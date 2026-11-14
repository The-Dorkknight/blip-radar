#!/usr/bin/env python3
"""Blip — Python port of firmware/include/tracker.h (the experimental "Smart" filter).

Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.

Used by tools/sim_radar.py so the simulator shows exactly what the firmware
would. Keep it line-for-line with the C++; tests/test_tracker_py.py replays
the same detections through both and checks they agree.
"""
import math

MAX_TRACKS = 6
RHIST = 60
GRID = 16
CELL_MM = 500.0
TENTATIVE, CONFIRMED, GHOST, CLUTTER = 0, 1, 2, 3
STATE_NAMES = {TENTATIVE: "tentative", CONFIRMED: "ok", GHOST: "ghost", CLUTTER: "clutter"}


class Cfg:
    min_range, max_range, max_angle_deg = 100.0, 8000.0, 65.0
    gate_mm, vmax_mms = 700.0, 3500.0
    alpha, beta = 0.5, 0.15
    confirm_hits = 3
    coast_s = 1.0
    clutter_s, clutter_radius = 30.0, 400.0
    ghost_bearing_deg, ghost_behind_mm, ghost_s = 10.0, 500.0, 1.0
    strict_ghost = False
    ghost_corr = 0.9
    no_clutter = False


class Track:
    __slots__ = ("used", "id", "st", "x", "y", "vx", "vy", "vdop", "vdopf", "hist", "unseen",
                 "ax", "ay", "still", "sx", "sy", "ghost_t", "suspect", "age", "ghost_of", "rh", "ri", "rn")

    def __init__(self):
        self.used = False
        self.id = 0
        self.st = TENTATIVE
        self.x = self.y = self.vx = self.vy = 0.0
        self.vdop = self.vdopf = 0.0
        self.hist = 0
        self.unseen = 0.0
        self.ax = self.ay = self.still = 0.0
        self.sx = self.sy = 0.0
        self.ghost_t = 0.0
        self.suspect = False
        self.age = 0.0
        self.ghost_of = 0
        self.rh = [0.0] * RHIST
        self.ri = 0
        self.rn = 0

    def push_range(self):
        self.rh[self.ri] = self.range()
        self.ri = (self.ri + 1) % RHIST
        if self.rn < RHIST:
            self.rn += 1

    def r_ago(self, k):
        return self.rh[(self.ri + 2 * RHIST - 1 - k) % RHIST]

    def range(self):
        return math.sqrt(self.x * self.x + self.y * self.y)

    def bearing_deg(self):
        return math.atan2(self.x, self.y) * 57.29578


def range_corr(a, b):
    """Same as Tracker::rangeCorr in tracker.h."""
    m = min(a.rn, b.rn)
    if m < RHIST:
        return 0.0
    sa = sb = saa = sbb = sab = 0.0
    lo, hi = 1e9, -1e9
    for k in range(m):
        ra, rb = a.r_ago(k), b.r_ago(k)
        lo = min(lo, ra); hi = max(hi, ra)
        sa += ra; sb += rb; saa += ra * ra; sbb += rb * rb; sab += ra * rb
    if hi - lo < 400:
        return 0.0
    va = saa - sa * sa / m
    vb = sbb - sb * sb / m
    cab = sab - sa * sb / m
    if va <= 1e-3 or vb <= 1e-3:
        return 0.0
    slope = cab / va
    if slope < 0.6 or slope > 1.4:
        return 0.0
    return cab / math.sqrt(va * vb)


def _popcount5(h):
    return sum((h >> i) & 1 for i in range(5))


