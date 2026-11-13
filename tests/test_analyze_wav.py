#!/usr/bin/env python3
"""tools/analyze_wav.py finds a 102.4 ms burst train, clipping, and a heartbeat in synthetic recordings."""
import io, math, os, random, struct, subprocess, sys, tempfile, wave
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
random.seed(5)
FS = 8000

def write(path, x):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS)
        w.writeframes(struct.pack("<%dh" % len(x), *[max(-32768, min(32767, int(v * 32767))) for v in x]))

def run(x):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.wav"); write(p, x)
        return subprocess.run([sys.executable, "-I", os.path.join(root, "tools", "analyze_wav.py"), p], capture_output=True, text=True, check=True).stdout

N = FS * 12
ok = True
def check(c, m):
    global ok
    print(("PASS  " if c else "FAIL  ") + m)
    ok &= bool(c)

# 1) quiet heart-ish low-frequency thumps at 72/min + 4 ms hiss bursts every 102.4 ms
x = [0.004 * random.gauss(0, 1) for _ in range(N)]
for k in range(int(12 / 0.8333)):
    i0 = int(k * 0.8333 * FS) + 800
    for j in range(700):
        if i0 + j < N: x[i0 + j] += 0.2 * math.exp(-j / 160) * math.sin(2 * math.pi * 50 * j / FS)
t = 0.05
while t < 11.9:
    i0 = int(t * FS)
    for j in range(32): x[i0 + j] += 0.25 * random.gauss(0, 1)
    t += 0.1024
out = run(x)
check("per second" in out and any(8.5 <= float(l.split("=")[1].split("per")[0]) <= 11 for l in out.splitlines() if "short bursts" in l), "burst rate near 9.8 per second reported")
check("102.4 ms beat" in out, "burst train identified as the Wi-Fi beacon interval")
check("heartbeat-like rhythm: 72" in out or "heartbeat-like rhythm: 7" in out, "heartbeat rhythm found near 72/min")

# 2) clean signal: no bursts blamed on the beacon, clipping flagged when square
y = [0.004 * random.gauss(0, 1) for _ in range(N)]
out = run(y)
check("102.4 ms beat" not in out, "noise only: no beacon claim")
z = [max(-1, min(1, 3.0 * math.sin(2 * math.pi * 40 * i / FS))) for i in range(N)]
out = run(z)
check("clipping" in out, "square-clipped signal flagged as clipping")
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
