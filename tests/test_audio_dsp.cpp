// Native test for firmware/include/audio_dsp.h
//   g++ -std=c++17 -O2 -I firmware/include tests/test_audio_dsp.cpp -o /tmp/t && /tmp/t [outdir]
// Builds a synthetic "radar stethoscope" signal at 8 kHz — heart-sound bursts,
// background noise, and big knocks ("bumps") — runs it through the chain and
// checks that knocks are pushed down far more than heart sounds, that the
// noise between beats is reduced, that the AGC settles, and that nothing
// overflows. With an outdir it also writes before/after WAV files.
// Synthetic data only: this proves the maths, not that a real chest sounds like this.
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <vector>
#include <string>
#include "audio_dsp.h"

using namespace blipdsp;
static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("PASS  "); printf(__VA_ARGS__); printf("\n"); } else { printf("FAIL  "); printf(__VA_ARGS__); printf("\n"); fails++; } } while (0)

static uint32_t rng = 12345;
static double frand() { rng = rng * 1664525u + 1013904223u; return ((rng >> 8) / 16777216.0) * 2 - 1; }

struct Scene {
  std::vector<int32_t> x;          // input, sample units
  std::vector<uint8_t> kind;       // 0 noise, 1 heart sound, 2 bump
};

// 20 s: heart at 72 bpm (S1 45 Hz 70 ms, S2 70 Hz 50 ms 0.3 s later),
// white-ish noise, a knock every 3.3 s that is ~25 dB louder than S1.
static Scene makeScene(double secs) {
  Scene s; int n = (int)(secs * FS); s.x.resize(n); s.kind.assign(n, 0);
  double beat = 60.0 / 72;
  for (int i = 0; i < n; i++) {
    double t = (double)i / FS, v = 0;
    double ph = fmod(t, beat);
    if (ph < 0.07) { v += 900 * sin(2 * M_PI * 45 * ph) * sin(M_PI * ph / 0.07); s.kind[i] = 1; }
    double p2 = ph - 0.30;
    if (p2 >= 0 && p2 < 0.05) { v += 600 * sin(2 * M_PI * 70 * p2) * sin(M_PI * p2 / 0.05); s.kind[i] = 1; }
    double pb = fmod(t + 1.1, 3.3);
    if (pb < 0.06) { v += 14000 * exp(-pb / 0.012) * (frand() * 0.7 + 0.3 * sin(2 * M_PI * 30 * pb)); s.kind[i] = 2; }
    v += 120 * frand();
    s.x[i] = (int32_t)lround(v);
  }
  return s;
}

static void writeWav(const std::string& path, const std::vector<int16_t>& d) {
  FILE* f = fopen(path.c_str(), "wb"); if (!f) return;
  uint32_t n = d.size() * 2, sr = FS, br = FS * 2; uint16_t ch = 1, bits = 16, align = 2, fmt = 1; uint32_t sz = 36 + n, fl = 16;
  fwrite("RIFF", 1, 4, f); fwrite(&sz, 4, 1, f); fwrite("WAVEfmt ", 1, 8, f); fwrite(&fl, 4, 1, f);
  fwrite(&fmt, 2, 1, f); fwrite(&ch, 2, 1, f); fwrite(&sr, 4, 1, f); fwrite(&br, 4, 1, f); fwrite(&align, 2, 1, f); fwrite(&bits, 2, 1, f);
  fwrite("data", 1, 4, f); fwrite(&n, 4, 1, f); fwrite(d.data(), 2, d.size(), f); fclose(f);
}

