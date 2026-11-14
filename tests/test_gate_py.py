#!/usr/bin/env python3
"""Blip — checks tools/gate_py.py (used by the simulator) matches firmware/include/gate.h.

    python3 tests/test_gate_py.py

Builds tests/gate_replay.cpp with g++ (skips with a note if there is no compiler), feeds
both the same synthetic street scene (walking, standing, lamp posts, a pedestrian, close
clutter, edge contacts) under three settings, and compares the per-slot decisions.
C++ uses 32-bit floats, Python 64-bit, so a borderline case may differ now and then;
at least 99% of frames must agree exactly.
"""
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import gate_py  # noqa: E402


def scene():
    rnd = random.Random(7)
    frames = []
    for k in range(20 * 120):
        t = k * 0.05
        walk = 1300 if (k // 400) % 2 == 0 else 0           # walk 20 s, stand 20 s, ...
        d = []
        for i in range(2):
            b = math.radians(rnd.choice([-50, -20, 5, 30, 70]))
            r = rnd.uniform(800, 7000)
            d.append((r * math.sin(b), r * math.cos(b), -(walk * math.cos(b) + rnd.gauss(0, 80)) / 10))
        if rnd.random() < 0.5:
            d.append((rnd.gauss(0, 30), 250 + rnd.gauss(0, 30), rnd.uniform(-5, 5)))       # the carrier's hand
        else:
            pr = 6000 - (t * 2000) % 5000
            d.append((300, pr, -(walk + 900) / 10))                                        # a pedestrian
        if (k // 300) % 2 == 0:
            d.append((-900, 3100, 0))                                                      # a frozen phantom, on and off
        rnd.shuffle(d)
        frames.append([(int(round(x)), int(round(y)), int(round(v))) for x, y, v in d[:3]])
    return frames


def main():
    gxx = shutil.which("g++")
    if not gxx:
        print("SKIP  no g++ found; cannot cross-check against the C++ gate")
        print("\nRESULT: PASS (skipped)")
        return 0
    tmp = tempfile.mkdtemp()
    exe = os.path.join(tmp, "gate_replay")
    subprocess.run([gxx, "-std=c++17", "-O2", "-I", os.path.join(ROOT, "firmware", "include"),
                    os.path.join(ROOT, "tests", "gate_replay.cpp"), "-o", exe], check=True)
    frames = scene()
    inp = "\n".join(" ".join(f"{x} {y} {v}" for x, y, v in fr) for fr in frames) + "\n"
    fails = 0
    for (mn, deg, hand, stuck) in [(100, 65, 0, 0), (500, 45, 0, 0), (500, 65, 1, 0), (100, 65, 0, 5), (500, 65, 1, 10)]:
        out = subprocess.run([exe, str(mn), str(deg), str(hand), str(stuck)], input=inp, capture_output=True, text=True, check=True).stdout.splitlines()
        G = gate_py.Gate()
        G.cfg.min_mm, G.cfg.max_deg, G.cfg.handheld, G.cfg.stuck_s = mn, deg, bool(hand), stuck
        same = drops = 0
        for fr, line in zip(frames, out):
            G.apply(fr, 0.05)
            c = [int(v) for v in line.split()[:3]]
            same += G.why == c
            drops += sum(1 for w in c if w)
        pct = 100.0 * same / len(frames)
        ok = pct >= 99.0 and drops > 0
        print(("PASS  " if ok else "FAIL  ") + f"min {mn} mm, edge {deg}°, handheld {hand}, stuck {stuck} s: same decisions in {pct:.2f}% of {len(frames)} frames ({drops} drops in C++)")
        fails += not ok
    print("\nRESULT:", "FAIL" if fails else "PASS", f"({fails} failures)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
