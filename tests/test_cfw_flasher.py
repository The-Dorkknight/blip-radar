#!/usr/bin/env python3
"""Blip — tests for the flasher's "LD2450 custom firmware" tab (tools/flasher.py, modes cfw-*).

    python3 tests/test_cfw_flasher.py

No radar, no internet: a fake copy of earlynerd/HLK-LD2450_FW is zipped up locally and
served as file://, its four tools are stand-ins that log their arguments, and the SHA-256
pins are pointed at the fake images. Checks: download + unpack + hash check, the exact
command each action runs, refusal of tampered images and of "../" paths in the zip,
and the HTTP rules (explicit port, typed BRICK for anything that writes).
"""
import hashlib
import io
import json
import os
import sys
import tempfile
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
IMG = "firmware/releases/usb-bins40-20261008/update-two-wire.ufw"
STOCK = "5o09fdkye1jo8.ufw"
LOG = os.path.join(TMP, "argv.log")
TOOL = ("import sys, os\nopen(%r, 'a').write(os.path.basename(sys.argv[0]) + ' ' + ' '.join(sys.argv[1:]) + '\\n')\n"
        "print('fake tool says hello')\nsys.exit(int(os.environ.get('FAKE_CFW_RC', '0')))\n" % LOG)


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)


files = {"HLK-LD2450_FW-fake/" + IMG: b"fake custom image", "HLK-LD2450_FW-fake/" + STOCK: b"fake stock image"}
for t in ("firmware/tools/stock_uart.py", "firmware/tools/uart_upload.py", "firmware/tools/restore_stock.py", "tools/live_radar.py"):
    files["HLK-LD2450_FW-fake/" + t] = TOOL
good_zip = os.path.join(TMP, "good.zip")
make_zip(good_zip, files)
os.environ.update({
    "BLIP_CFW_URL": "file://" + good_zip,
    "BLIP_CFW_DIR": os.path.join(TMP, "cache", "cfw"),
    "BLIP_CFW_PY": sys.executable,
    "BLIP_CFW_IMAGE_SHA": hashlib.sha256(b"fake custom image").hexdigest(),
    "BLIP_CFW_STOCK_SHA": hashlib.sha256(b"fake stock image").hexdigest(),
    "BLIP_PORTS": "/dev/ttyFAKE0",
})
sys.path.insert(0, os.path.join(ROOT, "tools"))
import flasher  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    print(("PASS  " if cond else "FAIL  ") + msg)
    fails += not cond


def run(mode, port="/dev/ttyFAKE0", rc=0):
    open(LOG, "w").close()
    os.environ["FAKE_CFW_RC"] = str(rc)
    flasher.JOB.start("c3", "ld2450", port, False, mode)
    t = time.time()
    while flasher.JOB.state in ("running", "monitoring") and time.time() - t < 30:
        time.sleep(0.02)
    return flasher.JOB.snapshot(0), open(LOG).read().splitlines()


print("-- actions")
s, a = run("cfw-probe")
check(s["state"] == "done" and not s["flashed"], "probe: finishes, nothing counted as written")
check(os.path.exists(os.path.join(os.environ["BLIP_CFW_DIR"], IMG)), "probe: project downloaded and unpacked (top folder stripped)")
check(len(a) == 1 and a[0].startswith("stock_uart.py --port /dev/ttyFAKE0 --baud 256000 --log "), "probe runs stock_uart.py --port .. --baud 256000 --log ..")
check(any("match their pinned SHA-256" in x for x in s["lines"]), "probe: both images hash-checked first")
s, a = run("cfw-install")
check(s["state"] == "done" and s["flashed"], "install: finishes, counted as a write")
check(len(a) == 1 and a[0].startswith("uart_upload.py ") and IMG in a[0] and "--entry stock-b2" in a[0]
      and "--initial-baud 256000 --baud 256000" in a[0] and "--port /dev/ttyFAKE0" in a[0], "install: uart_upload.py <image> --entry stock-b2 at 256000")
s, a = run("cfw-update")
check(len(a) == 1 and "--entry custom" in a[0], "update: uses --entry custom")
s, a = run("cfw-restore")
check(s["state"] == "done" and len(a) == 1 and a[0] == "restore_stock.py --port /dev/ttyFAKE0", "restore: restore_stock.py --port ..")
s, a = run("cfw-viewer", port="")
check(s["state"] == "done" and len(a) == 1 and a[0] == "live_radar.py --connect", "viewer: live_radar.py --connect")
s, a = run("cfw-install", rc=3)
check(s["state"] == "error" and not s["flashed"] and s["steps"][2]["status"] == "error", "a failing upload ends in error, not 'written'")

print("-- refusals")
img = os.path.join(os.environ["BLIP_CFW_DIR"], IMG)
with open(img, "ab") as f:
    f.write(b"tampered")
s, a = run("cfw-install")
check(s["state"] == "error" and not a and any("doesn't match its pinned SHA-256" in x for x in s["lines"]), "a tampered image is refused before any tool runs")
import shutil  # noqa: E402
shutil.rmtree(os.environ["BLIP_CFW_DIR"])
bad = os.path.join(TMP, "bad.zip")
make_zip(bad, dict(files, **{"HLK-LD2450_FW-fake/../../evil.txt": b"x"}))
flasher.CFW_URL = "file://" + bad
s, a = run("cfw-probe")
check(s["state"] == "error" and not a and not os.path.exists(os.path.join(TMP, "cache", "evil.txt"))
      and not os.path.exists(os.path.join(TMP, "evil.txt")), "a zip with ../ paths is refused, nothing written outside")
flasher.CFW_URL = "file://" + good_zip

print("-- HTTP rules")


class H:
    def __init__(self, body):
        raw = json.dumps(body).encode()
        self.command = "POST"
        self.client_address = ("127.0.0.1", 5555)
        self.headers = {"Host": "127.0.0.1:8080", "X-Blip-Token": flasher.TOKEN, "Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.close_connection = False
        self.reply = None

    def _send(self, code, ctype, body):
        self.reply = (code, json.loads(body))


def post(body):
    h = H(body)
    flasher.handle(h, "/api/flash/start", "")
    t = time.time()
    while flasher.JOB.state in ("running", "monitoring") and time.time() - t < 30:
        time.sleep(0.02)
    return h.reply


r = post({"mode": "cfw-install", "port": "auto", "confirm": "BRICK"})
check(r[0] == 400 and "never guess" in r[1]["error"], "auto-detect port refused for the radar tools")
r = post({"mode": "cfw-install", "port": "/dev/ttyFAKE0"})
check(r[0] == 400 and "BRICK" in r[1]["error"], "install without the typed BRICK is refused")
r = post({"mode": "cfw-restore", "port": "/dev/ttyFAKE0", "confirm": "brick?"})
check(r[0] == 400, "restore with the wrong word is refused")
r = post({"mode": "cfw-probe", "port": "/dev/ttyFAKE0"})
check(r[0] == 200, "probe needs no confirmation (writes nothing)")
r = post({"mode": "cfw-install", "port": "/dev/ttyFAKE0", "confirm": "BRICK"})
check(r[0] == 200, "install with port + BRICK is accepted")
r = post({"mode": "cfw-nonsense", "port": "/dev/ttyFAKE0"})
check(r[0] == 400, "unknown cfw mode refused")

print("\nRESULT:", "FAIL" if fails else "PASS", f"({fails} failures)")
sys.exit(1 if fails else 0)
