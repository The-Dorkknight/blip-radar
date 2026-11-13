// Native test: does the Stetho audio chain stay well-behaved in the situations the real
// node meets, beyond what tests/test_audio_dsp.cpp covers?
//   g++ -std=c++20 -O2 -fsanitize=undefined,address -I firmware/include tests/test_dsp_stability.cpp -o /tmp/t && /tmp/t
//
// The front end (DC tracker, <<3, 80:1 decimator) is copied from Stetho::taskLoop so the
// chain sees what it sees on the board. Scenes:
//   1. start-up on a MAX4466 that idles at ~2700 counts (not 2048) with a few counts of ADC noise
//   2. a CW-Doppler chest (breathing + heart, phase-modulated like the real 24 GHz IF)
//   3. the ADC pinned at a rail for a while, then released (this one used to latch the bump gate for good)
//   4. settings changed 5x a second (what a dragged slider does) while a signal runs
// Thresholds are regression guards chosen from the chain's behaviour when this test was
// written, with margin; they are not a clinical or audio-quality specification.
// Synthetic data only: it proves the maths is stable, not that a real chest sounds like this.
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <vector>
#include <algorithm>
#include "audio_dsp.h"

using namespace blipdsp;
static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("PASS  "); printf(__VA_ARGS__); printf("\n"); } else { printf("FAIL  "); printf(__VA_ARGS__); printf("\n"); fails++; } } while (0)

static uint32_t rng = 777;
static double frand() { rng = rng * 1664525u + 1013904223u; return ((rng >> 8) / 16777216.0) * 2 - 1; }
static double gauss() { double s = 0; for (int i = 0; i < 6; i++) s += frand(); return s / 1.2247; }   // ~N(0,1)

// Same arithmetic as Stetho::taskLoop for one ADC sample.
struct Front {
  AudioChain chain; Decimator dec;
  int32_t dc = 2048 << 14;
  int muteN = 0;
  int16_t vitals = 0; bool vitalsReady = false;
  int16_t push(int32_t v, int32_t* sOut = nullptr) {
    dc += ((v << 14) - dc) >> 14;
    int32_t s = (v - (dc >> 14)) << 3;
    if (sOut) *sOut = s;
    vitalsReady = dec.push(s, vitals);
    int16_t o = chain.process(s);
    if (muteN) { muteN--; o = 0; }
    return o;
  }
};

static double rms(const std::vector<int16_t>& v, size_t a, size_t b) {
  double s = 0; for (size_t i = a; i < b && i < v.size(); i++) s += (double)v[i] * v[i];
  return b > a ? sqrt(s / (double)(std::min(b, v.size()) - a)) : 0;
}
static int peak(const std::vector<int16_t>& v, size_t a, size_t b) {
  int p = 0; for (size_t i = a; i < b && i < v.size(); i++) p = std::max(p, abs((int)v[i])); return p;
}
static double dbfs(double x) { return 20 * log10(std::max(x, 1e-9) / 32768.0); }

