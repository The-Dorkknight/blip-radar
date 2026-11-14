// Blip — pre-filter ("gate") applied to every radar frame, Raw or Smart.
// Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
// Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
//
// Three optional checks, each a setting on the phone (all added 2026-11-13 after
// the first street test, see docs/RADAR_TRACKING_NOTES.md):
//
//   1. minimum range   drop anything closer than N mm (the module's own blind zone
//                      is about 0.5 m; a contact at 0.2-0.3 m is usually the person
//                      holding it, or wires near the antennas)
//   2. edge limit      drop detections beyond ±N° of straight ahead (edge-of-view
//                      detections are more often multi-bounce reflections)
//   3. handheld mode   for a radar that is being carried. Walking forward at v,
//                      a fixed object at bearing θ closes at about v·cos θ. When at
//                      least two contacts agree on one walking speed, that speed is
//                      taken as ours, held for 1.5 s, and every contact that fits it
//                      is scenery (lamp posts, parked cars) and dropped. A real mover
//                      does not fit. Untested on hardware: it trusts the module's
//                      speed field.
//   4. frozen targets  drop a detection the module keeps reporting at exactly the same
//                      x and y (to the mm) for longer than N s. The LD2450 sometimes
//                      fixates on a phantom (fan, glass, a reflection) at byte-identical
//                      coordinates; a real person always wobbles by a few mm. It comes
//                      back the moment its coordinates change. Added 2026-11-14.
//
// Plain C++ (no Arduino) so tests/test_gate.cpp runs it natively; tools/gate_py.py
// is the simulator's line-by-line Python copy (tests/test_gate_py.py checks they agree).
#pragma once
#include <math.h>
#include <string.h>
#include "rd03d.h"

namespace blip_gate {

enum Why : uint8_t { KEEP = 0, NEAR = 1, EDGE = 2, SCENERY = 3, STUCK = 4 };
static const int FROZEN_SLOTS = 6;

struct Cfg {
  uint16_t minMm = 100;        // 100 = the old behaviour (Smart filter's own limit)
  uint8_t maxDeg = 65;         // 65 = the old behaviour
  bool handheld = false;
  uint8_t stuckS = 0;          // drop a target frozen at identical x,y for this many seconds (0 = off)
  // handheld tuning
  float walkMin = 300;         // below this |speed| (mm/s) we are "standing still": no scenery test
  float tolMms = 250;          // a contact fits our walking speed within this...
  float tolFrac = 0.25f;       // ...plus this fraction of the expected closing speed
  float minCos = 0.3f;         // contacts more than ~72° off-axis say little about our speed
  float holdS = 1.5f;          // keep the last walking-speed estimate this long
};

class Gate {
 public:
  Cfg cfg;

  void reset() { ego_ = 0; egoAge_ = 99; memset(why_, 0, sizeof why_); memset(fz_, 0, sizeof fz_); }
  Gate() { reset(); }

  // Our own walking speed (mm/s, + = moving forward), or 0 when unknown / standing still.
  float ego() const { return egoValid() ? ego_ : 0; }
  bool egoValid() const { return egoAge_ <= cfg.holdS && fabsf(ego_) >= cfg.walkMin; }
  // Why slot i was dropped in the last frame (KEEP if it wasn't).
  Why why(int i) const { return (Why)why_[i]; }

