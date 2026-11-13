#!/usr/bin/env python3
"""Blip — the firmware flasher behind the simulator's "Flash" tab.

Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.

Standard library only. tools/sim_radar.py hands every /api/flash/* request and
/flasher.html to handle(); the page (web/flasher.html) does the rest.

Two ways to flash, both shown step by step on the page:

Quick flash (default) writes the firmware that ships in firmware/prebuilt/.
  1 Firmware    pick the image for the board + radar, check its SHA-256 against
                manifest.json, and say whether it matches the source in this folder
  2 Flash tool  find esptool, or pip-install it into ./.venv (about 40 MB, once)
  3 Upload      esptool --chip <chip> write_flash 0x0 <image>
  4 Boot        optional: tools/serial_tail.py shows the board's serial output

Build from source compiles this folder with PlatformIO (needs Git and a few GB once).
  1 Prepare     python tools/embed_web.py        (web/index.html -> firmware/include/web_ui.h)
  2 PlatformIO  find it, or install it into ./.venv
  3 Build       pio run -d firmware -e <env>
  4 Upload      pio run -d firmware -e <env> -t upload [--upload-port <port>]
  5 Boot        as above

Safety. This runs programs on your computer, so:
  * only requests from this computer are answered (loopback address AND a
    localhost Host header, which also stops DNS-rebinding tricks),
  * starting/cancelling needs a random per-run token that only this page gets,
  * cross-site requests are refused,
  * the board, radar, mode and port are checked against fixed lists; nothing from
    the browser ever reaches a shell (argument lists only).

Tests set BLIP_PIO / BLIP_ESPTOOL to a stand-in (tests/fake_pio.py), may point
BLIP_PREBUILT at a copy of firmware/prebuilt, and BLIP_PORTS to pretend ports exist.
"""
import glob
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE = os.path.join(ROOT, "firmware")
PREBUILT = os.environ.get("BLIP_PREBUILT") or os.path.join(FIRMWARE, "prebuilt")
VENV = os.path.join(ROOT, ".venv")
PAGE = os.path.join(ROOT, "web", "flasher.html")
WIN = sys.platform.startswith("win")
MAC = sys.platform == "darwin"
ESPTOOL_PIP = "esptool>=4.7,<5"

ENABLED = True
TOKEN = secrets.token_urlsafe(18)

BOARDS = {
    "c3": {"name": "ESP32-C3 Super Mini", "env": "c3-supermini", "chip": "esp32c3",
           "blurb": "Tiny and cheap. USB-C straight on the chip."},
    "s3": {"name": "Waveshare ESP32-S3-Pico", "env": "s3-pico", "chip": "esp32s3",
           "blurb": "Pico-shaped, 16 MB flash, CH343 USB-UART."},
}
RADARS = {
    "rd03d": {"name": "Ai-Thinker RD-03D", "suffix": "",
              "blurb": "The default. 8 m, 1.25 mm connector."},
    "ld2450": {"name": "HLK-LD2450", "suffix": "-ld2450",
               "blurb": "2.54 mm header, about 6 m. New, untested on hardware."},
    "bench": {"name": "Bench test (not Blip)", "suffix": "-bench",
              "blurb": "Pass/fail check of a new board: RAM, flash, Wi-Fi, pins, then a 2-min Stetho + Wi-Fi run. "
                       "Results show in the log below. Flash Blip again afterwards."},
}
MODES = {
    "quick": ["Firmware", "Flash tool", "Upload", "Boot"],
    "source": ["Prepare", "PlatformIO", "Build", "Upload", "Boot"],
    "log": ["Serial tool", "USB log"],          # no flashing: just show the board's serial output
}

