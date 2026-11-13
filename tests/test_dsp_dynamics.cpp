// How the Stetho audio chain behaves in time: what happens to the heart AFTER a knock or a big movement,
// how loud a knock gets, and whether Wi-Fi-beacon-like bursts are removed without touching the heart.
//   g++ -std=c++20 -O2 -I firmware/include -I tests tests/test_dsp_dynamics.cpp -o /tmp/t && /tmp/t
// Why this exists: with the first chain, a knock left the heart 15-20 dB too quiet for several seconds and a big
// movement 30-48 dB too quiet (the AGC level estimate was inflated by the event and decayed at 1 s while the gain
// followed it), on top of a 150 ms hold and a 120 ms release of a 30 dB duck. See docs/STETHO_SIGNAL_NOTES.md.
#include <cstdio>
#include <algorithm>
#include <vector>
#include "audio_dsp.h"
#include "dsp_scenes.h"

using namespace blipdsp;
static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("PASS  "); printf(__VA_ARGS__); printf("\n"); } else { printf("FAIL  "); printf(__VA_ARGS__); printf("\n"); fails++; } } while (0)

static std::vector<int16_t> runChain(const Scene& sc, const Params& p, long* blankSamples = nullptr, long* frozenSamples = nullptr) {
  AudioChain c; c.configure(p); std::vector<int16_t> out(sc.N); long bl = 0, fz = 0;
  for (int i = 0; i < sc.N; i++) { out[i] = c.process(sc.at(i)); bl += c.blanking(); fz += c.frozen(); }
  if (blankSamples) *blankSamples = bl;
  if (frozenSamples) *frozenSamples = fz;
  return out;
}
// output energy in a 60 ms window at each S1, over the heart's own energy there (dB)
static std::vector<double> beatGain(const Scene& sc, const std::vector<int16_t>& out) {
  std::vector<double> g;
  for (int i0 : sc.s1) { if (i0 + 500 > sc.N) break; double so = 0, si = 0; for (int k = 0; k < 480; k++) { so += (double)out[i0 + k] * out[i0 + k]; si += sc.heart[i0 + k] * sc.heart[i0 + k]; } g.push_back(10 * log10((so + 1) / (si + 1))); }
  return g;
}