  // Remove failing targets from f in place. Returns how many were dropped.
  int apply(rd03d::Frame& f, float dt) {
    if (dt <= 0 || dt > 0.5f) dt = 0.05f;
    memset(why_, 0, sizeof why_);
    float cs[rd03d::MAX_TARGETS], ap[rd03d::MAX_TARGETS];   // cos(bearing), closing speed mm/s (+ = approaching)
    if (cfg.stuckS) ageFrozen(f, dt);
    for (int i = 0; i < rd03d::MAX_TARGETS; i++) {
      rd03d::Target& t = f.t[i];
      cs[i] = 0; ap[i] = 0;
      if (!t.present) continue;
      float r = sqrtf((float)t.x_mm * t.x_mm + (float)t.y_mm * t.y_mm);
      float a = fabsf(atan2f((float)t.x_mm, (float)t.y_mm)) * 57.29578f;
      if (r < cfg.minMm) { why_[i] = NEAR; continue; }
      if (a > cfg.maxDeg) { why_[i] = EDGE; continue; }
      if (cfg.stuckS && frozenFor(t.x_mm, t.y_mm) > cfg.stuckS) { why_[i] = STUCK; continue; }
      cs[i] = r > 1 ? (float)t.y_mm / r : 0;
      ap[i] = -t.v_cms * 10.0f;                              // module: + = moving away
    }
    if (cfg.handheld) {
      // each usable contact's guess at our walking speed, if it were a fixed object
      float g[rd03d::MAX_TARGETS]; int n = 0;
      for (int i = 0; i < rd03d::MAX_TARGETS; i++)
        if (f.t[i].present && why_[i] == KEEP && cs[i] >= cfg.minCos) g[n++] = ap[i] / cs[i];
      egoAge_ += dt;
      float est = 0; int agree = 0;
      for (int a = 0; a < n; a++) {                          // the guess most others agree with
        int c = 0; float s = 0;
        for (int b = 0; b < n; b++)
          if (fabsf(g[b] - g[a]) <= cfg.tolMms + cfg.tolFrac * fabsf(g[a])) { c++; s += g[b]; }
        if (c > agree) { agree = c; est = s / c; }
      }
      if (agree >= 2 && fabsf(est) >= cfg.walkMin) {
        ego_ = egoAge_ > cfg.holdS ? est : ego_ + 0.5f * (est - ego_);
        egoAge_ = 0;
      }
      if (egoValid()) {
        for (int i = 0; i < rd03d::MAX_TARGETS; i++) {
          if (!f.t[i].present || why_[i] != KEEP || cs[i] < cfg.minCos) continue;
          float expect = ego_ * cs[i];
          if (fabsf(ap[i] - expect) <= cfg.tolMms + cfg.tolFrac * fabsf(expect)) why_[i] = SCENERY;
        }
      }
    }
    int dropped = 0;
    for (int i = 0; i < rd03d::MAX_TARGETS; i++)
      if (f.t[i].present && why_[i] != KEEP) { f.t[i].present = false; dropped++; if (f.count) f.count--; }
    return dropped;
  }

 private:
  float ego_ = 0, egoAge_ = 99;
  uint8_t why_[rd03d::MAX_TARGETS];
  // positions reported with identical coordinates, and for how long
  struct Frozen { bool used; int16_t x, y; float t, gone; };
  Frozen fz_[FROZEN_SLOTS];

  void ageFrozen(const rd03d::Frame& f, float dt) {
    for (auto& z : fz_) if (z.used) { z.gone += dt; if (z.gone > 1.0f) z.used = false; }
    for (int i = 0; i < rd03d::MAX_TARGETS; i++) {
      const rd03d::Target& t = f.t[i];
      if (!t.present) continue;
      Frozen* hit = nullptr;
      for (auto& z : fz_) if (z.used && z.x == t.x_mm && z.y == t.y_mm) { hit = &z; break; }
      if (hit) { hit->t += dt; hit->gone = 0; continue; }
      // a free slot, else the entry frozen the shortest time (moving targets never build up time,
      // so a phantom that misses a frame or two is not pushed out by them)
      Frozen* slot = nullptr;
      for (auto& z : fz_) if (!z.used) { slot = &z; break; }
      if (!slot) { slot = &fz_[0]; for (auto& z : fz_) if (z.t < slot->t || (z.t == slot->t && z.gone > slot->gone)) slot = &z; }
      *slot = {true, t.x_mm, t.y_mm, 0, 0};
    }
  }
  float frozenFor(int16_t x, int16_t y) const {
    for (const auto& z : fz_) if (z.used && z.x == x && z.y == y) return z.t;
    return 0;
  }
};

}  // namespace blip_gate
