#!/usr/bin/env python3
"""Blip — tests for the Python RD-03D parser and for the simulator's encoder.

Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.

    python3 tests/test_parser_py.py
"""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import rd03d_py as r  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        fails += 1


DOC = bytes.fromhex("AAFF0300 0E03 B186 1000 6801 0000000000000000 0000000000000000 55CC".replace(" ", ""))
TWO = bytes.fromhex("AAFF0300 0501 1982 0000 6801 E381 3388 2080 6801 0000000000000000 55CC".replace(" ", ""))

check(r.decode_signed(0x0E, 0x03) == -782, "x 0x030E -> -782")
check(r.decode_signed(0xB1, 0x86) == 1713, "y 0x86B1 -> 1713")
check(r.decode_signed(0x10, 0x00) == -16, "v 0x0010 -> -16")
fr = r.decode(DOC)
check(fr.count == 1 and fr.t[0].x_mm == -782 and fr.t[0].y_mm == 1713 and fr.t[0].v_cms == -16 and fr.t[0].res_mm == 360, "doc frame decodes")
fr = r.decode(TWO)
check(fr.count == 2 and fr.t[1].x_mm == 483 and fr.t[1].y_mm == 2099 and fr.t[1].v_cms == 32, "two-target frame decodes")

p = r.Parser()
stream = bytes([0x12, 0xAA, 0xAA, 0xFF, 0x03, 0x01]) + bytes.fromhex("FDFCFBFA0800800100000403 0201".replace(" ", "")) + DOC[:15] + DOC + TWO + DOC
got = [f for f in (p.feed(b) for b in stream) if f]
check(len(got) == 3 and got[-1].t[0].y_mm == 1713, "stream resync: 3 frames from junk+ACK+torn")

# round trip through the simulator's encoder
sys.path.insert(0, os.path.join(ROOT, "tools"))
import sim_radar as sim  # noqa: E402


class W:
    def __init__(self, x, y, v, on=True):
        self.x, self.y, self.v, self.on = x, y, v, on

    def radial_speed_cms(self):
        return self.v


sim.STATE["multi"] = True
sim.STATE["messy"] = False   # exact bytes: no simulated room noise
frame = sim.encode_frame([W(-782, 1713, -16), W(483, 2099, 32), W(0, 0, 0, on=False)])
check(frame[:12] == DOC[:12] and frame[12:20] == TWO[12:20] and frame[-2:] == r.TAIL, "simulator encoder reproduces the datasheet bytes")
d = r.decode(frame)
check(d.count == 2 and d.t[0].x_mm == -782 and d.t[1].v_cms == 32, "encoder -> decoder round trip")

print("\nRESULT:", "FAIL" if fails else "PASS", f"({fails} failures)")
sys.exit(1 if fails else 0)