int main() {
  // ---- 1) start-up: MAX4466 idles at 2700, 3 counts of ADC noise -----------------------------
  {
    Front f; Params p; p.preset = HEART; f.chain.configure(p);
    f.muteN = 600 * (FS / 1000);                         // applyStetho() mutes 600 ms
    std::vector<int16_t> out;
    for (int i = 0; i < FS * 20; i++) out.push_back(f.push(2700 + (int)lround(3 * gauss())));
    int pk = peak(out, 600 * (FS / 1000), FS * 3);
    printf("      start-up: peak after the 600 ms mute %d (%.1f dBFS)\n", pk, dbfs(pk));
    CHECK(pk < 12000, "start-up thump after the mute is not near full scale (peak %d)", pk);
    double settled = rms(out, FS * 10, FS * 20);
    printf("      idle hiss once settled: rms %.0f (%.1f dBFS), AGC %d dB, suppression %d dB\n", settled, dbfs(settled), f.chain.gainDb(), f.chain.nsAttenDb());
    CHECK(dbfs(settled) < -30.0, "idle ADC noise stays under -30 dBFS after settling (%.1f dBFS)", dbfs(settled));
    CHECK(f.chain.gainDb() <= 36, "AGC never exceeds its 36 dB ceiling (%d dB)", f.chain.gainDb());
  }

  // ---- 2) Doppler chest: x(t) = breathing 4 mm @ 0.25 Hz + heart 0.3 mm pulses @ 72 bpm -------
  // 24 GHz: lambda = 12.5 mm, phase = 4*pi*x/lambda. IF = A*sin(phase + phi0).
  {
    Front f; Params p; p.preset = HEART; f.chain.configure(p);
    f.muteN = 600 * (FS / 1000);
    const double lam = 12.5, A = 500;                    // A counts = 0.4 V into a 12-bit ADC at ~2.5 V span
    std::vector<int16_t> out; std::vector<double> gains; long bumpN = 0;
    double beat = 60.0 / 72;
    for (int i = 0; i < FS * 90; i++) {
      double t = (double)i / FS, ph = fmod(t, beat);
      double heart = 0.0;
      if (ph < 0.07) heart += 0.3 * sin(M_PI * ph / 0.07);                      // S1 displacement pulse, mm
      double p2 = ph - 0.30; if (p2 >= 0 && p2 < 0.05) heart += 0.2 * sin(M_PI * p2 / 0.05);
      double x = 4.0 * sin(2 * M_PI * 0.25 * t) + heart;                        // mm
      double phi = 4 * M_PI * x / lam + 0.7;
      int v = 2700 + (int)lround(A * sin(phi) + 3 * gauss());
      out.push_back(f.push(v));
      if (i >= FS * 30 && f.chain.bumpActive()) bumpN++;
      if (i % (FS / 10) == 0) gains.push_back(f.chain.gainDb());
    }
    double duty = 100.0 * (double)bumpN / (double)(FS * 60);
    printf("      Doppler chest: bump gate active %.1f %% of the time\n", duty);
    CHECK(duty < 10.0, "the bump gate does not fire on normal breathing and heartbeat (%.1f %% duty)", duty);
    // gain stability over the last 60 s
    double mn = 99, mx = -99, mean = 0; size_t from = 30 * 10;
    for (size_t i = from; i < gains.size(); i++) { mn = std::min(mn, gains[i]); mx = std::max(mx, gains[i]); mean += gains[i]; }
    mean /= (double)(gains.size() - from);
    printf("      Doppler chest: AGC gain over the last 60 s min %.0f / mean %.1f / max %.0f dB\n", mn, mean, mx);
    CHECK(mx - mn <= 12.0, "AGC does not pump on a steady chest (spread %.0f dB)", mx - mn);
    double r = rms(out, FS * 30, FS * 90);
    CHECK(dbfs(r) > -45.0 && dbfs(r) < -3.0, "output level is usable: %.1f dBFS rms", dbfs(r));
    int clipped = 0; for (size_t i = FS * 30; i < out.size(); i++) if (abs((int)out[i]) >= 32767) clipped++;
    CHECK(clipped == 0, "output never hard-clips on a steady chest (%d samples)", clipped);
  }

  // ---- 2b) idle sensor, then it is put on a chest: no latch either way --------------------
  // A realistic chest is mostly below the detector's 3 Hz high-pass (breathing/heart motion is a ~1 Hz Doppler),
  // so this passes on both the old and the new detector; it is here to keep it that way.
  {
    for (int A : {60, 150, 500}) {
      Front f; Params p; p.preset = HEART; f.chain.configure(p);
      double beat = 60.0 / 72; long bumpN = 0; const int idle = 20, on = 40;
      std::vector<int16_t> out;
      for (int i = 0; i < FS * (idle + on); i++) {
        double t = (double)i / FS, ph = fmod(t, beat), amp = (t < idle) ? 0.0 : (double)A;
        double heart = 0.0;
        if (ph < 0.07) heart += 0.3 * sin(M_PI * ph / 0.07);
        double x = 4.0 * sin(2 * M_PI * 0.25 * t) + heart;
        int v = 2700 + (int)lround(amp * sin(4 * M_PI * x / 12.5 + 0.7) + 3 * gauss());
        out.push_back(f.push(v));
        if (t >= idle + 20 && f.chain.bumpActive()) bumpN++;
      }
      double duty = 100.0 * (double)bumpN / (double)(FS * 20);
      printf("      sensor placed on a chest after %d s idle, amplitude %d counts: bump gate active %.1f %% of seconds 20-40 after\n", idle, A, duty);
      CHECK(duty < 15.0, "no permanent bump latch after the level steps up (A=%d: %.1f %% duty)", A, duty);
    }
  }

  // ---- 3) ADC pinned at the rail for 2 s (MAX4466 saturated / cable knocked), then released ---
  {
    Front f; Params p; p.preset = HEART; f.chain.configure(p);
    std::vector<int16_t> out; std::vector<uint8_t> bump;
    for (int i = 0; i < FS * 16; i++) {
      int v = 2700 + (int)lround(3 * gauss());
      if (i >= FS * 4 && i < FS * 6) v = 4095;                                  // pinned for 2 s
      out.push_back(f.push(v)); bump.push_back(f.chain.bumpActive());
    }
    // find when the bump gate lets go after the rail is released
    size_t rel = FS * 6; size_t i = rel; while (i < bump.size() && bump[i]) i++;
    double ms = (double)(i - rel) * 1000.0 / FS;
    printf("      rail pinned 2 s: bump gate released %.0f ms after the rail let go\n", ms);
    // Regression guard for a real latch: before BUMP_MAX_FREEZE existed, the detector's background sank below the
    // ADC noise floor while the input was pinned, then re-triggered on plain noise and froze again: the gate
    // stayed on for 10 s+ (until the test ended). It now lets go within about a second.
    CHECK(ms < 2000.0, "the bump gate lets go within 2 s of the rail being released (%.0f ms)", ms);
    double r = rms(out, FS * 14, FS * 16);
    CHECK(dbfs(r) < -25.0, "the last two seconds are quiet again after the rail event (%.1f dBFS)", dbfs(r));
  }

  // ---- 4) settings churn: reconfigure 5x a second (a dragged slider) ------------------------
  {
    Front f; Params p; p.preset = HEART; f.chain.configure(p);
    std::vector<int16_t> out; int configs = 0;
    for (int i = 0; i < FS * 30; i++) {
      if (i % (FS / 5) == 0) { p.nsStrength = (uint8_t)(20 + (configs * 7) % 70); p.bumpSens = (uint8_t)(30 + (configs * 11) % 60); f.chain.configure(p); configs++; }
      double t = (double)i / FS, ph = fmod(t, 60.0 / 72);
      double v = (ph < 0.07 ? 700 * sin(2 * M_PI * 45 * ph) * sin(M_PI * ph / 0.07) : 0) + 20 * gauss();
      out.push_back(f.push(2700 + (int)lround(v)));
    }
    int pk = peak(out, FS * 2, out.size());
    double r = rms(out, FS * 2, out.size());
    printf("      %d reconfigures in 30 s: peak %d, rms %.0f\n", configs, pk, r);
    CHECK(pk < 30000, "no runaway transient from repeated configure() (peak %d)", pk);
  }

  // ---- 5) every preset x AGC on/off x extreme settings never produces out-of-range output ---
  {
    int bad = 0;
    for (int preset = 0; preset < NPRESETS; preset++)
      for (int agc = 0; agc < 2; agc++)
        for (int ns : {0, 50, 100})
          for (int bump : {0, 50, 100}) {
            Front f; Params p; p.preset = (uint8_t)preset; p.agc = agc; p.nsStrength = (uint8_t)ns; p.bumpSens = (uint8_t)bump; p.maxGainDb = 48; p.manualGainDb = 48;
            f.chain.configure(p);
            for (int i = 0; i < FS * 2; i++) {
              int v = 2700 + (int)lround(900 * gauss()) + ((i / 2000) & 1 ? 1200 : -1200);   // loud noise plus a square wave
              v = std::max(0, std::min(4095, v));
              int16_t o = f.push(v);
              if (o == INT16_MIN) bad++;
            }
          }
    CHECK(bad == 0, "no preset/setting combination produces INT16_MIN (a wrapped sample): %d", bad);
  }

  printf("\n%s\n", fails ? "SOME TESTS FAILED" : "ALL PASS");
  return fails ? 1 : 0;
}