# Friendly explanations for the errors people actually hit. First match per id wins.
HINTS = [
    ("perm", r"Permission denied.*(/dev/tty|/dev/cu)|\[Errno 13\].*(/dev/tty|/dev/cu)|could not open port.*Permission denied",
     "The computer won't let Blip use the serial port",
     "On Linux add yourself to the serial group, then log out and back in:  sudo usermod -aG dialout $USER  (Arch: uucp). "
     "To just try it first, start Blip once with sudo."),
    ("busy", r"Access is denied.*COM\d+|PermissionError\(13.*COM\d+|could not open port 'COM\d+'.*(denied|busy)",
     "Another program is using the port",
     "Close any serial monitor, Arduino IDE or another flasher that has the board open, then try again."),
    ("venv", r"ensurepip is not|No module named venv|python3-venv|The virtual environment was not created",
     "Python's venv module is missing",
     "Debian / Ubuntu / Mint:  sudo apt install python3-venv  — then press Flash again."),
    ("git", r"git: command not found|'git' is not recognized|No such file or directory: 'git'|Could not find the .git. executable|git\" command not found",
     "Git is needed to build from source",
     "PlatformIO fetches Blip's libraries from GitHub with Git. Install it from https://git-scm.com/downloads (macOS: run  xcode-select --install ), "
     "then press Flash again — or use Quick flash, which needs no Git."),
    ("boot", r"Failed to connect to ESP32|Wrong boot mode|No serial data received|Timed out waiting for packet header|A fatal error occurred: Failed to connect",
     "The board isn't in flashing mode",
     "Hold BOOT, tap RESET, release BOOT, then press Flash again. Check the cable is a data cable (some only charge)."),
    ("noport", r"Please specify .upload_port|Error: Please specify|could not find .*serial port|Auto-detected: None|Could not connect to an Espressif device on any of|\[Errno 2\] could not open port",
     "No board found",
     "Plug the board in with a USB data cable. If nothing appears, hold BOOT while plugging it in. The S3-Pico needs the CH343 driver on Windows and older macOS."),
    ("net", r"Could not resolve|Temporary failure in name resolution|Max retries exceeded|ConnectionError|Connection refused|HTTPSConnectionPool|getaddrinfo failed|ReadTimeoutError|Network is unreachable|Failed to establish a new connection|SSLError|CERTIFICATE_VERIFY_FAILED",
     "This step needs the internet",
     "The first run downloads the flashing tools (Quick flash: about 40 MB; Build from source: a few GB). Connect, then press Flash again — it carries on where it stopped."),
    ("disk", r"No space left on device",
     "The disk is full", "Building from source needs several GB for the ESP32 toolchain. Free some space, or use Quick flash."),
]
_HINT_RE = [(i, re.compile(rx, re.I), t, x) for i, rx, t, x in HINTS]
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


# ---------------------------------------------------------------------------
# Serial ports (standard library only)
# ---------------------------------------------------------------------------
def list_ports():
    if os.environ.get("BLIP_PORTS") is not None:          # tests: pretend these USB ports exist
        return [{"port": x, "desc": "test"} for x in os.environ["BLIP_PORTS"].split(",") if x]
    ports = []
    if WIN:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as k:
                i = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    ports.append({"port": str(val), "desc": name.replace("\\Device\\", "")})
                    i += 1
        except OSError:
            pass
        ports.sort(key=lambda p: int(re.sub(r"\D", "", p["port"]) or 0))
    else:
        pats = ["/dev/cu.usbmodem*", "/dev/cu.usbserial*", "/dev/cu.wchusbserial*", "/dev/cu.SLAB*"] if MAC \
            else ["/dev/ttyACM*", "/dev/ttyUSB*"]
        names = {}
        for link in glob.glob("/dev/serial/by-id/*"):               # Linux: friendly names
            names[os.path.realpath(link)] = os.path.basename(link).replace("usb-", "", 1)
        for pat in pats:
            for p in sorted(glob.glob(pat)):
                ports.append({"port": p, "desc": names.get(os.path.realpath(p), "")})
    return ports


def port_ok(port):
    return port == "auto" or port in {p["port"] for p in list_ports()}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
