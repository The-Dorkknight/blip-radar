#!/usr/bin/env python3
"""Blip — checks tools/tracker_py.py (used by the simulator) matches firmware/include/tracker.h.

    python3 tests/test_tracker_py.py

Builds tests/tracker_replay.cpp with g++ (skips with a note if no compiler),
feeds both trackers the same 3 minutes of messy synthetic detections, and
compares the visible tracks frame by frame. The C++ uses 32-bit floats and
Python 64-bit, so positions may differ by a millimetre or two; ids and the
set of shown targets must match in at least 99% of frames.
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
import tracker_py  # noqa: E402


def scene():
    rnd = random.Random(42)
    frames = []
    for k in range(20 * 180):
        t = k * 0.05
        d = []
        x, y = 1500 * math.sin(0.25 * t), 3500 + 1200 * math.cos(0.25 * t)
        vr = (x * 375 * math.cos(0.25 * t) + y * -300 * math.sin(0.25 * t)) / math.hypot(x, y)
        if k % 97 >= 6:
            d.append((x + rnd.gauss(0, 120), y + rnd.gauss(0, 60), vr / 10))
            r = math.hypot(x, y)
            if rnd.random() > 0.3:
                d.append((x / r * (r + 1200) + rnd.gauss(0, 120), y / r * (r + 1200) + rnd.gauss(0, 60), vr / 10))   # reflection
        if rnd.random() > 0.85:
            d.append((rnd.uniform(-3000, 3000), rnd.uniform(1000, 7000), rnd.uniform(-50, 50)))                     # flicker
        d.append((-1500 + rnd.gauss(0, 100), 6000 + rnd.gauss(0, 100), rnd.uniform(-20, 20)))                         # fan
        rnd.shuffle(d)
        frames.append([(int(round(a)), int(round(b)), int(round(c))) for a, b, c in d[:3]])
    return frames


def main():
    gxx = shutil.which("g++")
    if not gxx:
        print("SKIP  no g++ found; cannot cross-check against the C++ tracker")
        print("\nRESULT: PASS (skipped)")
        return 0
    tmp = tempfile.mkdtemp()
    exe = os.path.join(tmp, "replay")
    subprocess.run([gxx, "-std=c++17", "-O2", "-I", os.path.join(ROOT, "firmware", "include"),
                    os.path.join(ROOT, "tests", "tracker_replay.cpp"), "-o", exe], check=True)
    frames = scene()
    inp = "\n".join(" ".join(f"{x} {y} {v}" for x, y, v in fr) for fr in frames) + "\n"
    fails = 0
    for flags in ([], ["strict"], ["noclutter"]):
        out = subprocess.run([exe] + flags, input=inp, capture_output=True, text=True, check=True).stdout.splitlines()
        T = tracker_py.Tracker()
        T.cfg.strict_ghost = "strict" in flags
        T.cfg.no_clutter = "noclutter" in flags
        same = worst = 0
        for fr, line in zip(frames, out):
            T.update(fr, 0.05)
            py = T.visible()
            nums = [int(v) for v in line.split()]
            cc = [(nums[i], nums[i + 1], nums[i + 2]) for i in range(0, len(nums), 3)]
            if [p[0] for p in py] == [c[0] for c in cc]:
                same += 1
                for p, c in zip(py, cc):
                    worst = max(worst, abs(p[1] - c[1]), abs(p[2] - c[2]))
        pct = 100.0 * same / len(frames)
        tag = "+".join(flags) or "default"
        ok = pct >= 99.0
        print(("PASS  " if ok else "FAIL  ") + f"[{tag}] same visible ids in {pct:.2f}% of {len(frames)} frames"); fails += not ok
        ok = worst <= 20
        print(("PASS  " if ok else "FAIL  ") + f"[{tag}] positions agree within {worst} mm where ids match"); fails += not ok
    print("\nRESULT:", "FAIL" if fails else "PASS", f"({fails} failures)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
