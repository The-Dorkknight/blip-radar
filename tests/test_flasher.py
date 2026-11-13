#!/usr/bin/env python3
"""Blip — tests for the Flash tab's backend (tools/flasher.py) with a fake PlatformIO.

    python3 tests/test_flasher.py

No board, no internet, no PlatformIO needed: BLIP_PIO points at tests/fake_pio.py,
which prints what `pio run` and esptool print and fails the common ways.
Part 1 drives the job runner directly; part 2 starts the real simulator and
checks the HTTP side (token, localhost-only, validation, a full run).
"""
import http.client
import json
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
FAKE = "%s %s" % (shlex.quote(sys.executable), shlex.quote(os.path.join(ROOT, "tests", "fake_pio.py")))
TMP = tempfile.mkdtemp()
os.environ["BLIP_PIO"] = FAKE
os.environ["BLIP_ESPTOOL"] = FAKE
os.environ["FAKE_PIO_LOG"] = os.path.join(TMP, "argv.log")
os.environ["FAKE_PIO_PID"] = os.path.join(TMP, "pid")
import flasher  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    print(("PASS  " if cond else "FAIL  ") + msg)
    fails += not cond


def until(pred, timeout=30.0, every=0.02):
    t = time.time()
    while time.time() - t < timeout:
        if pred():
            return True
        time.sleep(every)
    return False


def run_job(board, radar, port, mode="ok", monitor=False, how="source"):
    os.environ["FAKE_PIO_MODE"] = mode
    open(os.environ["FAKE_PIO_LOG"], "w").close()
    ok = flasher.JOB.start(board, radar, port, monitor, how)
    peak, seen = [0], []

    def watch():
        while flasher.JOB.state == "running":
            p = flasher.JOB.snapshot(1 << 30)["pct"]
            if p is not None:
                seen.append(p)
                peak[0] = max(peak[0], p)
            time.sleep(0.01)
    th = threading.Thread(target=watch, daemon=True)
    th.start()
    until(lambda: flasher.JOB.state not in ("running",), 60)
    th.join(2)
    return ok, flasher.JOB.snapshot(0), peak[0], seen


def argv_log():
    return open(os.environ["FAKE_PIO_LOG"]).read().splitlines()


# ---------------------------------------------------------------------------
print("-- names, hints, guard")
check(flasher.env_name("c3", "rd03d") == "c3-supermini", "env: C3 + RD-03D -> c3-supermini")
check(flasher.env_name("s3", "ld2450") == "s3-pico-ld2450", "env: S3 + LD2450 -> s3-pico-ld2450")

j = flasher.Job()
for line, want in (
        ("([Errno 13] could not open port /dev/ttyACM0: [Errno 13] Permission denied: '/dev/ttyACM0')", "perm"),
        ("A fatal error occurred: Failed to connect to ESP32-C3: No serial data received.", "boot"),
        ("The virtual environment was not created successfully because ensurepip is not available.", "venv"),
        ("Error: HTTPSConnectionPool(host='x', port=443): Max retries exceeded", "net"),
        ("sh: 1: git: command not found", "git"),
        ("OSError: [Errno 28] No space left on device", "disk")):
    j2 = flasher.Job()
    j2._line(line)
    check(want in j2.hints, "hint '%s' recognised" % want)
for line in ("Compiling .pio/build/c3-supermini/src/main.cpp.o", "Writing at 0x00010000... (45 %)", "[SUCCESS] Took 3.5 seconds"):
    j._line(line)
check(not j.hints, "normal build/upload lines raise no hints")


class H:
    def __init__(self, ip="127.0.0.1", host="127.0.0.1:8080", **hdr):
        self.client_address = (ip, 5555)
        self.headers = dict({"Host": host}, **hdr)