int main() {
  Params p; p.preset = HEART; p.nsStrength = 100; p.bumpSens = 34;      // the user's settings in the bench photo
  const int N = 8000 * 20; const double bpm = 72, per = 60.0 / bpm;

  // ---- 1) the heart comes back right after a knock / movement --------------------------------
  struct D { const char* name; int kind; double a; double lim[4]; };       // worst allowed dip (dB) at beat +1..+4
  const D ds[] = {
    {"knock 300 LSB",           0,  300, {-4, -3, -2, -1.5}},
    {"knock 600 LSB",           0,  600, {-4, -3, -2, -1.5}},
    {"knock 2000 LSB (rails)",  0, 2000, {-4, -3, -2, -1.5}},
    {"movement 1.5 s, 400 LSB", 1,  400, {-4, -3, -2, -1.5}},
    {"movement 1.5 s, 900 LSB", 1,  900, {-7, -4, -2.5, -1.5}},
    {"movement 3 s, 900 LSB",   2,  900, {-9, -5, -3, -2}},               // longer than the 3 s hold: AGC may start to adapt
  };
  for (const D& d : ds) {
    double worst[4] = {0, 0, 0, 0};
    for (int trial = 0; trial < 16; trial++) {
      double t0 = 9.0 + (trial % 8) / 8.0 * per;                            // where in the heart cycle it starts
      Rng r; r.s = 77 + trial; Scene a(N); a.addHeart(bpm, 40); a.addNoise(25, r);
      Scene b = a; Rng rk; rk.s = 5 + trial; double end;
      if (d.kind == 0) { b.addKnock(t0 * 1000, d.a, rk); end = t0 + 0.3; } else { double dur = d.kind == 1 ? 1500 : 3000; b.addMove(t0 * 1000, dur, d.a); end = t0 + dur / 1000; }
      auto g0 = beatGain(a, runChain(a, p)), g1 = beatGain(b, runChain(b, p));
      int k = 0; for (size_t i = 0; i < a.s1.size() && i < g0.size() && k < 4; i++) if (a.s1[i] / 8000.0 > end + 0.05) { worst[k] = std::min(worst[k], g1[i] - g0[i]); k++; }
    }
    bool ok = true; for (int k = 0; k < 4; k++) ok = ok && worst[k] >= d.lim[k];
    CHECK(ok, "%-24s heart gain change on the next 4 beats, worst of 16 trials: %+.1f %+.1f %+.1f %+.1f dB", d.name, worst[0], worst[1], worst[2], worst[3]);
  }

  // ---- 2) a knock is squeezed, not blasted, and does not overshoot the limiter ----------------------
  for (double amp : {300.0, 2000.0}) {
    Rng r; Scene s(N); s.addHeart(bpm, 40); s.addNoise(25, r); Rng rk; s.addKnock(12000, amp, rk);
    auto out = runChain(s, p); int pkHeart = 0, pkKnock = 0;
    for (int i = 8000 * 6; i < 8000 * 11; i++) pkHeart = std::max(pkHeart, (int)abs(out[i]));
    for (int i = 8000 * 12; i < 8000 * 12 + 2400; i++) pkKnock = std::max(pkKnock, (int)abs(out[i]));
    CHECK(pkKnock < 20500 && pkKnock < 4 * pkHeart, "knock %.0f LSB: output peak %d (limiter ceiling %d), heart peaks %d: knock no more than 12 dB over the heart", amp, pkKnock, (int)LIM_CEIL, pkHeart);
  }
  {
    // a knock that rails the ADC is certain to raise the bump flag: how long does the flag (and the duck behind it) last?
    Rng r; Scene s(N); s.addHeart(bpm, 40); s.addNoise(25, r); Rng rk; s.addKnock(12000, 2000, rk);
    AudioChain c; c.configure(p); int first = -1, last = -1;
    for (int i = 0; i < N; i++) { c.process(s.at(i)); if (i > 8000 && c.bumpActive()) { if (first < 0) first = i; last = i; } }
    CHECK(first >= 8000 * 12 && last < 8000 * 12 + 8 * 400, "railing knock: bump flag %.0f ms after it starts, over %.0f ms after it starts (was 150 ms hold + 120 ms release of a 30 dB duck)",
          (first - 96000) / 8.0, (last - 96000) / 8.0);
  }

  // ---- 3) burst blanker -------------------------------------------------------------------------
  {
    const int M = 8000 * 30; Params off = p; off.blanker = false; Params on = p; on.nsStrength = off.nsStrength = 60;
    auto gapLevel = [&](const Scene& s, const Params& q, long* blank, double* beat) {
      auto out = runChain(s, q, blank); double eg = 0, eb = 0, ei = 0; long ng = 0, nb = 0;
      for (int i = 8000 * 4; i < s.N - 500; i++) { bool b = false; for (int i0 : s.s1) if (i >= i0 && i < i0 + 480) { b = true; break; }
        if (b) { eb += (double)out[i] * out[i]; ei += s.heart[i] * s.heart[i]; nb++; } else { eg += (double)out[i] * out[i]; ng++; } }
      *beat = 10 * log10(eb / nb + 1) - 10 * log10(ei / nb + 1); return 10 * log10(eg / ng + 1); };
    Rng r0; Scene clean(M); clean.addHeart(72, 40); clean.addNoise(25, r0);
    long bl0; double bg0; double clean0 = gapLevel(clean, on, &bl0, &bg0);
    CHECK(100.0 * bl0 / M < 1.5, "blanker on a clean scene blanks %.2f %% of the time (false alarms)", 100.0 * bl0 / M);
    for (double amp : {150.0}) for (double dur : {2.5, 5.0}) {
      Rng r; Scene s(M); s.addHeart(72, 40); s.addNoise(25, r); s.addBursts(102.4, dur, amp, r);
      long bl; double bgOn, bgOff; double lOn = gapLevel(s, on, &bl, &bgOn), lOff = gapLevel(s, off, nullptr, &bgOff);
      CHECK(lOff > clean0 + 1.0 && lOn < clean0 + 0.7 && fabs(bgOn - bgOff) < 1.0,
            "beacon-like bursts (9.77 Hz, %.1f ms, %.0f LSB rms): level between beats %.1f dB -> %.1f dB with the blanker (clean scene %.1f); heart gain %+.1f vs %+.1f dB", dur, amp, lOff, lOn, clean0, bgOn, bgOff);
    }
    for (int pr : {VOICE, WIDE, RAW}) {
      Rng r; Scene s(8000 * 6); s.addHeart(72, 40); s.addNoise(25, r); s.addBursts(102.4, 2.5, 300, r);
      Params q; q.preset = pr; long bl; runChain(s, q, &bl);
      CHECK(bl == 0, "preset %-5s has no blanker (its passband leaves no room above it to listen)", PRESETS[pr].id);
    }
  }

  // ---- 4) no false freezes, no latch -------------------------------------------------------------
  {
    Rng r; Scene s(N * 2); s.addHeart(72, 40); s.addNoise(25, r); long fz;
    runChain(s, p, nullptr, &fz);
    CHECK(100.0 * fz / s.N < 2.0, "AGC held (frozen) only %.2f %% of the time on a plain heart + noise scene", 100.0 * fz / s.N);
  }
  {
    // the signal gets 12 dB louder for good (sensor pressed onto the chest): it must not stay frozen
    Rng r; Scene s(8000 * 60); s.addHeart(72, 40); s.addNoise(25, r); for (int i = 15 * 8000; i < s.N; i++) s.heart[i] *= 4;
    AudioChain c; c.configure(p); long fz = 0; for (int i = 0; i < s.N; i++) { c.process(s.at(i)); if (i > 30 * 8000) fz += c.frozen(); }
    CHECK(100.0 * fz / (30 * 8000) < 5.0, "after a permanent +12 dB step the AGC is back to normal within 15 s (frozen %.1f %% of seconds 30-60)", 100.0 * fz / (30 * 8000));
  }

  // ---- 5) oversampling: trimmed mean of 2 / 4 / 8 conversions ------------------------------------------------
  {
    uint16_t a[8] = {2000, 2001, 1999, 2000, 3500, 2000, 1998, 2002};
    CHECK(osMean(a, 8) == 2000 && osMean(a, 4) == 2000, "a conversion hit by a burst (3500 among ~2000) is dropped: 8x -> %u, 4x -> %u", (unsigned)osMean(a, 8), (unsigned)osMean(a, 4));
    Rng r; double v1 = 0, v2 = 0, v4 = 0, v8 = 0; const int K = 20000;
    for (int i = 0; i < K; i++) { uint16_t c[8]; for (int j = 0; j < 8; j++) c[j] = (uint16_t)lround(2000 + r.g() * 8);
      double e1 = (double)osMean(c, 1) - 2000, e2 = (double)osMean(c, 2) - 2000, e4 = (double)osMean(c, 4) - 2000, e8 = (double)osMean(c, 8) - 2000; v1 += e1 * e1; v2 += e2 * e2; v4 += e4 * e4; v8 += e8 * e8; }
    printf("      white ADC noise (8 LSB rms) after averaging: 1x %.2f   2x %.2f   4x trimmed %.2f   8x trimmed %.2f LSB rms\n", sqrt(v1 / K), sqrt(v2 / K), sqrt(v4 / K), sqrt(v8 / K));
    CHECK(sqrt(v2 / K) < 0.78 * sqrt(v1 / K) && sqrt(v4 / K) < 0.78 * sqrt(v1 / K) && sqrt(v8 / K) < 0.55 * sqrt(v1 / K), "oversampling lowers white ADC noise (2x: -3 dB, 4x trimmed: ~-3 dB, 8x trimmed: -6 dB)");
  }

  puts(fails ? "\nSOME FAILED" : "\nALL PASS");
  return fails ? 1 : 0;
}
