// Native test for firmware/include/tracker.h (the experimental "Smart" filter).
//   g++ -std=c++17 -O2 -I firmware/include tests/test_tracker.cpp -o /tmp/tt && /tmp/tt [trace.csv]
// Synthetic RD-03D output at 20 Hz with the usual troubles: position noise,
// slots shuffled every frame, one-frame flickers, a wall reflection, a fan,
// two people crossing, dropouts. Synthetic: proves the logic, not the tuning
// against a real room.
#include <cstdio>
#include <cmath>
#include <vector>
#include <algorithm>
#include <map>
#include <set>
#include "tracker.h"

using namespace blip_track;
static int fails = 0;
#define CHECK(c, ...) do { printf((c) ? "PASS  " : "FAIL  "); printf(__VA_ARGS__); printf("\n"); if (!(c)) fails++; } while (0)

static uint32_t rng = 777;
static double frand() { rng = rng * 1664525u + 1013904223u; return ((rng >> 8) / 16777216.0) * 2 - 1; }
static double gauss() { double s = 0; for (int i = 0; i < 6; i++) s += frand(); return s / sqrt(2.0); }

struct Det { double x, y, v; };
static const double DT = 0.05;

static rd03d::Frame frameOf(std::vector<Det> d) {
  rd03d::Frame f; memset(&f, 0, sizeof f);
  for (size_t i = d.size(); i > 1; i--) std::swap(d[i - 1], d[(size_t)((frand() * 0.5 + 0.5) * i) % i]);   // chip slots swap about
  for (size_t i = 0; i < d.size() && i < 3; i++) {
    f.t[i].present = true; f.t[i].x_mm = (int16_t)lround(d[i].x); f.t[i].y_mm = (int16_t)lround(d[i].y);
    f.t[i].v_cms = (int16_t)lround(d[i].v / 10); f.count++;
  }
  return f;
}
static Det noisy(double x, double y, double vr) { return {x + 120 * gauss(), y + 60 * gauss(), vr}; }

// visible tracks as id → (x,y)
static std::map<int, std::pair<double, double>> vis(const Tracker& T) {
  rd03d::Frame o; uint16_t ids[3] = {0};
  T.visible(o, ids);
  std::map<int, std::pair<double, double>> m;
  for (int i = 0; i < 3; i++) if (o.t[i].present) m[ids[i]] = {(double)o.t[i].x_mm, (double)o.t[i].y_mm};
  return m;
}