def _venv_exe(name):
    d = os.path.join(VENV, "Scripts" if WIN else "bin")
    return os.path.join(d, name + (".exe" if WIN else ""))


def pio_cmd():
    """argv prefix that runs PlatformIO, or None if it is not installed yet."""
    ov = os.environ.get("BLIP_PIO")
    if ov:
        return shlex.split(ov)
    p = _venv_exe("pio")
    if os.path.exists(p):
        return [p]
    w = shutil.which("pio") or shutil.which("platformio")
    return [w] if w else None


_ESPTOOL = {"t": 0.0, "cmd": None}


def esptool_cmd(fresh=False):
    """argv prefix that runs esptool (python -m esptool), or None. Cached: the page polls."""
    ov = os.environ.get("BLIP_ESPTOOL")
    if ov:
        return shlex.split(ov)
    if not fresh and time.time() - _ESPTOOL["t"] < 30:
        return _ESPTOOL["cmd"]
    found = None
    vpy = _venv_exe("python")
    for py in ([vpy] if os.path.exists(vpy) else []) + [sys.executable]:
        try:
            if subprocess.run([py, "-c", "import esptool"], capture_output=True, timeout=30).returncode == 0:
                found = [py, "-m", "esptool"]
                break
        except (OSError, subprocess.SubprocessError):
            pass
    _ESPTOOL.update(t=time.time(), cmd=found)
    return found


def env_name(board, radar):
    return BOARDS[board]["env"] + RADARS[radar]["suffix"]


# ---------------------------------------------------------------------------
# Bundled firmware (firmware/prebuilt/manifest.json, written by tools/make_prebuilt.py)
# ---------------------------------------------------------------------------
SOURCE_DIRS = ("firmware/src", "firmware/include")
SOURCE_FILES = ("firmware/platformio.ini", "web/index.html")
SOURCE_SKIP = ("firmware/include/web_ui.h",)          # generated from web/index.html, which is hashed instead


def source_hash(root=ROOT):
    """SHA-256 over the firmware sources, line endings normalised (so a Windows checkout matches)."""
    rels = list(SOURCE_FILES)
    for d in SOURCE_DIRS:
        for dp, dn, fn in os.walk(os.path.join(root, d)):
            dn.sort()
            for f in fn:
                rels.append(os.path.relpath(os.path.join(dp, f), root).replace(os.sep, "/"))
    h = hashlib.sha256()
    for rel in sorted(set(rels)):
        if rel in SOURCE_SKIP:
            continue
        try:
            with open(os.path.join(root, rel), "rb") as f:
                data = f.read().replace(b"\r\n", b"\n")
        except OSError:
            continue
        h.update(rel.encode() + b"\0" + data + b"\0")
    return h.hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest():
    try:
        with open(os.path.join(PREBUILT, "manifest.json"), encoding="utf-8") as f:
            m = json.load(f)
        return m if isinstance(m.get("images"), dict) else None
    except (OSError, ValueError, AttributeError):
        return None


def image_for(env):
    """(path, entry) of the bundled image for env, or (None, reason)."""
    m = manifest()
    if not m:
        return None, "There is no bundled firmware in firmware/prebuilt/."
    e = m["images"].get(env)
    if not isinstance(e, dict) or not isinstance(e.get("file"), str) or os.path.basename(e["file"]) != e["file"]:
        return None, "The bundled firmware has no image for %s." % env
    p = os.path.join(PREBUILT, e["file"])
    if not os.path.isfile(p):
        return None, "%s is missing from firmware/prebuilt/." % e["file"]
    return p, e


_SRC = {"t": 0.0, "h": ""}


