"""Blip — Python copy of firmware/include/gate.h (minimum range, edge limit, handheld mode).

Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.

Used by tools/sim_radar.py. Keep it line-for-line with gate.h; tests/test_gate_py.py
replays the same frames through both and compares.
"""
import math

KEEP, NEAR, EDGE, SCENERY, STUCK = 0, 1, 2, 3, 4
WHY_NAMES = {NEAR: "near", EDGE: "edge", SCENERY: "scenery", STUCK: "stuck"}
FROZEN_SLOTS = 6


class Cfg:
    def __init__(self):
        self.min_mm = 100
        self.max_deg = 65
        self.handheld = False
        self.stuck_s = 0
        self.walk_min = 300.0
        self.tol_mms = 250.0
        self.tol_frac = 0.25
        self.min_cos = 0.3
        self.hold_s = 1.5


class Gate:
    def __init__(self):
        self.cfg = Cfg()
        self.reset()

    def reset(self):
        self.ego_ = 0.0
        self.ego_age = 99.0
        self.why = [KEEP, KEEP, KEEP]
        self.fz = [[False, 0, 0, 0.0, 0.0] for _ in range(FROZEN_SLOTS)]

    def ego_valid(self):
        return self.ego_age <= self.cfg.hold_s and abs(self.ego_) >= self.cfg.walk_min

    def ego(self):
        return self.ego_ if self.ego_valid() else 0.0

    def _age_frozen(self, slots, dt):
        # fixed slots [used, x, y, t, gone], in the same order as Gate::fz_ in gate.h
        for z in self.fz:
            if z[0]:
                z[4] += dt
                if z[4] > 1.0:
                    z[0] = False
        for d in slots:
            if d is None:
                continue
            x, y = int(d[0]), int(d[1])
            hit = next((z for z in self.fz if z[0] and z[1] == x and z[2] == y), None)
            if hit:
                hit[3] += dt
                hit[4] = 0.0
                continue
            slot = next((z for z in self.fz if not z[0]), None)
            if slot is None:
                slot = self.fz[0]
                for z in self.fz:
                    if z[3] < slot[3] or (z[3] == slot[3] and z[4] > slot[4]):
                        slot = z
            slot[:] = [True, x, y, 0.0, 0.0]

    def _frozen_for(self, x, y):
        for z in self.fz:
            if z[0] and z[1] == int(x) and z[2] == int(y):
                return z[3]
        return 0.0

    def apply(self, dets, dt):
        """dets: list of (x_mm, y_mm, v_cms), up to 3 slots (None = empty slot allowed).
        Returns (kept, dropped) where dropped is [(x, y, why_name)]."""
        c = self.cfg
        if dt <= 0 or dt > 0.5:
            dt = 0.05
        slots = list(dets[:3]) + [None] * (3 - len(dets[:3]))
        self.why = [KEEP, KEEP, KEEP]
        cs = [0.0] * 3
        ap = [0.0] * 3
        if c.stuck_s:
            self._age_frozen(slots, dt)
        for i, d in enumerate(slots):
            if d is None:
                continue
            x, y, v = d
            r = math.sqrt(x * x + y * y)
            a = abs(math.atan2(x, y)) * 57.29578
            if r < c.min_mm:
                self.why[i] = NEAR
                continue
            if a > c.max_deg:
                self.why[i] = EDGE
                continue
            if c.stuck_s and self._frozen_for(x, y) > c.stuck_s:
                self.why[i] = STUCK
                continue
            cs[i] = y / r if r > 1 else 0.0
            ap[i] = -v * 10.0
        if c.handheld:
            g = [ap[i] / cs[i] for i in range(3)
                 if slots[i] is not None and self.why[i] == KEEP and cs[i] >= c.min_cos]
            self.ego_age += dt
            est, agree = 0.0, 0
            for ga in g:
                close = [gb for gb in g if abs(gb - ga) <= c.tol_mms + c.tol_frac * abs(ga)]
                if len(close) > agree:
                    agree = len(close)
                    est = sum(close) / len(close)
            if agree >= 2 and abs(est) >= c.walk_min:
                self.ego_ = est if self.ego_age > c.hold_s else self.ego_ + 0.5 * (est - self.ego_)
                self.ego_age = 0.0
            if self.ego_valid():
                for i in range(3):
                    if slots[i] is None or self.why[i] != KEEP or cs[i] < c.min_cos:
                        continue
                    expect = self.ego_ * cs[i]
                    if abs(ap[i] - expect) <= c.tol_mms + c.tol_frac * abs(expect):
                        self.why[i] = SCENERY
        kept, dropped = [], []
        for i, d in enumerate(slots):
            if d is None:
                continue
            if self.why[i] == KEEP:
                kept.append(d)
            else:
                dropped.append((d[0], d[1], WHY_NAMES[self.why[i]]))
        return kept, dropped