int main(int argc, char** argv) {
  FILE* tr = argc > 1 ? fopen(argv[1], "w") : nullptr;
  if (tr) fprintf(tr, "scene,t,kind,x,y,id\n");

  // ---- 1) one person walking an ellipse, with flickers and dropouts ----------
  {
    Tracker T; std::set<int> idsSeen; int falseVis = 0, frames = 0; double errRaw = 0, errTrk = 0; int ne = 0;
    for (int k = 0; k < 20 * 60; k++) {
      double t = k * DT, x = 1500 * sin(0.25 * t), y = 3500 + 1200 * cos(0.25 * t);
      double vx = 1500 * 0.25 * cos(0.25 * t), vy = -1200 * 0.25 * sin(0.25 * t), r = hypot(x, y), vr = (x * vx + y * vy) / r;
      std::vector<Det> d;
      bool drop = (k % 97) < 6;                                   // 0.3 s gaps now and then
      Det p = noisy(x, y, vr);
      if (!drop) d.push_back(p);
      if (frand() > 0.85) d.push_back({frand() * 3000, 1000 + (frand() * 0.5 + 0.5) * 6000, frand() * 500});   // flicker
      T.update(frameOf(d), DT);
      auto m = vis(T);
      if (k > 40) {
        frames++;
        for (auto& kv : m) {
          double e = hypot(kv.second.first - x, kv.second.second - y);
          if (e > 700) falseVis++; else { idsSeen.insert(kv.first); errTrk += e * e; ne++; }
        }
        if (!drop) errRaw += (p.x - x) * (p.x - x) + (p.y - y) * (p.y - y);
      }
      if (tr) { if (!drop) fprintf(tr, "walk,%.2f,raw,%.0f,%.0f,0\n", t, p.x, p.y); for (auto& kv : m) fprintf(tr, "walk,%.2f,trk,%.0f,%.0f,%d\n", t, kv.second.first, kv.second.second, kv.first); }
    }
    double rmsRaw = sqrt(errRaw / frames), rmsTrk = sqrt(errTrk / std::max(1, ne));
    CHECK(idsSeen.size() == 1, "one walker keeps one id for 60 s through 0.3 s dropouts (%zu ids)", idsSeen.size());
    CHECK(falseVis * 100 < frames, "15%% one-frame flickers almost never shown (%d of %d frames)", falseVis, frames);
    CHECK(rmsTrk < rmsRaw, "smoothed position closer to the truth than raw (%.0f vs %.0f mm rms)", rmsTrk, rmsRaw);
  }

  // ---- 2) wall reflection: a copy 1.2 m behind on the same bearing ------------
  {
    Tracker T; int ghostVisFrames = 0, realVis = 0, frames = 0;
    for (int k = 0; k < 20 * 30; k++) {
      double t = k * DT, y = 2000 + 1500 * sin(0.4 * t), x = 300, vy = 1500 * 0.4 * cos(0.4 * t);
      double r = hypot(x, y), vr = y / r * vy;
      double gr = r + 1200, gx = x / r * gr, gy = y / r * gr;      // same bearing, farther
      std::vector<Det> d = {noisy(x, y, vr)};
      if (frand() > 0.2) d.push_back(noisy(gx, gy, vr));          // reflection seen 80% of frames
      T.update(frameOf(d), DT);
      auto m = vis(T);
      if (k > 60) {
        frames++;
        bool real = false;
        for (auto& kv : m) { double ex = kv.second.first - x, ey = kv.second.second - y; if (hypot(ex, ey) < 700) real = true; else ghostVisFrames++; }
        realVis += real;
      }
      if (tr) for (auto& kv : m) fprintf(tr, "ghost,%.2f,trk,%.0f,%.0f,%d\n", t, kv.second.first, kv.second.second, kv.first);
    }
    CHECK(ghostVisFrames * 20 < frames, "wall reflection hidden >95%% of the time (shown %d of %d frames)", ghostVisFrames, frames);
    CHECK(realVis * 100 > frames * 95, "the real person still shown (%d of %d frames)", realVis, frames);
  }

  // ---- 3) a fan wobbling in place, then someone walks past it ----------------
  {
    Tracker T; int fanVisLate = 0, lateFrames = 0, walkerVis = 0, walkFrames = 0;
    for (int k = 0; k < 20 * 70; k++) {
      double t = k * DT;
      std::vector<Det> d = {{-1500 + 100 * gauss(), 4000 + 100 * gauss(), 200 * frand()}};
      bool walking = t > 55;
      double wx = -3000 + (t - 55) * 1000, wy = 2500;
      if (walking) d.push_back(noisy(wx, wy, 0));
      T.update(frameOf(d), DT);
      auto m = vis(T);
      if (t > 35) {
        lateFrames++;
        for (auto& kv : m) if (hypot(kv.second.first + 1500, kv.second.second - 4000) < 700) fanVisLate++;
      }
      if (walking && t > 56 && fabs(atan2(wx, wy)) < 1.05) {  /* inside the ±60° field of view */ walkFrames++; for (auto& kv : m) if (hypot(kv.second.first - wx, kv.second.second - wy) < 700) { walkerVis++; break; } }
    }
    CHECK(fanVisLate * 50 < lateFrames, "fan muted as clutter after 30 s (shown %d of %d frames after 35 s)", fanVisLate, lateFrames);
    CHECK(walkerVis * 10 > walkFrames * 9, "a person walking past the fan is still shown (%d of %d)", walkerVis, walkFrames);
  }

  // ---- 4) two people crossing paths -------------------------------------------
  {
    Tracker T; int okEnd = 0; std::map<int, int> idA, idB;
    for (int k = 0; k < 20 * 10; k++) {
      double t = k * DT;
      double ax = -2500 + 500 * t, ay = 3000, bx = 2500 - 500 * t, by = 3600;   // pass 0.6 m apart at t = 5 s
      T.update(frameOf({noisy(ax, ay, 0), noisy(bx, by, 0)}), DT);
      auto m = vis(T);
      for (auto& kv : m) {
        if (hypot(kv.second.first - ax, kv.second.second - ay) < 500) idA[kv.first]++;
        if (hypot(kv.second.first - bx, kv.second.second - by) < 500) idB[kv.first]++;
      }
      if (k == 199) okEnd = (int)m.size();
      if (tr) for (auto& kv : m) fprintf(tr, "cross,%.2f,trk,%.0f,%.0f,%d\n", t, kv.second.first, kv.second.second, kv.first);
    }
    auto top = [](std::map<int, int>& c) { int best = -1, n = 0; for (auto& kv : c) if (kv.second > n) { n = kv.second; best = kv.first; } return std::make_pair(best, n); };
    auto a = top(idA), b = top(idB);
    CHECK(okEnd == 2, "two crossing people are both shown at the end (%d)", okEnd);
    CHECK(a.first != b.first && a.second > 170 && b.second > 170, "each keeps its own id through the crossing (A id %d %d frames, B id %d %d frames)", a.first, a.second, b.first, b.second);
  }

  // ---- 6) a real second person behind, same bearing, walking differently ----
  {
    Tracker T; int bVis = 0, frames = 0;
    for (int k = 0; k < 20 * 30; k++) {
      double t = k * DT;
      double ay = 2000 + 1000 * sin(0.5 * t), avy = 500 * cos(0.5 * t);
      double by = 4500 + 800 * sin(0.9 * t + 2), bvy = 720 * cos(0.9 * t + 2);
      T.update(frameOf({noisy(0, ay, avy), noisy(0, by, bvy)}), DT);
      auto m = vis(T);
      if (k > 60) { frames++; for (auto& kv : m) if (hypot(kv.second.first, kv.second.second - by) < 700) { bVis++; break; } }
    }
    CHECK(bVis * 10 > frames * 9, "a real person behind, moving differently, is not mistaken for a ghost (%d of %d)", bVis, frames);
  }

  // ---- known limitation: two people in single file, in step --------------------
  {
    Tracker T; int bVis = 0, frames = 0;
    for (int k = 0; k < 20 * 20; k++) {
      double t = k * DT, ay = 2000 + 1000 * sin(0.5 * t), v = 500 * cos(0.5 * t);
      T.update(frameOf({noisy(0, ay, v), noisy(0, ay + 1500, v)}), DT);
      auto m = vis(T);
      if (k > 60) { frames++; for (auto& kv : m) if (hypot(kv.second.first, kv.second.second - ay - 1500) < 700) { bVis++; break; } }
    }
    printf("INFO  known limitation: second of two people walking in single file, in step, shown %d of %d frames (looks exactly like a reflection)\n", bVis, frames);
  }

  // ---- 5) range / field-of-view gate -----------------------------------------
  {
    Tracker T;
    for (int k = 0; k < 40; k++) T.update(frameOf({{5000, 1000, 0}, {0, 50, 0}, {0, 9000, 0}}), DT);   // 79°, 5 cm, 9 m
    CHECK(vis(T).empty(), "detections outside ±65°, under 10 cm or over 8 m are never shown");
  }

  if (tr) fclose(tr);
  printf(fails ? "\n%d FAILED\n" : "\nALL PASS\n", fails);
  return fails ? 1 : 0;
}
