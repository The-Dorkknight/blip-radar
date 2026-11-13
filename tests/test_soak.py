#!/usr/bin/env python3
"""tests/test_soak.py — tools/soak_test.py against the simulator, no board needed.

Checks that the harness (a) sees a healthy stream as OK (about 31 audio packets/s, none lost),
(b) sees a pretend watchdog reset as a CRASH, reads the boot counter and the node log back,
and (c) points at the Lab switch that makes the crash go away, and (d) restores the node's
defaults at the end. Run:  python3 tests/test_soak.py
"""
import os, subprocess, sys, time, socket, json, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0
def check(c, msg):
    global fails
    print(("PASS  " if c else "FAIL  ") + msg)
    if not c: fails += 1

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

port = free_port()
sim = subprocess.Popen([sys.executable, "-I", os.path.join(ROOT, "tools", "sim_radar.py"), "--no-browser", "--no-flash", "--port", str(port)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT)
try:
    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/api/status" % port, timeout=1).read(); break
        except Exception:
            time.sleep(0.2)
    soak = os.path.join(ROOT, "tools", "soak_test.py")
    out1 = os.path.join(ROOT, "tests", "_soak1.md"); out2 = os.path.join(ROOT, "tests", "_soak2.md")

    # (a) healthy node
    p = subprocess.run([sys.executable, "-I", soak, "--host", "127.0.0.1", "--port", str(port), "--plan", "selftest", "--secs", "5", "--out", out1],
                       capture_output=True, text=True, timeout=120)
    rep = open(out1).read()
    check(p.returncode == 0, "healthy simulator: every trial OK (exit code 0)")
    row = [l for l in rep.splitlines() if l.startswith("| baseline")][0].split("|")
    pps = float(row[4]); lost = int(row[5])
    check(28.0 <= pps <= 34.0, "audio arrives at ~31.25 packets/s (got %.1f)" % pps)
    check(lost == 0, "no audio packets lost on a loopback link (lost %d)" % lost)
    row2 = [l for l in rep.splitlines() if l.startswith("| send=1")][0].split("|")
    check(float(row2[4]) == 0.0 and "OK" in row2[2], "send=1 trial: node stays up and (as asked) sends no audio")

    # (b)+(c) pretend crash: the baseline resets, the send=1 variant does not
    p = subprocess.run([sys.executable, "-I", soak, "--host", "127.0.0.1", "--port", str(port), "--plan", "selftest", "--secs", "8",
                        "--sim-crash-in", "3", "--wait-back", "30", "--out", out2], capture_output=True, text=True, timeout=180)
    rep = open(out2).read()
    check(p.returncode == 1, "a crashing baseline gives exit code 1")
    brow = [l for l in rep.splitlines() if l.startswith("| baseline")][0]
    check("CRASH" in brow and "boot #" in brow, "baseline is reported as CRASH with the boot number")
    check("crash (task watchdog)" in brow, "the node's own reset reason is carried into the report")
    check("Node log after `baseline`" in rep, "the node log is fetched after the crash")
    check("`send=1`" in rep.split("## Reading it")[1], "the report names send=1 as the variant that survived")

    # (d) defaults restored
    st = json.load(urllib.request.urlopen("http://127.0.0.1:%d/api/status" % port, timeout=3))
    check(all(st["lab"][k] == v for k, v in {"pace": 0, "dsp": 0, "send": 0, "text": 0, "src": 0, "prio": 5, "quiet": 0, "skip": 0}.items()),
          "the node is left on its shipped defaults")
finally:
    sim.terminate()
    try: sim.wait(5)
    except Exception: sim.kill()
    for f in ("_soak1.md", "_soak2.md"):
        try: os.remove(os.path.join(ROOT, "tests", f))
        except OSError: pass

print("\nRESULT: %s (%d failures)" % ("PASS" if fails == 0 else "FAIL", fails))
sys.exit(1 if fails else 0)