check(flasher._local_only(H()) is None, "guard: 127.0.0.1 with a localhost Host is allowed")
check(flasher._local_only(H(host="localhost:8080")) is None, "guard: localhost Host is allowed")
check(flasher._local_only(H(host="[::1]:8080", ip="::1")) is None, "guard: IPv6 loopback is allowed")
check(flasher._local_only(H(ip="192.168.1.20")) is not None, "guard: a LAN address is refused")
check(flasher._local_only(H(host="evil.example:8080")) is not None, "guard: a foreign Host header (DNS rebinding) is refused")
check(flasher._local_only(H(**{"Sec-Fetch-Site": "cross-site"})) is not None, "guard: cross-site fetch is refused")
check(flasher._local_only(H(Origin="http://evil.example")) is not None, "guard: foreign Origin is refused")
check(flasher._local_only(H(Origin="http://127.0.0.1:8080")) is None, "guard: same Origin is allowed")

# ---------------------------------------------------------------------------
print("-- job runner")
ok, s, peak, seen = run_job("s3", "ld2450", "/dev/ttyACM0")
check(ok and s["state"] == "done" and s["flashed"], "normal run: finishes, flashed")
check([x["status"] for x in s["steps"]] == ["done"] * 5, "normal run: all five steps done")
a = argv_log()
check(any("-e s3-pico-ld2450" in x and "upload" not in x for x in a), "build call uses the s3-pico-ld2450 env")
check(any("-t upload" in x and "--upload-port /dev/ttyACM0" in x for x in a), "upload call passes --upload-port")
check(peak >= 90 and seen == sorted(seen), "progress bar follows the big segment (peak %d %%, never backwards)" % peak)
writing = [x for x in s["lines"] if x.startswith("Writing at")]
check(0 < len(writing) <= 25, "esptool's progress spam is thinned (%d 'Writing at' lines kept)" % len(writing))
check(any(x.startswith("$ ") for x in s["lines"]) and any(x.startswith("▸ ") for x in s["lines"]), "log shows commands and Blip's own notes")
check(s["from"] == 0 and s["next"] == len(s["lines"]), "log cursor covers the whole log")
later = flasher.JOB.snapshot(s["next"])
check(later["lines"] == [] and later["next"] == s["next"], "asking from the cursor returns only new lines")

ok, s, _, _ = run_job("c3", "rd03d", "auto")
check(not any("--upload-port" in x for x in argv_log()), "port Auto-detect passes no --upload-port")

ok, s, _, _ = run_job("c3", "rd03d", "auto", mode="perm")
check(s["state"] == "error" and not s["flashed"] and s["steps"][3]["status"] == "error", "permission failure: stops at Upload")
check("perm" in [h["id"] for h in s["hints"]], "permission failure: shows the dialout tip")

ok, s, _, _ = run_job("c3", "rd03d", "auto", mode="boot")
check("boot" in [h["id"] for h in s["hints"]], "connect failure: shows the BOOT/RESET tip")

ok, s, _, _ = run_job("c3", "rd03d", "auto", mode="builderror")
check(s["state"] == "error" and s["steps"][2]["status"] == "error" and s["steps"][3]["status"] == "todo", "build error: stops at Build, never uploads")
check(not any("upload" in x for x in argv_log()), "build error: upload was never attempted")

ok, s, _, _ = run_job("c3", "rd03d", "auto", mode="net")
check("net" in [h["id"] for h in s["hints"]], "network failure: shows the internet tip")

# cancel mid-build kills the process
os.environ["FAKE_PIO_MODE"] = "slow"
flasher.JOB.start("c3", "rd03d", "auto", False, "source")
check(until(lambda: flasher.JOB.step == 2 and any("Compiling" in x for x in flasher.JOB.snapshot(0)["lines"]), 20), "slow run reaches the build step")
check(flasher.JOB.start("c3", "rd03d", "auto", False, "quick") is False, "a second start while one runs is refused")
check(flasher.JOB.stop(), "cancel is accepted")
check(until(lambda: flasher.JOB.state != "running", 10) and flasher.JOB.state == "cancelled", "cancelled run ends as 'cancelled'")
pid = int(open(os.environ["FAKE_PIO_PID"]).read())