int main(int argc, char** argv) {
  Scene sc = makeScene(20.0);
  const int n = sc.x.size();

  // ---- 1) full chain, heart preset -------------------------------------------
  AudioChain ch; Params p; p.preset = HEART; ch.configure(p);
  std::vector<int16_t> out(n), in16(n);
  int bumpSamples = 0;
  for (int i = 0; i < n; i++) {
    int32_t v = sc.x[i]; in16[i] = (int16_t)std::max(-32768, std::min(32767, v));
    out[i] = ch.process(v);
    if (ch.bumpActive()) bumpSamples++;
  }
  // energies by kind, last 10 s (after the AGC has settled), output aligned for the 4 ms look-ahead
  double eIn[3] = {0}, eOut[3] = {0}; long cnt[3] = {0};
  for (int i = n / 2; i < n - LOOKAHEAD; i++) {
    int k = sc.kind[i]; double a = sc.x[i], b = out[i + LOOKAHEAD];
    eIn[k] += a * a; eOut[k] += b * b; cnt[k]++;
  }
  auto db = [](double e, long c) { return 10 * log10(e / (c ? c : 1) + 1e-9); };
  double gNoise = db(eOut[0], cnt[0]) - db(eIn[0], cnt[0]);
  double gHeart = db(eOut[1], cnt[1]) - db(eIn[1], cnt[1]);
  double gBump  = db(eOut[2], cnt[2]) - db(eIn[2], cnt[2]);
  printf("gain through chain:  heart %+.1f dB   noise %+.1f dB   bumps %+.1f dB   (AGC %d dB, NS %d dB)\n",
         gHeart, gNoise, gBump, ch.gainDb(), ch.nsAttenDb());
  CHECK(gHeart - gBump > 20, "bumps pushed down >20 dB relative to heart sounds (%.1f dB)", gHeart - gBump);
  CHECK(gHeart - gNoise > 6, "noise between beats reduced >6 dB relative to heart sounds (%.1f dB)", gHeart - gNoise);
  CHECK(bumpSamples > 0 && bumpSamples < n / 4, "bump gate active only part of the time (%.1f%%)", 100.0 * bumpSamples / n);

  // heart-sound bursts are not gated: no bump flag inside a beat away from knocks
  {
    AudioChain c2; c2.configure(p); int falseTrig = 0, beats = 0;
    for (int i = 0; i < n; i++) {
      int32_t v = sc.x[i];
      if (sc.kind[i] == 2) v = (int32_t)lround(120 * frand());       // same scene, knocks removed
      c2.process(v);
      if (i > FS && sc.kind[i] == 1 && (i == 0 || sc.kind[i - 1] != 1)) beats++;
      if (i > FS && c2.bumpActive()) falseTrig++;
    }
    CHECK(falseTrig == 0, "no bump triggers on heart sounds alone (%d samples flagged over %d bursts)", falseTrig, beats);
  }

  // output level sensible, nothing pinned at the rails
  double peak = 0, rms = 0; for (int i = n / 2; i < n; i++) { peak = std::max(peak, (double)abs(out[i])); rms += (double)out[i] * out[i]; }
  rms = sqrt(rms / (n / 2));
  CHECK(peak < 32767 && !ch.clippedAndClear(), "no hard clipping in the output (peak %.0f)", peak);
  CHECK(rms > 300 && rms < 12000, "AGC lands the level in a sane window (rms %.0f)", rms);

  // ---- 2) raw preset is a clean pass-through (+ fixed gain) --------------------
  {
    AudioChain c3; Params q; q.preset = RAW; q.agc = false; q.manualGainDb = 0; c3.configure(q);
    // project the output onto a 440 Hz sine/cosine: whatever is left over is distortion/noise
    double sI = 0, sQ = 0, tot = 0; int m = 0;
    for (int i = 0; i < FS * 2; i++) {
      double w = 2 * M_PI * 440 * i / (double)FS;
      int16_t o = c3.process((int32_t)lround(3000 * sin(w)));
      if (i >= FS) { sI += o * sin(w); sQ += o * cos(w); tot += (double)o * o; m++; }
    }
    double amp = 2 * sqrt(sI * sI + sQ * sQ) / m, fit = amp * amp / 2, resid = tot / m - fit;
    double snr = 10 * log10(fit / (resid > 1e-9 ? resid : 1e-9));
    CHECK(fabs(20 * log10(amp / 3000)) < 1.0 && snr > 40, "raw preset passes a 440 Hz tone cleanly (gain %+.2f dB, %.1f dB SNR)", 20 * log10(amp / 3000), snr);
  }

  // ---- 3) every preset runs, settles, no overflow on a nasty input -------------
  for (int pr = 0; pr < NPRESETS; pr++) {
    AudioChain c4; Params q; q.preset = pr; q.nsStrength = 100; q.bumpSens = 100; q.maxGainDb = 48; c4.configure(q);
    bool bad = false;
    for (int i = 0; i < FS * 3; i++) {
      int32_t v = (i % 977 == 0) ? 16383 : (int32_t)lround(16000 * frand());
      int16_t o = c4.process(v); if (o == -32768) bad = true;
    }
    CHECK(!bad, "preset %-6s survives full-scale noise and impulses", PRESETS[pr].id);
  }

  // ---- 4) decimator ------------------------------------------------------------
  { Decimator d; int16_t o; int got = 0; long s = 0; for (int i = 0; i < 800; i++) if (d.push(1000, o)) { got++; s += o; }
    CHECK(got == 10 && s == 10000, "decimator gives 10 samples of 1000 from 800 inputs (%d, %ld)", got, s); }

  // ---- 5) mu-law (audio to the phone) ----------------------------------------------
  { int worst = 0; bool mono = true; int prev = -40000;
    for (int v = -32768; v <= 32767; v += 7) {
      int r = mulawDecode(mulaw((int16_t)v)), e = abs(r - v), lim = abs(v) / 16 + 8;
      if (abs(v) <= 32635 && e > lim) worst = e;
      if (r < prev) mono = false;
      prev = r;
    }
    CHECK(worst == 0, "mu-law round trip within ~6%% (+8 LSB) across the range");
    CHECK(mono, "mu-law decode is monotonic");
    CHECK(mulaw(0) == 0xFF && mulaw(32767) == 0x80 && mulaw(-32768) == 0x00, "mu-law matches G.711 codes (0 -> FF, +max -> 80, -max -> 00)");
    FILE* f = argc > 2 ? fopen(argv[2], "w") : nullptr;   // reference codes for the simulator's Python copy
    if (f) { for (int v = -32768; v <= 32767; v += 97) fprintf(f, "%d %d\n", v, mulaw((int16_t)v)); fclose(f); }
  }

  if (argc > 1) {
    std::string dir = argv[1];
    writeWav(dir + "/dsp_before.wav", in16);
    writeWav(dir + "/dsp_after.wav", out);
    FILE* f = fopen((dir + "/dsp_trace.csv").c_str(), "w");
    if (f) { fprintf(f, "t,in,out,kind\n"); for (int i = 0; i < n - LOOKAHEAD; i += 4) fprintf(f, "%.4f,%d,%d,%d\n", i / (double)FS, sc.x[i], out[i + LOOKAHEAD], sc.kind[i]); fclose(f); }
    printf("wrote %s/dsp_before.wav, dsp_after.wav, dsp_trace.csv\n", dir.c_str());
  }
  printf(fails ? "\n%d FAILED\n" : "\nALL PASS\n", fails);
  return fails ? 1 : 0;
}
