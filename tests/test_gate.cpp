// Blip — native tests for firmware/include/gate.h (minimum range, edge limit, handheld mode).
//   g++ -std=c++17 -O2 -Wall -Wextra -I firmware/include tests/test_gate.cpp -o test_gate && ./test_gate
// Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
// Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
// Synthetic scenes only: nothing here has been checked against a real carried radar.
#include <cstdio>
#include <cstring>
#include <cmath>
#include <vector>
#include "gate.h"
using namespace blip_gate;

static int fails = 0;
#define CHECK(c, ...) do { printf((c) ? "PASS  " : "FAIL  "); printf(__VA_ARGS__); printf("\n"); if (!(c)) fails++; } while (0)
static uint32_t rng = 4242;
static double frand() { rng = rng * 1664525u + 1013904223u; return ((rng >> 8) / 16777216.0) * 2 - 1; }

struct Det { double x, y, approach; };      // approach in mm/s, + = closing
static rd03d::Frame frameOf(const std::vector<Det>& d) {
  rd03d::Frame f; memset(&f, 0, sizeof f);
  for (size_t i = 0; i < d.size() && i < 3; i++) {
    f.t[i].present = true; f.t[i].x_mm = (int16_t)lround(d[i].x); f.t[i].y_mm = (int16_t)lround(d[i].y);
    f.t[i].v_cms = (int16_t)lround(-d[i].approach / 10); f.count++;
  }
  return f;
}
static bool kept(const rd03d::Frame& f, double x, double y) {
  for (auto& t : f.t) if (t.present && hypot(t.x_mm - x, t.y_mm - y) < 1) return true;
  return false;
}