def dead():
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
check(until(dead, 5), "cancel really killed the build process")
check(flasher.JOB.stop() is False, "cancel with nothing running is a no-op")

# ---------------------------------------------------------------------------
print("-- quick flash (bundled firmware)")
import json as _json  # noqa: E402
import shutil  # noqa: E402
man = flasher.manifest()
check(man is not None and set(man["images"]) == {"c3-supermini", "s3-pico", "c3-supermini-ld2450", "s3-pico-ld2450", "c3-supermini-bench", "s3-pico-bench"}, "bundled firmware: manifest lists all six images (4 Blip + 2 bench)")
for env, e in (man or {"images": {}})["images"].items():
    pth = os.path.join(flasher.PREBUILT, e["file"])
    with open(pth, "rb") as f:
        magic = f.read(1)
    check(os.path.isfile(pth) and flasher.sha256_file(pth) == e["sha256"] and magic == b"\xe9", "bundled %s: checksum matches, starts with an ESP image header" % env)
check((man or {}).get("version") == open(os.path.join(ROOT, "firmware", "include", "config.h")).read().split('BLIP_VERSION "')[1].split('"')[0],
      "bundled firmware version = firmware version")
check((man or {}).get("source") == flasher.source_hash(), "bundled firmware was built from exactly this source (run tools/make_prebuilt.py after changing firmware or web/index.html)")

ok, s, peak, _ = run_job("s3", "ld2450", "/dev/ttyACM0", how="quick")
check(ok and s["state"] == "done" and s["flashed"] and s["mode"] == "quick", "quick: finishes, flashed")
check([x["name"] for x in s["steps"]] == ["Firmware", "Flash tool", "Upload", "Boot"] and all(x["status"] == "done" for x in s["steps"]), "quick: its four steps, all done")
a = [x for x in argv_log() if "write_flash" in x]
check(len(a) == 1 and "--chip esp32s3" in a[0] and "--port /dev/ttyACM0" in a[0] and a[0].endswith("write_flash 0x0 " + os.path.join(flasher.PREBUILT, "blip-s3-pico-ld2450-full.bin")),
      "quick: esptool writes the S3 + LD2450 image at 0x0 on the chosen port")
check(not any(" run " in " %s " % x for x in argv_log()), "quick: PlatformIO is never called")
check(s["image"] and s["image"]["sha256"] == man["images"]["s3-pico-ld2450"]["sha256"], "quick: reports the exact image it wrote")
check(any(x.startswith("▸ SHA-256") for x in s["lines"]), "quick: the log shows the checksum it verified")
check(peak >= 90, "quick: progress bar follows the write (peak %d %%)" % peak)

os.environ["BLIP_PORTS"] = "/dev/ttyACM7"
ok, s, _, _ = run_job("c3", "rd03d", "auto", how="quick")
a = [x for x in argv_log() if "write_flash" in x]
check(a and "--chip esp32c3" in a[0] and "--port /dev/ttyACM7" in a[0], "quick: Auto-detect with one USB board uses that port (esptool never probes ttyS*/COM1)")
os.environ["BLIP_PORTS"] = ""
ok, s, _, _ = run_job("c3", "rd03d", "auto", how="quick")
check(s["state"] == "error" and s["steps"][2]["status"] == "error" and "noport" in [h["id"] for h in s["hints"]]
      and not any("write_flash" in x for x in argv_log()), "quick: Auto-detect with no board stops at once with the 'No board found' tip")
os.environ["BLIP_PORTS"] = "/dev/ttyACM0,/dev/ttyUSB0"
ok, s, _, _ = run_job("c3", "rd03d", "auto", how="quick")
check(s["state"] == "error" and any("pick the board" in x for x in s["lines"]), "quick: Auto-detect with two ports asks you to pick one")
os.environ["BLIP_PORTS"] = "/dev/ttyACM7"