class Tracker:
    def __init__(self):
        self.cfg = Cfg()
        self.reset()
        self.forget_clutter()

    def reset(self):
        self.tr = [Track() for _ in range(MAX_TRACKS)]
        self.next_id = 1
        self.decay_t = 0.0

    def forget_clutter(self):
        self.clutter = [[0] * GRID for _ in range(GRID)]

    @staticmethod
    def _cell(x, y):
        ix = int((x + GRID * CELL_MM / 2) / CELL_MM)
        iy = int(y / CELL_MM)
        return max(0, min(GRID - 1, ix)), max(0, min(GRID - 1, iy))

    def _mark(self, x, y):
        ix, iy = self._cell(x, y)
        for j in range(iy - 1, iy + 2):
            for i in range(ix - 1, ix + 2):
                if 0 <= i < GRID and 0 <= j < GRID:
                    self.clutter[j][i] = 255

    def cell_score(self, x, y):
        ix, iy = self._cell(x, y)
        return self.clutter[iy][ix]

    def _gate(self, t, dt):
        return self.cfg.gate_mm + self.cfg.vmax_mms * (dt + t.unseen)

    def update(self, dets, dt):
        """dets: list of (x_mm, y_mm, v_cms) as the RD-03D reports them (up to 3)."""
        c = self.cfg
        if dt <= 0 or dt > 0.5:
            dt = 0.05
        dx, dy, dv = [], [], []
        for (x, y, v) in dets[:3]:
            r = math.sqrt(x * x + y * y)
            a = abs(math.atan2(x, y) * 57.29578)
            if r < c.min_range or r > c.max_range or a > c.max_angle_deg or y <= 0:
                continue
            dx.append(float(x)); dy.append(float(y)); dv.append(v * 10.0)
        n = len(dx)
        for t in self.tr:
            if t.used:
                t.x += t.vx * dt; t.y += t.vy * dt
                t.hist = (t.hist << 1) & 0xFF
                t.unseen += dt; t.age += dt

        # associate (same depth-first search and costs as the C++)
        self._best_cost = 1e30
        self._best = [-1] * n
        cur = [-1] * n

        def search(k, cost, used):
            if cost >= self._best_cost:
                return
            if k >= n:
                self._best_cost = cost
                self._best = cur[:]
                return
            for j, t in enumerate(self.tr):
                if not t.used or (used >> j) & 1:
                    continue
                d = math.sqrt((dx[k] - t.x) ** 2 + (dy[k] - t.y) ** 2)
                g = self._gate(t, dt)
                if d > g:
                    continue
                cc = d / g + (0.15 if t.st == TENTATIVE else 0.0)
                cur[k] = j
                search(k + 1, cost + cc, used | (1 << j))
            cur[k] = -1
            search(k + 1, cost + 1.2, used)

        search(0, 0.0, 0)

        for k in range(n):
            j = self._best[k]
            if j >= 0:
                t = self.tr[j]
                rx, ry = dx[k] - t.x, dy[k] - t.y
                t.x += c.alpha * rx; t.y += c.alpha * ry
                t.vx += c.beta * rx / dt; t.vy += c.beta * ry / dt
                sp = math.sqrt(t.vx * t.vx + t.vy * t.vy)
                if sp > c.vmax_mms:
                    t.vx *= c.vmax_mms / sp; t.vy *= c.vmax_mms / sp
                t.vdop = dv[k]; t.vdopf += 0.15 * (dv[k] - t.vdopf)
                t.hist |= 1; t.unseen = 0.0
            else:
                s = next((i for i, t in enumerate(self.tr) if not t.used), -1)
                if s < 0:
                    continue
                t = Track()
                t.used = True; t.id = self.next_id
                self.next_id = (self.next_id + 1) & 0xFFFF or 1
                t.x = t.ax = t.sx = dx[k]; t.y = t.ay = t.sy = dy[k]
                t.vdop = t.vdopf = dv[k]; t.hist = 1
                self.tr[s] = t

        for t in self.tr:
            if t.used:
                t.push_range()

        # ghosts
        for b in self.tr:
            if not b.used or b.st == CLUTTER:
                continue
            cond = sus = False
            of = 0
            for a in self.tr:
                if a is b or not a.used or a.st != CONFIRMED:
                    continue
                va, vb = a.vdopf, b.vdopf
                if abs(va) < 100:
                    continue
                behind = b.range() - a.range() > c.ghost_behind_mm
                same = abs(b.bearing_deg() - a.bearing_deg()) < c.ghost_bearing_deg
                if behind and same:
                    sus = True
                    if abs(vb - va) < max(150.0, 0.3 * abs(va)):
                        cond = True; of = a.id
                        break
                if c.strict_ghost and behind and abs(vb - va) < max(200.0, 0.4 * abs(va)) and range_corr(a, b) > c.ghost_corr:
                    cond = True; of = a.id
                    break
            b.suspect = sus
            b.ghost_t += dt if cond else -dt
            b.ghost_t = max(0.0, min(3.0, b.ghost_t))
            if b.st in (CONFIRMED, TENTATIVE) and b.ghost_t >= c.ghost_s:
                b.st = GHOST; b.ghost_of = of
            elif b.st == GHOST and b.ghost_t <= 0:
                b.st = CONFIRMED

        # confirm, coast, drop, clutter
        for t in self.tr:
            if not t.used:
                continue
            hits = _popcount5(t.hist)
            if t.st == TENTATIVE:
                clutter_cell = not c.no_clutter and self.cell_score(t.x, t.y) > 128
                wait = t.suspect and t.age < c.ghost_s + 0.5
                if hits >= c.confirm_hits and not wait:
                    t.st = CLUTTER if clutter_cell else CONFIRMED
                    if clutter_cell:
                        self._mark(t.x, t.y)
                elif t.unseen > 0.2 and hits < 2:
                    t.used = False
                    continue
            if t.unseen > c.coast_s:
                t.used = False
                continue
            if t.unseen > 0:
                t.vx *= 0.9; t.vy *= 0.9
            if t.unseen == 0:
                t.sx += 0.05 * (t.x - t.sx); t.sy += 0.05 * (t.y - t.sy)
            ddx, ddy = t.sx - t.ax, t.sy - t.ay
            lim = 2 * c.clutter_radius if t.st == CLUTTER else c.clutter_radius
            if ddx * ddx + ddy * ddy > lim * lim:
                t.ax, t.ay, t.still = t.sx, t.sy, 0.0
                if t.st == CLUTTER:
                    t.st = CONFIRMED
            elif t.unseen < 0.5 and not c.no_clutter:
                t.still += dt
                need = 3.0 if self.cell_score(t.sx, t.sy) > 128 else c.clutter_s
                if t.still > need and t.st in (CONFIRMED, TENTATIVE):
                    t.st = CLUTTER
                    self._mark(t.ax, t.ay)

        self.decay_t += dt
        if self.decay_t >= 2.0:
            self.decay_t = 0.0
            for row in self.clutter:
                for i, v in enumerate(row):
                    if v:
                        row[i] = v - 1

    def visible(self):
        """[(id, x, y, v_cms)] of confirmed tracks, nearest first, at most 3."""
        ts = sorted((t for t in self.tr if t.used and t.st == CONFIRMED), key=lambda t: t.range())
        return [(t.id, int(round(t.x)), int(round(t.y)), int(round(t.vdop / 10.0))) for t in ts[:3]]

    def hidden(self):
        """Tracks the filter is hiding, for the phone's "show filtered" overlay."""
        return [(t.id, int(round(t.x)), int(round(t.y)), STATE_NAMES[t.st]) for t in self.tr
                if t.used and t.st in (GHOST, CLUTTER)]