def prebuilt_info():
    m = manifest()
    if not m:
        return None
    if time.time() - _SRC["t"] > 5:                  # the page polls every 2 s; hashing ~20 files is cheap but not free
        _SRC.update(t=time.time(), h=source_hash())
    imgs = {k: {"file": v.get("file"), "sha256": v.get("sha256"), "size": v.get("size")}
            for k, v in m["images"].items() if isinstance(v, dict)}
    return {"version": m.get("version"), "built": m.get("built"), "images": imgs, "matches": m.get("source") == _SRC["h"]}


def _kill(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        if WIN:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGTERM)

            def later():
                if proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except OSError:
                        pass
            threading.Timer(3.0, later).start()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# The job
# ---------------------------------------------------------------------------
class Job:
    MAX_LINES = 3000

    def __init__(self):
        self.lock = threading.Lock()
        self.thread = None
        self.proc = None
        self._reset("idle", "quick")

    def _reset(self, state, mode):
        self.state = state                  # idle | running | monitoring | done | error | cancelled
        self.mode = mode
        self.names = MODES[mode]
        self.steps = ["todo"] * len(self.names)
        self.step = -1
        self.lines, self.base = [], 0
        self.pct = None
        self.activity = ""
        self.hints = {}
        self.flashed = False
        self.cancel = False
        self.env = ""
        self.port = ""
        self.monitor = False
        self.image = None                   # what Quick flash wrote: file, sha256, size, version
        self.t0 = 0.0
        self.seg_big = False
        self.last_decade = -1

    # -- log -----------------------------------------------------------------
    def log(self, text):
        with self.lock:
            self.lines.append(text)
            if len(self.lines) > self.MAX_LINES:
                drop = len(self.lines) - self.MAX_LINES
                del self.lines[:drop]
                self.base += drop

    def say(self, text):                    # Blip's own commentary, drawn differently by the page
        self.log("▸ " + text)

    def hint(self, hid, title, text):
        with self.lock:
            self.hints.setdefault(hid, {"id": hid, "title": title, "text": text})

    def _line(self, raw):
        s = _ANSI.sub("", raw).rstrip()
        if not s.strip():
            return
        for hid, rx, title, text in _HINT_RE:
            if hid not in self.hints and rx.search(s):
                self.hint(hid, title, text)
        m = re.search(r"Compressed (\d+) bytes", s)
        if m:                                # a new flash segment: only the big one (the app) drives the bar
            self.seg_big = int(m.group(1)) > 200_000
            self.pct = None
            self.last_decade = -1
        m = re.search(r"Writing at 0x[0-9a-f]+\.*\s*\(\s*(\d+)\s*%\)", s, re.I)
        if m:
            p = int(m.group(1))
            if self.seg_big:
                self.pct = p
            self.activity = "Writing flash… %d %%" % p if self.seg_big else "Writing flash…"
            if p // 10 != self.last_decade or p >= 100:      # esptool prints a line per few KB; keep one per 10 %
                self.last_decade = p // 10
                self.log(s)
            return
        self.activity = s.strip()[:140]
        self.log(s)

    # -- running programs ----------------------------------------------------
    def _exec(self, cmd, cwd=None):
        self.log("$ " + subprocess.list2cmdline(cmd) if WIN else "$ " + " ".join(shlex.quote(c) for c in cmd))
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", NO_COLOR="1", TERM="dumb",
                   PLATFORMIO_DISABLE_PROGRESSBAR="true")
        kw = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=cwd or ROOT, env=env)
        if WIN:
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        if self.cancel:
            return 130
        try:
            proc = subprocess.Popen(cmd, **kw)
        except OSError as e:
            self._line("Could not start %s: %s" % (cmd[0], e))
            return 127
        self.proc = proc
        if self.cancel:                      # cancel pressed while it was starting
            _kill(proc)
        buf = b""
        while True:
            chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(1)
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for p in parts:
                self._line(p.decode("utf-8", "replace"))
        if buf:
            self._line(buf.decode("utf-8", "replace"))
        rc = proc.wait()
        self.proc = None
        return rc

    def _set_step(self, i):
        with self.lock:
            if 0 <= self.step < len(self.steps) and self.steps[self.step] == "active":
                self.steps[self.step] = "done"
            self.step = i
            self.steps[i] = "active"
            self.pct = None
            self.activity = ""

    def _fail(self, msg):
        with self.lock:
            if 0 <= self.step < len(self.steps):
                self.steps[self.step] = "error"
            self.state = "cancelled" if self.cancel else "error"
        self.say("Cancelled." if self.cancel else msg)

    # -- tools ---------------------------------------------------------------
    def _pip_install(self, what, label):
        self.say("%s isn't installed yet. Installing it into .venv (one-off, needs the internet)." % label)
        py = _venv_exe("python")
        if not os.path.exists(py):
            if self._exec([sys.executable, "-m", "venv", VENV]) or self.cancel:
                return False
        return self._exec([py, "-m", "pip", "install", "--progress-bar", "off", what]) == 0 and not self.cancel

    def _resolve_monitor_port(self, port):
        if port != "auto":
            return port
        self.activity = "Looking for the board's serial port…"
        for _ in range(12):                  # the C3 re-enumerates after a flash; give it a moment
            if self.cancel:
                return None
            ports = list_ports()
            if len(ports) == 1:
                return ports[0]["port"]
            if len(ports) > 1:
                return None
            time.sleep(0.5)
        return None

    # -- the two ways to get the firmware onto the board ---------------------
    def _quick(self, board, env, port):
        self._set_step(0)
        path, e = image_for(env)
        if not path:
            self._fail(e + " Use Build from source instead.")
            return False
        m = manifest() or {}
        got = sha256_file(path)
        if not isinstance(e.get("sha256"), str) or got != e["sha256"].lower():
            self._fail("%s doesn't match its checksum in manifest.json (damaged or swapped). Not flashing it. "
                       "Use Build from source, or get a fresh copy of Blip." % e["file"])
            return False
        with self.lock:
            self.image = {"file": e["file"], "sha256": got, "size": os.path.getsize(path), "version": m.get("version"), "built": m.get("built")}
        self.say("Bundled firmware: %s — Blip %s, built %s, %d bytes." % (e["file"], m.get("version"), m.get("built"), os.path.getsize(path)))
        self.say("SHA-256 %s — matches manifest.json." % got)
        if m.get("source") == source_hash():
            self.say("It was built from exactly the source in this folder.")
        else:
            self.say("This folder's source differs from what the bundled firmware was built from.")
            self.hint("stale", "Your source has changed since the bundled firmware was built",
                      "Quick flash writes the bundled version, not your changes. To flash your own changes, choose Build from source.")

        self._set_step(1)
        cmd = esptool_cmd(fresh=True)
        if cmd:
            self.say("esptool found: " + " ".join(cmd))
        elif not self._pip_install(ESPTOOL_PIP, "esptool"):
            self._fail("Could not install esptool.")
            return False
        cmd = esptool_cmd(fresh=True)
        if not cmd:
            self._fail("esptool is still missing after the install.")
            return False

        self._set_step(2)
        if port == "auto":                   # esptool alone would also probe /dev/ttyS*, COM1 etc. and hang there
            ports = list_ports()
            if len(ports) != 1:
                if not ports:
                    self.hint("noport", *[(t, x) for i, _, t, x in _HINT_RE if i == "noport"][0])
                self._fail("No USB serial port found — plug the board in." if not ports else
                           "Found %d serial ports (%s) — pick the board's one above." % (len(ports), ", ".join(p["port"] for p in ports)))
                return False
            port = ports[0]["port"]
            self.say("Auto-detect: the only USB serial port is %s." % port)
        self.say("Writing the whole image at address 0x0 (bootloader, partition table and app in one file).")
        up = cmd + ["--chip", BOARDS[board]["chip"], "--port", port] + \
            ["--baud", "460800", "--before", "default_reset", "--after", "hard_reset", "write_flash", "0x0", path]
        if self._exec(up) or self.cancel:
            self._fail("The upload failed. See the tip below, or hold BOOT, tap RESET and try again.")
            return False
        return True

    def _source(self, env, port):
        self._set_step(0)
        if self._exec([sys.executable, os.path.join(ROOT, "tools", "embed_web.py")]) or self.cancel:
            self._fail("Could not rebuild the embedded web page.")
            return False

        self._set_step(1)
        cmd = pio_cmd()
        if cmd:
            self.say("PlatformIO found: " + cmd[-1])
        elif not self._pip_install("platformio", "PlatformIO"):
            self._fail("Could not install PlatformIO.")
            return False
        cmd = pio_cmd()
        if not cmd:
            self._fail("PlatformIO is still missing after the install.")
            return False

        self._set_step(2)
        self.say("Building %s. The first build downloads the ESP32 toolchain and libraries (a few GB, needs Git) — allow 5–15 minutes." % env)
        if self._exec(cmd + ["run", "-d", FIRMWARE, "-e", env]) or self.cancel:
            self._fail("The build failed. The red lines above say why.")
            return False

        self._set_step(3)
        self.say("Uploading%s." % ("" if port == "auto" else " to " + port))
        up = cmd + ["run", "-d", FIRMWARE, "-e", env, "-t", "upload"]
        if port != "auto":
            up += ["--upload-port", port]
        if self._exec(up) or self.cancel:
            self._fail("The upload failed. See the tip below, or hold BOOT, tap RESET and try again.")
            return False
        return True

    def _usb_log(self, port):
        """Show the board's serial output without flashing anything."""
        self._set_step(0)
        def has_serial(exe):
            return os.path.exists(exe) and subprocess.run([exe, "-c", "import serial"], capture_output=True).returncode == 0
        py = next((x for x in (_venv_exe("python"), sys.executable) if has_serial(x)), None)
        if py is None:
            if not self._pip_install("pyserial", "The serial tool (pyserial)"):
                self._fail("Couldn't install the serial tool. See the tip below.")
                return
            py = _venv_exe("python")
        self._set_step(1)
        mport = self._resolve_monitor_port(port)
        if mport is None:
            if not self.cancel:
                self._fail("No single USB board found. Plug the board in (or pick its port above) and try again.")
            return
        with self.lock:
            self.state = "monitoring"
        self.say("Watching %s at 115200 baud. Press RESET on the board to see it start; the node also prints a health line every 10 s." % mport)
        self._exec([py, os.path.join(ROOT, "tools", "serial_tail.py"), mport, "115200"])
        with self.lock:
            self.steps[1] = "done"
            self.state = "done"
        self.say("Stopped watching the serial port.")

    def run(self, mode, board, env, port, monitor):
        if mode == "log":
            try:
                self._usb_log(port)
            except Exception as e:
                self._fail("Internal error: %r" % (e,))
            finally:
                with self.lock:
                    if self.state in ("running", "monitoring"):
                        self.state = "error"
                    self.proc = None
            return
        try:
            ok = self._quick(board, env, port) if mode == "quick" else self._source(env, port)
            if not ok:
                return
            boot = len(self.names) - 1
            with self.lock:
                self.flashed = True
                self.steps[boot - 1] = "done"
            self._set_step(boot)
            mport = self._resolve_monitor_port(port) if monitor else None
            if not monitor or mport is None:
                with self.lock:
                    self.steps[boot] = "done"
                    self.state = "done"
                if monitor and not self.cancel:
                    self.say("Flashed. I couldn't tell which port to watch (none or several found) — pick one above next time to see the board's output.")
                else:
                    self.say("Flashed. Press RESET on the board if it doesn't start by itself.")
                return
            with self.lock:
                self.state = "monitoring"
            self.say("Flashed. Watching %s at 115200 baud. Press RESET on the board to see it boot." % mport)
            py = _venv_exe("python")
            py = py if os.path.exists(py) else sys.executable
            self._exec([py, os.path.join(ROOT, "tools", "serial_tail.py"), mport, "115200"])
            with self.lock:
                self.steps[boot] = "done"
                self.state = "done"
            self.say("Stopped watching the serial port.")
        except Exception as e:               # never leave the page spinning
            self._fail("Internal error: %r" % (e,))
        finally:
            with self.lock:
                if self.state in ("running", "monitoring"):
                    self.state = "done" if self.flashed else "error"
                self.proc = None

    # -- API -----------------------------------------------------------------
    def start(self, board, radar, port, monitor, mode="quick"):
        with self.lock:
            if self.state in ("running", "monitoring"):
                return False
            self._reset("running", mode)
            self.env = env_name(board, radar)
            self.port = port
            self.monitor = monitor
            self.t0 = time.time()
        if mode == "log":
            self.say("Opening the board's USB log (nothing is flashed).")
        else:
            how = "the bundled %s firmware" % RADARS[radar]["name"] if mode == "quick" else "%s firmware built from this folder" % RADARS[radar]["name"]
            self.say("Flashing %s with %s (%s)." % (BOARDS[board]["name"], how, self.env))
        self.thread = threading.Thread(target=self.run, args=(mode, board, self.env, port, monitor), daemon=True)
        self.thread.start()
        return True

    def stop(self):
        with self.lock:
            if self.state not in ("running", "monitoring"):
                return False
            self.cancel = True
            proc = self.proc
        _kill(proc)
        return True

    def snapshot(self, since=0):
        with self.lock:
            start = min(max(0, since - self.base), len(self.lines))
            return {
                "state": self.state, "mode": self.mode, "step": self.step, "flashed": self.flashed, "env": self.env,
                "port": self.port, "monitor": self.monitor, "pct": self.pct, "activity": self.activity, "image": self.image,
                "elapsed": round(time.time() - self.t0, 1) if self.t0 and self.state in ("running", "monitoring") else 0,
                "steps": [{"name": n, "status": s} for n, s in zip(self.names, self.steps)],
                "hints": list(self.hints.values()),
                "from": self.base + start, "next": self.base + len(self.lines),
                "lines": self.lines[start:],
            }