ok, s, _, _ = run_job("c3", "rd03d", "/dev/ttyACM0", mode="perm", how="quick")
check(s["state"] == "error" and s["steps"][2]["status"] == "error" and "perm" in [h["id"] for h in s["hints"]], "quick: permission failure stops at Upload with the tip")

real_prebuilt = flasher.PREBUILT
tmp_pb = os.path.join(TMP, "prebuilt")
shutil.copytree(real_prebuilt, tmp_pb)
flasher.PREBUILT = tmp_pb
try:
    with open(os.path.join(tmp_pb, "blip-c3-supermini-full.bin"), "r+b") as f:
        f.seek(5000)
        b = f.read(1)
        f.seek(5000)
        f.write(bytes([b[0] ^ 0xFF]))
    ok, s, _, _ = run_job("c3", "rd03d", "auto", how="quick")
    check(s["state"] == "error" and s["steps"][0]["status"] == "error" and not s["flashed"], "quick: a damaged image is refused at the Firmware step")
    check(not any("write_flash" in x for x in argv_log()), "quick: nothing was written from the damaged image")
    check(any("checksum" in x for x in s["lines"]), "quick: says why (checksum)")

    m2 = _json.load(open(os.path.join(tmp_pb, "manifest.json")))
    m2["source"] = "0" * 64
    _json.dump(m2, open(os.path.join(tmp_pb, "manifest.json"), "w"))
    ok, s, _, _ = run_job("s3", "rd03d", "auto", how="quick")
    check(s["state"] == "done" and "stale" in [h["id"] for h in s["hints"]], "quick: changed source still flashes the bundle, with a 'build from source' tip")
    flasher._SRC["t"] = 0
    check(flasher.prebuilt_info()["matches"] is False, "info reports the bundle no longer matches the source")

    os.remove(os.path.join(tmp_pb, "manifest.json"))
    ok, s, _, _ = run_job("s3", "rd03d", "auto", how="quick")
    check(s["state"] == "error" and s["steps"][0]["status"] == "error", "quick: no bundled firmware -> clear error at the Firmware step")

    m3 = dict(m2, images={"c3-supermini": {"file": "../../../etc/passwd", "sha256": "x"}})
    _json.dump(m3, open(os.path.join(tmp_pb, "manifest.json"), "w"))
    check(flasher.image_for("c3-supermini")[0] is None, "quick: a manifest can't point outside firmware/prebuilt/")
finally:
    flasher.PREBUILT = real_prebuilt

# serial monitor after a flash, through a pty so no hardware is needed
try:
    import pty
    import serial  # noqa: F401
    master, slave = pty.openpty()
    name = os.ttyname(slave)
    os.environ["FAKE_PIO_MODE"] = "ok"
    flasher.JOB.start("c3", "rd03d", name, True)
    check(until(lambda: flasher.JOB.state == "monitoring", 30), "monitor: reaches 'monitoring' after the upload")
    time.sleep(1.0)
    os.write(master, b"boot: Blip 0.2.1 ip=192.168.4.1\r\n")
    check(until(lambda: any("ip=192.168.4.1" in x for x in flasher.JOB.snapshot(0)["lines"]), 8), "monitor: board output reaches the log")
    flasher.JOB.stop()
    check(until(lambda: flasher.JOB.state == "done", 8) and flasher.JOB.flashed, "monitor: Stop ends as done (still flashed)")
    # USB log without flashing
    open(os.environ["FAKE_PIO_LOG"], "w").close()
    flasher.JOB.start("c3", "rd03d", name, True, "log")
    check(until(lambda: flasher.JOB.state == "monitoring", 15), "USB log: reaches 'monitoring' without flashing")
    check(open(os.environ["FAKE_PIO_LOG"]).read().strip() == "", "USB log: no flash tool or build was run")
    time.sleep(1.0)
    os.write(master, b"[00:10.0] health: 150 KB free\r\n")
    check(until(lambda: any("health: 150 KB" in x for x in flasher.JOB.snapshot(0)["lines"]), 8), "USB log: board output reaches the log")
    check([x["name"] for x in flasher.JOB.snapshot(0)["steps"]] == ["Serial tool", "USB log"], "USB log: its own two steps")
    flasher.JOB.stop()
    check(until(lambda: flasher.JOB.state == "done", 8) and not flasher.JOB.flashed, "USB log: Stop ends as done, nothing flashed")
    os.close(master)
    os.close(slave)
