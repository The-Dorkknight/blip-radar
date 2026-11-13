// Blip — "Smart" target filter (experimental): a small multi-target tracker
// that sits on top of the RD-03D's own output.
// Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
// Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
//
// The RD-03D does its own detection and tracking inside the chip and hands us
// up to three (x, y, speed) slots per frame. Those slots flicker, swap places,
// include one-frame false alarms, wall reflections ("ghosts") and things that
// wobble in place (fans, curtains). This layer cleans that up the way bigger
// mmWave people trackers do (gate → associate → filter → manage), scaled down
// to three detections and six tracks:
//
//   1. range/field-of-view gate        drop 0–10 cm, > 8 m, outside ±65°
//   2. predict                          constant-velocity motion model
//   3. associate                        best overall detection↔track pairing (brute force, ≤ 3×6)
//   4. alpha-beta filter                smooth position, estimate velocity
//   5. confirm M-of-N                   a new track must be seen in 3 of its last 5 frames
//   6. coast                            keep a track ~1 s through missed frames, then drop it
//   7. ghost check                      farther, same bearing, moving in lockstep with a nearer track
//                                       → probably a reflection, hidden while that holds
//   8. clutter map                      something that keeps "moving" without going anywhere
//                                       for 30 s (fan, curtain) is muted; the spot is remembered
//                                       for a few minutes
//
// Plain C++ (no Arduino) so tests/test_tracker.cpp runs it natively.
// tools/tracker_py.py is a line-by-line Python port used by the simulator;
// tests/test_tracker_py.py checks the two agree.
#pragma once
#include <stdint.h>
#include <math.h>
#include <string.h>
#include "rd03d.h"

namespace blip_track {

static const int MAX_TRACKS = 6;
static const int GRID = 16;                // clutter map: 16 × 16 cells of 0.5 m
static const float CELL_MM = 500.0f;

enum State : uint8_t { TENTATIVE = 0, CONFIRMED = 1, GHOST = 2, CLUTTER = 3 };

struct Cfg {
  float minRange = 100, maxRange = 8000, maxAngleDeg = 65;
  float gateMm = 700;                      // base association gate
  float vmaxMms = 3500;                    // fastest plausible walker/runner indoors
  float alpha = 0.5f, beta = 0.15f;        // alpha-beta filter gains
  int confirmHits = 3;                     // ... out of the last 5 frames
  float coastS = 1.0f;                     // drop a confirmed track after this long unseen
  float clutterS = 30.0f;                  // in-place wobble this long → clutter
  float clutterRadius = 400;               // "in place" = within this of where it started
  float ghostBearingDeg = 10, ghostBehindMm = 500, ghostS = 1.0f;
};

struct Track {
  bool used = false;
  uint16_t id = 0;
  State st = TENTATIVE;
  float x = 0, y = 0, vx = 0, vy = 0;      // mm, mm/s
  float vDop = 0;                          // last speed reported by the module, mm/s (module's sign)
  float vDopF = 0;                         // the same, smoothed (~0.3 s) for the ghost test
  uint8_t hist = 0;                        // bit0 = seen this frame
  float unseen = 0;                        // seconds since last matched
  float ax = 0, ay = 0, still = 0;         // anchor for the clutter test
  float sx = 0, sy = 0;                    // slow (~1 s) average position, so noise and coasting don't count as moving
  float ghostT = 0;                        // seconds the ghost condition has held
  bool suspect = false;                    // sits behind a moving track on the same bearing
  float age = 0;                           // seconds since the track was born
  uint16_t ghostOf = 0;
  float range() const { return sqrtf(x * x + y * y); }
  float bearingDeg() const { return atan2f(x, y) * 57.29578f; }
  float radialV() const { float r = range(); return r > 1 ? (x * vx + y * vy) / r : 0; }
};

class Tracker {
 public:
  Cfg cfg;

  void reset() { for (auto& t : tr_) t = Track(); nextId_ = 1; }
  void forgetClutter() { memset(clutter_, 0, sizeof clutter_); }
  Tracker() { reset(); forgetClutter(); }

  const Track& track(int i) const { return tr_[i]; }