JOB = Job()


def shutdown():
    JOB.stop()


# ---------------------------------------------------------------------------
# HTTP glue (called by tools/sim_radar.py)
# ---------------------------------------------------------------------------
def _json(h, code, obj):
    h._send(code, "application/json", json.dumps(obj))


def _local_only(h):
    ip = h.client_address[0]
    if ip not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        return "Flashing is only available from the computer that runs Blip."
    host = (h.headers.get("Host") or "").strip().lower()
    name = host.split("]")[0] + "]" if host.startswith("[") else host.rsplit(":", 1)[0]
    if name not in ("127.0.0.1", "localhost", "[::1]"):
        return "Open Blip as http://127.0.0.1:<port>/ or http://localhost:<port>/ to flash."
    if (h.headers.get("Sec-Fetch-Site") or "same-origin") not in ("same-origin", "none"):
        return "Cross-site request refused."
    origin = h.headers.get("Origin")
    if origin and urlparse(origin).netloc.lower() != host:
        return "Cross-site request refused."
    return None


def _body(h):
    """Read the request body (always, so a keep-alive connection stays in step)."""
    try:
        n = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        n = 0
    if n > 65536:
        h.close_connection = True
        return None
    return h.rfile.read(n) if n > 0 else b""


HOME = os.path.join(ROOT, "web", "flash_home.html")