except ImportError:
    print("SKIP  serial monitor (needs pty and pyserial)")

# ---------------------------------------------------------------------------
print("-- HTTP side (real simulator)")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def call(port, method, path, body=None, headers=None, host=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    c.putrequest(method, path, skip_host=True)
    c.putheader("Host", host or "127.0.0.1:%d" % port)
    for k, v in (headers or {}).items():
        c.putheader(k, v)
    data = json.dumps(body).encode() if body is not None else b""
    if method == "POST":
        c.putheader("Content-Length", str(len(data)))
    c.endheaders(data)
    r = c.getresponse()
    txt = r.read().decode()
    ctype = r.getheader("Content-Type", "")
    c.close()
    return r.status, (json.loads(txt) if ctype.startswith("application/json") else txt)


def start_sim(*extra):
    port = free_port()
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "tools", "sim_radar.py"), "--port", str(port), "--no-browser", *extra],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=dict(os.environ, FAKE_PIO_MODE="ok"))
    if not until(lambda: _up(port), 15):
        p.kill()
        raise SystemExit("simulator did not start")
    return p, port


def _up(port):
    try:
        return call(port, "GET", "/api/status")[0] == 200
    except OSError:
        return False


sim, port = start_sim()
try:
    st, status = call(port, "GET", "/api/status")
    check(status.get("flash") is True and status.get("sim") is True, "status says the Flash tab is available")
    st, page = call(port, "GET", "/flasher.html")
    m = page.split('const TOKEN="') if st == 200 else ["", ""]
    token = m[1].split('"')[0] if len(m) > 1 else ""
    check(st == 200 and len(token) >= 16 and "__BLIP_TOKEN__" not in page, "flasher.html is served with a per-run token")
    good = {"X-Blip-Token": token}
    st, home = call(port, "GET", "/")
    check(st == 200 and "BLIP <span>FLASHER" in home and 'id="flash" class="on"' in home, "the home page is the flasher, already active")
    check('const TOKEN="%s"' % token in home and "__BLIP_TOKEN__" not in home and "__FLASHER__" not in home and "__VERSION__" not in home,
          "the home page carries the same token and no placeholders")
    check('href="/sim"' in home, "the home page has a button to the simulator")
    st, simpage = call(port, "GET", "/sim")
    check(st == 200 and 'id="toFlash"' in simpage and 'id="flash"' not in simpage, "/sim is the simulator, with a way back")
    st, other = call(port, "GET", "/", host="evil.example")
    check(st == 200 and "FLASHER" not in other and "TOKEN" not in other, "a foreign Host gets the simulator, never the flasher or its token")
    body = {"board": "c3", "radar": "rd03d", "port": "auto", "monitor": False}

    check(call(port, "POST", "/api/flash/start", body)[0] == 403, "start without the token is refused")
    check(call(port, "POST", "/api/flash/start", body, {"X-Blip-Token": "wrong"})[0] == 403, "start with a wrong token is refused")
    check(call(port, "POST", "/api/flash/start", body, good, host="evil.example:%d" % port)[0] == 403, "start with a foreign Host is refused")
    check(call(port, "POST", "/api/flash/start", body, dict(good, Origin="http://evil.example"))[0] == 403, "start with a foreign Origin is refused")
    check(call(port, "GET", "/flasher.html", host="evil.example")[0] == 403, "the page itself is not served to a foreign Host")
    for bad, why in (({"board": "x", "radar": "rd03d"}, "unknown board"), ({"board": "c3", "radar": "x"}, "unknown radar"),
                     ({"board": "c3", "radar": "rd03d", "mode": "rm -rf"}, "unknown mode"),
                     ({"board": "c3", "radar": "rd03d", "port": "/etc/passwd"}, "a port that isn't a serial port"),
                     ({"board": "c3", "radar": "rd03d", "port": "auto; touch /tmp/pwned"}, "shell injection in port"),
                     ({"board": "c3", "radar": "rd03d", "port": 5}, "a non-string port")):
        check(call(port, "POST", "/api/flash/start", bad, good)[0] == 400, "start rejects " + why)
    check(not os.path.exists("/tmp/pwned"), "nothing was executed from the port field")

    st, info = call(port, "GET", "/api/flash/info")
    check(st == 200 and {b["id"] for b in info["boards"]} == {"c3", "s3"} and {r["id"] for r in info["radars"]} == {"rd03d", "ld2450", "bench"}, "info lists both boards, both radars and the bench test")
    check(isinstance(info["ports"], list) and info["pio"]["state"] == "ready" and info["esptool"]["state"] == "ready", "info lists ports and sees PlatformIO + esptool")
    check(info["prebuilt"] and len(info["prebuilt"]["images"]) == 6 and info["prebuilt"]["matches"] is True, "info shows the bundled firmware and that it matches the source")
    check(info["job"]["lines"] == [], "info carries no log lines")

    st, r = call(port, "POST", "/api/flash/start", body, good)
    check(st == 200 and r["env"] == "c3-supermini" and r["mode"] == "quick", "start with the token is accepted (Quick flash by default)")
    cur, snap = 0, {}
    t0 = time.time()
    while time.time() - t0 < 60:
        st, snap = call(port, "GET", "/api/flash/log?from=%d" % cur)
        cur = snap["next"]
        if snap["state"] not in ("running", "monitoring"):
            break
        time.sleep(0.1)
    check(snap["state"] == "done" and snap["flashed"], "full Quick flash over HTTP finishes flashed")
    st, r = call(port, "POST", "/api/flash/start", dict(body, mode="source"), good)
    check(st == 200 and r["mode"] == "source", "Build from source can be chosen")
    until(lambda: call(port, "GET", "/api/flash/log?from=0")[1]["state"] not in ("running", "monitoring"), 60, 0.2)
    snap2 = call(port, "GET", "/api/flash/log?from=0")[1]
    check(snap2["state"] == "done" and len(snap2["steps"]) == 5, "Build from source over HTTP finishes with five steps")
    # keep-alive: a refused POST with a body must not leave the body in the socket for the next request
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    data = json.dumps(body).encode()
    c.request("POST", "/api/flash/start", body=data, headers={"Content-Length": str(len(data))})
    r1 = c.getresponse(); r1.read()
    c.request("GET", "/api/status")
    r2 = c.getresponse(); r2body = r2.read()
    c.close()
    check(r1.status == 403 and r2.status == 200 and b'"app"' in r2body, "keep-alive: next request after a refused POST is answered normally")
    check(call(port, "GET", "/api/flash/log?from=0")[1]["lines"][0].startswith("▸ Flashing"), "the whole log can be fetched again after a page reload")
    check(call(port, "POST", "/api/flash/cancel", {}, good)[1] == {"ok": False}, "cancel with nothing running says so")
finally:
    sim.terminate()
    sim.wait(5)

sim2, port2 = start_sim("--no-flash")
try:
    check(call(port2, "GET", "/api/status")[1].get("flash") is False, "--no-flash: status says no Flash tab")
    st, home2 = call(port2, "GET", "/")
    check(st == 200 and "FLASHER" not in home2 and 'id="scope"' in home2, "--no-flash: / is the simulator")
    check(call(port2, "GET", "/api/flash/info")[0] == 404 and call(port2, "GET", "/flasher.html")[0] == 404, "--no-flash: endpoints are gone")
finally:
    sim2.terminate()
    sim2.wait(5)

print("\nRESULT:", "FAIL" if fails else "PASS", "(%d failures)" % fails)
sys.exit(1 if fails else 0)