  // Feed one RD-03D frame. dt = seconds since the previous frame.
  void update(const rd03d::Frame& f, float dt) {
    if (dt <= 0 || dt > 0.5f) dt = 0.05f;
    // 1. gate the raw detections
    float dx[rd03d::MAX_TARGETS], dy[rd03d::MAX_TARGETS], dv[rd03d::MAX_TARGETS];
    int n = 0;
    for (int i = 0; i < rd03d::MAX_TARGETS; i++) {
      const rd03d::Target& t = f.t[i];
      if (!t.present) continue;
      float r = sqrtf((float)t.x_mm * t.x_mm + (float)t.y_mm * t.y_mm);
      float a = fabsf(atan2f((float)t.x_mm, (float)t.y_mm) * 57.29578f);
      if (r < cfg.minRange || r > cfg.maxRange || a > cfg.maxAngleDeg || t.y_mm <= 0) continue;
      dx[n] = t.x_mm; dy[n] = t.y_mm; dv[n] = t.v_cms * 10.0f; n++;
    }
    // 2. predict
    for (auto& t : tr_) if (t.used) { t.x += t.vx * dt; t.y += t.vy * dt; t.hist <<= 1; t.unseen += dt; t.age += dt; }

    // 3. associate: try every assignment of detections to tracks (or to "new")
    int best[rd03d::MAX_TARGETS + 1], cur[rd03d::MAX_TARGETS + 1];   // +1: keeps -Warray-bounds quiet
    for (int i = 0; i <= rd03d::MAX_TARGETS; i++) best[i] = cur[i] = -1;
    bestCost_ = 1e30f;
    search(0, n, dx, dy, dt, cur, best, 0.0f, 0);

    // 4. update matched tracks, start new ones
    for (int k = 0; k < n; k++) {
      int j = best[k];
      if (j >= 0) {
        Track& t = tr_[j];
        float rx = dx[k] - t.x, ry = dy[k] - t.y;
        t.x += cfg.alpha * rx; t.y += cfg.alpha * ry;
        t.vx += cfg.beta * rx / dt; t.vy += cfg.beta * ry / dt;
        float sp = sqrtf(t.vx * t.vx + t.vy * t.vy);
        if (sp > cfg.vmaxMms) { t.vx *= cfg.vmaxMms / sp; t.vy *= cfg.vmaxMms / sp; }
        t.vDop = dv[k]; t.vDopF += 0.15f * (dv[k] - t.vDopF); t.hist |= 1; t.unseen = 0;
      } else {
        int s = freeSlot();
        if (s < 0) continue;
        Track& t = tr_[s];
        t = Track();
        t.used = true; t.id = nextId_++; if (nextId_ == 0) nextId_ = 1;
        t.x = t.ax = t.sx = dx[k]; t.y = t.ay = t.sy = dy[k]; t.vDop = t.vDopF = dv[k]; t.hist = 1;
      }
    }

    // 7. ghosts: B is farther than A along (nearly) the same bearing and its
    //    range changes at the same rate — the classic "reflection behind you".
    //    Runs before confirmation so a reflection can be caught before it ever shows.
    for (auto& b : tr_) {
      if (!b.used || b.st == CLUTTER) continue;
      bool cond = false, sus = false; uint16_t of = 0;
      for (auto& a : tr_) {
        if (&a == &b || !a.used || a.st != CONFIRMED) continue;
        // Compare the module's own (smoothed) Doppler speeds: both come from the
        // same chip with the same sign convention, and they are far less noisy
        // than speeds differentiated from jittery positions.
        float va = a.vDopF, vb = b.vDopF;
        if (fabsf(va) < 100) continue;                       // A must be moving to cast a moving ghost
        bool behind = b.range() - a.range() > cfg.ghostBehindMm;
        bool sameBearing = fabsf(b.bearingDeg() - a.bearingDeg()) < cfg.ghostBearingDeg;
        if (behind && sameBearing) {
          sus = true;
          if (fabsf(vb - va) < fmaxf(150.0f, 0.3f * fabsf(va))) { cond = true; of = a.id; break; }
        }
      }
      b.suspect = sus;
      b.ghostT += cond ? dt : -dt;
      if (b.ghostT < 0) b.ghostT = 0;
      if (b.ghostT > 3) b.ghostT = 3;
      if ((b.st == CONFIRMED || b.st == TENTATIVE) && b.ghostT >= cfg.ghostS) { b.st = GHOST; b.ghostOf = of; }
      else if (b.st == GHOST && b.ghostT <= 0) b.st = CONFIRMED;   // moved independently for a while
    }

    // 5./6. confirm, coast, drop
    for (auto& t : tr_) {
      if (!t.used) continue;
      int hits = popcount5(t.hist);
      if (t.st == TENTATIVE) {
        bool clutterCell = cellScore(t.x, t.y) > 128;
        bool wait = t.suspect && t.age < cfg.ghostS + 0.5f;   // possible reflection: give the ghost test time
        // born on a known clutter spot: track it but keep it muted until it walks 0.8 m away
        if (hits >= cfg.confirmHits && !wait) { t.st = clutterCell ? CLUTTER : CONFIRMED; if (clutterCell) markCell(t.x, t.y); }
        else if (t.unseen > 0.2f && hits < 2) { t.used = false; continue; }
      }
      if (t.unseen > cfg.coastS) { t.used = false; continue; }
      if (t.unseen > 0) { t.vx *= 0.9f; t.vy *= 0.9f; }      // coast and slow down, don't fly off
      // 8. clutter: still "moving" (the module keeps reporting it) but going nowhere
      if (t.unseen == 0) { t.sx += 0.05f * (t.x - t.sx); t.sy += 0.05f * (t.y - t.sy); }
      float ddx = t.sx - t.ax, ddy = t.sy - t.ay;
      float lim = t.st == CLUTTER ? 2 * cfg.clutterRadius : cfg.clutterRadius;   // muted things must go properly far to come back
      if (ddx * ddx + ddy * ddy > lim * lim) {
        t.ax = t.sx; t.ay = t.sy; t.still = 0;
        if (t.st == CLUTTER) t.st = CONFIRMED;               // it walked away: it's real
      } else if (t.unseen < 0.5f) {                        // seen recently (the chip only has 3 slots to share)
        t.still += dt;
        // 30 s to learn a new spot; on a spot already known as clutter, 3 s is enough
        float need = cellScore(t.sx, t.sy) > 128 ? 3.0f : cfg.clutterS;
        if (t.still > need && (t.st == CONFIRMED || t.st == TENTATIVE)) { t.st = CLUTTER; markCell(t.ax, t.ay); }
      }
    }

    // clutter map slowly forgets (~every 2 s, so a marked cell fades in ~8 min)
    decayT_ += dt;
    if (decayT_ >= 2.0f) { decayT_ = 0; for (auto& row : clutter_) for (auto& c : row) if (c) c--; }
  }