def _version():
    try:
        with open(os.path.join(ROOT, "firmware", "platformio.ini"), encoding="utf-8") as f:
            m = re.search(r'BLIP_VERSION="([^"]+)"', f.read())
        return "v" + m.group(1) if m else ""
    except OSError:
        return ""


def home_page():
    """The launcher's first page: web/flash_home.html with the flasher (web/flasher.html) inlined."""
    with open(HOME, encoding="utf-8") as f:
        home = f.read()
    with open(PAGE, encoding="utf-8") as f:
        frag = f.read()
    style = "".join(re.findall(r"<style>.*?</style>", frag, re.S))
    body = re.search(r"<body>(.*)</body>", frag, re.S).group(1)
    body = body.replace('<section id="flash">', '<section id="flash" class="on">', 1)
    return (home.replace("__FLASHER__", style + body)
                .replace("__BLIP_TOKEN__", TOKEN).replace("__VERSION__", _version()))


def handle(h, path, query):
    """Answer /flasher.html and /api/flash/*. `h` is the request handler."""
    post = h.command == "POST"
    raw = _body(h) if post else b""
    if not ENABLED:
        return _json(h, 404, {"error": "The flasher is switched off (--no-flash)."})
    why = _local_only(h)
    if why:
        return _json(h, 403, {"error": why})
    if raw is None:
        return _json(h, 413, {"error": "Request too large"})

    if path == "/" and not post:
        return h._send(200, "text/html; charset=utf-8", home_page().encode("utf-8"))

    if path == "/flasher.html" and not post:
        try:
            with open(PAGE, "r", encoding="utf-8") as f:
                body = f.read().replace("__BLIP_TOKEN__", TOKEN)
        except OSError:
            return _json(h, 404, {"error": "web/flasher.html is missing"})
        return h._send(200, "text/html; charset=utf-8", body)

    if path == "/api/flash/info" and not post:
        pio = pio_cmd()
        return _json(h, 200, {
            "os": "win" if WIN else "mac" if MAC else "linux",
            "boards": [dict(id=k, **v) for k, v in BOARDS.items()],
            "radars": [dict(id=k, **v) for k, v in RADARS.items()],
            "modes": MODES,
            "ports": list_ports(),
            "pio": {"state": "ready" if pio else "install"},
            "esptool": {"state": "ready" if esptool_cmd() else "install"},
            "prebuilt": prebuilt_info(),
            "job": JOB.snapshot(1 << 62),      # no lines: the page asks /api/flash/log for those
        })

    if path == "/api/flash/log" and not post:
        try:
            since = int(parse_qs(query).get("from", ["0"])[0])
        except ValueError:
            since = 0
        return _json(h, 200, JOB.snapshot(max(0, since)))

    if path in ("/api/flash/start", "/api/flash/cancel") and post:
        if not secrets.compare_digest((h.headers.get("X-Blip-Token") or "").encode(), TOKEN.encode()):
            return _json(h, 403, {"error": "Missing or wrong token. Reload the page."})
        if path == "/api/flash/cancel":
            return _json(h, 200, {"ok": JOB.stop()})
        try:
            req = json.loads(raw or b"{}")
        except ValueError:
            return _json(h, 400, {"error": "Bad request"})
        if not isinstance(req, dict):
            return _json(h, 400, {"error": "Bad request"})
        board, radar, mode = req.get("board"), req.get("radar", "rd03d"), req.get("mode", "quick")
        port, monitor = req.get("port", "auto"), req.get("monitor", True) is True
        if board not in BOARDS or radar not in RADARS or mode not in MODES:
            return _json(h, 400, {"error": "Unknown board, radar or mode"})
        if not isinstance(port, str) or not port_ok(port):
            return _json(h, 400, {"error": "That serial port isn't there any more. Pick another or use Auto-detect."})
        if mode == "quick":
            p, why = image_for(env_name(board, radar))
            if not p:
                return _json(h, 400, {"error": why + " Use Build from source."})
        if not JOB.start(board, radar, port, monitor, mode):
            return _json(h, 409, {"error": "A flash is already running."})
        return _json(h, 200, {"ok": True, "env": JOB.env, "mode": mode})

    return _json(h, 404, {"error": "Not found"})
