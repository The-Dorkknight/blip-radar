// Synthetic Stetho scenes for the host tests (not firmware). Sample units: 1 ADC LSB = 8 units.
// Heart = S1/S2 bursts, noise = ADC/Doppler hiss, plus the things that go wrong on the bench:
// Wi-Fi-beacon-like bursts, knocks, and big body movements (Doppler fringes that sweep up and down, clipped like the MAX4466).
// Components are kept apart so a test can measure what the chain does to the heart separately from the rest.
// Synthetic data only: it proves the maths and the dynamics, not that a real chest sounds like this.
//
// Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
// Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
#pragma once
#include <vector>
#include <cmath>
#include <cstdint>
struct Rng { uint32_t s = 12345; double u() { s = s * 1664525u + 1013904223u; return (s >> 8) / 16777216.0; } double g() { double a = 0; for (int i = 0; i < 6; i++) a += u(); return (a - 3.0) * 1.41421356; } };
struct Scene {
  int N; double fs = 8000; std::vector<double> heart, noise, extra;   // components kept apart so gains can be measured
  std::vector<int> s1;                                               // sample index of each S1
  Scene(int n) : N(n), heart(n, 0), noise(n, 0), extra(n, 0) {}
  void addHeart(double bpm, double peakLSB, double jitter = 0.0, Rng* r = nullptr) {
    double per = 60.0 / bpm * fs; double t = 0.3 * fs;
    while (t < N) {
      int i0 = (int)t; s1.push_back(i0);
      for (int k = 0; k < (int)(0.09 * fs) && i0 + k < N; k++) { double tt = k / fs; heart[i0 + k] += peakLSB * 8 * exp(-tt / 0.022) * sin(2 * M_PI * 48 * tt); }
      int i1 = i0 + (int)(0.30 * fs);                                   // S2 follows 300 ms later, a bit quieter and higher
      for (int k = 0; k < (int)(0.07 * fs) && i1 + k < N; k++) { double tt = k / fs; heart[i1 + k] += 0.7 * peakLSB * 8 * exp(-tt / 0.016) * sin(2 * M_PI * 68 * tt); }
      t += per * (1.0 + (r ? jitter * (r->u() - 0.5) : 0));
    }
  }
  void addNoise(double rmsLSB, Rng& r) { for (int i = 0; i < N; i++) noise[i] += r.g() * rmsLSB * 8; }
  // Wi-Fi-beacon-like: every periodMs a burst of wideband noise lasting durMs, amplitude relative LSB rms
  void addBursts(double periodMs, double durMs, double rmsLSB, Rng& r, double startMs = 50) {
    for (double t = startMs; t < N / fs * 1000; t += periodMs) { int i0 = (int)(t * fs / 1000), n = (int)(durMs * fs / 1000);
      for (int k = 0; k < n && i0 + k < N; k++) { double w = sin(M_PI * (k + 0.5) / n); extra[i0 + k] += r.g() * rmsLSB * 8 * w; } }
  }
  // knock: damped low-frequency thump plus a broadband click
  void addKnock(double tMs, double peakLSB, Rng& r, double f = 70, double tau = 0.03) {
    int i0 = (int)(tMs * fs / 1000);
    for (int k = 0; k < (int)(0.3 * fs) && i0 + k < N; k++) { double tt = k / fs; extra[i0 + k] += peakLSB * 8 * exp(-tt / tau) * sin(2 * M_PI * f * tt) + (k < 40 ? r.g() * peakLSB * 3 : 0); }
  }
  // big body movement: Doppler fringes (frequency sweep up and down), amplitude clipped like the MAX4466 would
  void addMove(double tMs, double durMs, double peakLSB, double fmax = 160) {
    int i0 = (int)(tMs * fs / 1000), n = (int)(durMs * fs / 1000); double ph = 0;
    for (int k = 0; k < n && i0 + k < N; k++) { double x = (double)k / n; double f = fmax * sin(M_PI * x); ph += 2 * M_PI * f / fs; double env = sin(M_PI * x);
      extra[i0 + k] += peakLSB * 8 * (0.4 + 0.6 * env) * sin(ph); }
  }
  int32_t at(int i, double railUnits = 15900) const { double v = heart[i] + noise[i] + extra[i]; if (v > railUnits) v = railUnits; if (v < -railUnits) v = -railUnits; return (int32_t)lround(v); }
};