int main() {
  // ---- minimum range ---------------------------------------------------------
  {
    Gate g; rd03d::Frame f = frameOf({{0, 250, 0}, {0, 3000, 500}});
    g.apply(f, 0.05);
    CHECK(kept(f, 0, 250) && f.count == 2, "default (10 cm): a contact at 0.25 m is kept");
    g.cfg.minMm = 500; f = frameOf({{0, 250, 0}, {0, 3000, 500}});
    int d = g.apply(f, 0.05);
    CHECK(!kept(f, 0, 250) && kept(f, 0, 3000) && d == 1 && f.count == 1 && g.why(0) == NEAR, "0.5 m: the 0.25 m contact is dropped, the 3 m one kept");
  }
  // ---- edge limit ------------------------------------------------------------
  {
    Gate g; g.cfg.maxDeg = 45;
    double a = 55 * M_PI / 180;
    rd03d::Frame f = frameOf({{3000 * sin(a), 3000 * cos(a), 300}, {500, 3000, 300}});
    g.apply(f, 0.05);
    CHECK(!kept(f, 3000 * sin(a), 3000 * cos(a)) && f.count == 1 && g.why(0) == EDGE, "45° limit: a contact at 55° is dropped, one at 9° kept");
  }
  // ---- handheld: walking down a street at 1.2 m/s ------------------------------
  // lamp posts / parked cars (fixed) at three bearings + one pedestrian walking towards us
  {
    Gate g; g.cfg.handheld = true;
    int postShown = 0, postFrames = 0, pedShown = 0, pedFrames = 0;
    double walk = 1200;
    for (int k = 0; k < 20 * 60; k++) {
      double t = k * 0.05;
      std::vector<Det> d;
      int slot = k % 3;                                     // the chip shares its 3 slots around
      double bear[3] = {-30, 10, 40};
      for (int i = 0; i < 2; i++) {
        double b = bear[(slot + i) % 3] * M_PI / 180, r = 2000 + 3000 * (0.5 + 0.5 * sin(0.2 * t + i));
        d.push_back({r * sin(b), r * cos(b), walk * cos(b) + 60 * frand()});
      }
      double pb = 5 * M_PI / 180, pr = 6000 - fmod(t * 2200, 5000);
      Det ped{pr * sin(pb), pr * cos(pb), (walk + 1000) * cos(pb) + 60 * frand()};
      d.push_back(ped);
      rd03d::Frame f = frameOf(d);
      g.apply(f, 0.05);
      if (k > 40) {
        for (int i = 0; i < 2; i++) { postFrames++; postShown += kept(f, lround(d[i].x), lround(d[i].y)); }
        pedFrames++; pedShown += kept(f, lround(ped.x), lround(ped.y));
      }
    }
    CHECK(postShown * 10 < postFrames, "fixed objects passed while walking are hidden (shown %d of %d)", postShown, postFrames);
    CHECK(pedShown * 100 > pedFrames * 95, "a pedestrian walking towards us stays shown (%d of %d)", pedShown, pedFrames);
    CHECK(fabsf(g.ego() - 1200) < 150, "our walking speed is estimated (%.0f mm/s, truth 1200)", g.ego());
  }
  // ---- handheld while standing still: nothing is touched ---------------------------
  {
    Gate g; g.cfg.handheld = true; int shown = 0, frames = 0;
    for (int k = 0; k < 400; k++) {
      double t = k * 0.05, y = 3000 + 1500 * sin(0.4 * t), v = -600 * cos(0.4 * t);   // approach = -dy/dt
      rd03d::Frame f = frameOf({{300, y, v}, {-1200, 5000 - y / 3, -v / 3}});
      g.apply(f, 0.05);
      frames++; shown += f.count == 2;
    }
    CHECK(shown == frames, "radar held still: two people walking are both always shown (%d of %d)", shown, frames);
  }
  // ---- handheld: someone walking beside us (same speed) is not scenery ---------------
  {
    Gate g; g.cfg.handheld = true; int shown = 0, frames = 0;
    for (int k = 0; k < 400; k++) {
      double b1 = -20 * M_PI / 180, b2 = 30 * M_PI / 180;
      rd03d::Frame f = frameOf({{4000 * sin(b1), 4000 * cos(b1), 1200 * cos(b1)}, {3000 * sin(b2), 3000 * cos(b2), 1200 * cos(b2)}, {200, 900, 0}});
      g.apply(f, 0.05);
      if (k > 20) { frames++; shown += kept(f, 200, 900); }
    }
    CHECK(shown == frames, "a companion walking alongside (closing speed 0) stays shown (%d of %d)", shown, frames);
  }
  // ---- handheld: the estimate is only held for 1.5 s ---------------------------------
  {
    Gate g; g.cfg.handheld = true;
    for (int k = 0; k < 40; k++) { rd03d::Frame f = frameOf({{0, 4000, 1000}, {1000, 3000, 970}}); g.apply(f, 0.05); }
    rd03d::Frame f = frameOf({{0, 5000, 1000}}); g.apply(f, 0.05);
    bool early = f.count == 0;
    for (int k = 0; k < 40; k++) { f = frameOf({{0, 5000, 1000}}); g.apply(f, 0.05); }
    CHECK(early && f.count == 1, "a lone fixed contact is hidden while the walking estimate is fresh, shown again after 1.5 s (known limitation)");
  }
  // ---- frozen targets: a phantom at byte-identical coordinates --------------------------
  {
    Gate g; g.cfg.stuckS = 10; int early = 0, late = 0, personDropped = 0;
    for (int k = 0; k < 20 * 20; k++) {                      // 20 s
      double t = k * 0.05;
      rd03d::Frame f = frameOf({{-800, 2500, 0}, {600 + 25 * frand(), 3200 + 15 * frand(), 0}});   // phantom + a still person (wobbles)
      g.apply(f, 0.05);
      bool ph = kept(f, -800, 2500);
      if (t < 9.5) early += ph; else if (t > 10.5) late += !ph;
      if (f.count + (ph ? 0 : 1) < 2) personDropped++;
    }
    CHECK(early == 190 && late == 189, "a phantom at identical x,y is shown for 10 s, then dropped (%d/190 before, %d/189 dropped after)", early, late);
    CHECK(personDropped == 0, "a still person who wobbles by a few mm is never dropped (%d frames)", personDropped);
    rd03d::Frame f = frameOf({{-799, 2500, 0}}); g.apply(f, 0.05);
    CHECK(f.count == 1, "the phantom comes back as soon as it moves by 1 mm");
    // the realistic case: two people walking about fill the other slots, the phantom misses 1 frame in 4
    Gate g2; g2.cfg.stuckS = 10; int shownLate = 0, lateN = 0;
    for (int k = 0; k < 20 * 25; k++) {
      double t = k * 0.05;
      std::vector<Det> d = {{1500 * sin(0.7 * t), 3000 + 1500 * sin(0.3 * t), 300}, {-1200 + 900 * cos(0.5 * t), 5000 - 1000 * cos(0.4 * t), -200}};
      if (k % 4) d.push_back({-800, 2500, 0});
      f = frameOf(d); g2.apply(f, 0.05);
      if (t > 15 && k % 4) { lateN++; shownLate += kept(f, -800, 2500); }
    }
    CHECK(shownLate == 0, "...also when it misses frames and moving targets fill the other slots (shown %d of %d after 15 s)", shownLate, lateN);
    Gate off; for (int k = 0; k < 400; k++) { f = frameOf({{-800, 2500, 0}}); off.apply(f, 0.05); }
    CHECK(f.count == 1, "with the option off (0) nothing is dropped");
  }
  printf(fails ? "\n%d FAILED\n" : "\nALL PASS\n", fails);
  return fails ? 1 : 0;
}