  // Visible targets in the same shape as a raw frame (nearest first), plus their track ids.
  void visible(rd03d::Frame& out, uint16_t ids[rd03d::MAX_TARGETS]) const {
    memset(&out, 0, sizeof out);
    int idx[MAX_TRACKS], m = 0;
    for (int i = 0; i < MAX_TRACKS; i++) if (tr_[i].used && tr_[i].st == CONFIRMED) idx[m++] = i;
    for (int i = 1; i < m; i++) for (int j = i; j > 0 && tr_[idx[j]].range() < tr_[idx[j - 1]].range(); j--) { int s = idx[j]; idx[j] = idx[j - 1]; idx[j - 1] = s; }
    for (int k = 0; k < m && k < rd03d::MAX_TARGETS; k++) {
      const Track& t = tr_[idx[k]];
      rd03d::Target& o = out.t[k];
      o.present = true; o.x_mm = (int16_t)lroundf(t.x); o.y_mm = (int16_t)lroundf(t.y);
      o.v_cms = (int16_t)lroundf(t.vDop / 10.0f); o.res_mm = 0;
      ids[k] = t.id; out.count++;
    }
  }

  uint8_t cellScore(float x, float y) const { int ix, iy; cell(x, y, ix, iy); return clutter_[iy][ix]; }

 private:
  Track tr_[MAX_TRACKS];
  uint16_t nextId_ = 1;
  uint8_t clutter_[GRID][GRID];
  float decayT_ = 0;
  float bestCost_ = 0;

  static int popcount5(uint8_t h) { int c = 0; for (int i = 0; i < 5; i++) c += (h >> i) & 1; return c; }
  int freeSlot() const { for (int i = 0; i < MAX_TRACKS; i++) if (!tr_[i].used) return i; return -1; }
  static void cell(float x, float y, int& ix, int& iy) {
    ix = (int)((x + GRID * CELL_MM / 2) / CELL_MM); iy = (int)(y / CELL_MM);
    if (ix < 0) ix = 0;
    if (ix >= GRID) ix = GRID - 1;
    if (iy < 0) iy = 0;
    if (iy >= GRID) iy = GRID - 1;
  }
  // mark the cell and its neighbours (a 1.5 m patch): a wobbling fan straddles cell edges
  void markCell(float x, float y) {
    int ix, iy; cell(x, y, ix, iy);
    for (int j = iy - 1; j <= iy + 1; j++) for (int i = ix - 1; i <= ix + 1; i++)
      if (i >= 0 && i < GRID && j >= 0 && j < GRID) clutter_[j][i] = 255;
  }

  float gateFor(const Track& t, float dt) const { return cfg.gateMm + cfg.vmaxMms * (dt + t.unseen); }

  // depth-first search over detection k: assign to a free track within its gate, or leave unassigned
  void search(int k, int n, const float* dx, const float* dy, float dt, int* cur, int* best, float cost, uint8_t usedMask) {
    if (cost >= bestCost_) return;
    if (k >= n || k >= rd03d::MAX_TARGETS) { bestCost_ = cost; for (int i = 0; i < n; i++) best[i] = cur[i]; return; }
    for (int j = 0; j < MAX_TRACKS; j++) {
      const Track& t = tr_[j];
      if (!t.used || (usedMask >> j) & 1) continue;
      float ex = dx[k] - t.x, ey = dy[k] - t.y, d = sqrtf(ex * ex + ey * ey);
      float g = gateFor(t, dt);
      if (d > g) continue;
      float c = d / g;                                      // normalised distance
      if (t.st == TENTATIVE) c += 0.15f;                     // prefer established tracks
      cur[k] = j;
      search(k + 1, n, dx, dy, dt, cur, best, cost + c, usedMask | (1 << j));
    }
    cur[k] = -1;
    search(k + 1, n, dx, dy, dt, cur, best, cost + 1.2f, usedMask);   // "new track" costs more than any match
  }
};

}  // namespace blip_track
