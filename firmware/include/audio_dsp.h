// Blip — Stetho audio chain that runs on the ESP32 (and natively in tests/).
// Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
// Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
//
// NOT A MEDICAL DEVICE. Hobby experiment in listening to chest-wall vibration
// with a CW Doppler radar module.
//
// Plain C++ (no Arduino), so the same file is compiled by PlatformIO and by
// tests/test_audio_dsp.cpp. Fixed-point throughout the per-sample path because
// the ESP32-C3 has no floating-point unit; floats are only used in configure().
//
//   in ──► burst blanker (high band above the preset's passband) ──┐
//    │                                                             │ blank gain
//    ├► detector HP 3 Hz ► bump detector (fast vs slow envelope)   │   duck (−12 dB, 60 ms)
//    │                     movement detector (fast vs 3 s reference): freeze AGC and noise floors
//    └► 4 ms look-ahead ► × blank ► HP ► peak EQ ► LP ► noise suppressor ► × duck ► AGC
//                                            ► 2 ms look-ahead peak limiter ► soft clip ► out
//
// A knock is handled by the limiter (fast, shallow, recovers in ~100 ms), not by a long deep mute, and while a
// knock or a big movement lasts the AGC and the noise floors keep their old values, so the heart is back at
// full level the moment the disturbance ends (before: −18 dB for 3 s after a knock, −29 dB after a movement).
//
// Samples: int32 "sample units", roughly ±32767 full scale. Feed it the ADC
// value with DC removed and shifted left by 3 (12-bit → ±16384, 6 dB headroom).
#pragma once
#include <stdint.h>
#include <math.h>
#include <string.h>

namespace blipdsp {

static const int FS = 8000;

// G.711 mu-law: 16-bit sample -> 8 bits, so audio to the phone takes half the
// Wi-Fi it would as int16 (telephone quality, ~13-bit dynamic range).
inline uint8_t mulaw(int16_t s) {
  const int BIAS = 0x84, CLIP = 32635;
  int sign = (s >> 8) & 0x80;
  int x = sign ? -(int)s : (int)s;
  if (x > CLIP) x = CLIP;
  x += BIAS;
  int exp = 7;
  for (int m = 0x4000; (x & m) == 0 && exp > 0; m >>= 1) exp--;
  int mant = (x >> (exp + 3)) & 0x0F;
  return (uint8_t)~(sign | (exp << 4) | mant);
}
inline int16_t mulawDecode(uint8_t u) {
  u = ~u;
  int t = (((u & 0x0F) << 3) + 0x84) << ((u & 0x70) >> 4);
  return (int16_t)((u & 0x80) ? (0x84 - t) : (t - 0x84));
}            // sample rate the chain is designed for
static const int LOOKAHEAD = 32;       // 4 ms: bumps are ducked from their leading edge
static const int NBANDS = 4;
static const int CTRL_EVERY = 8;       // gain maths at 1 kHz, envelopes at 8 kHz
static const int BUMP_MAX_FREEZE = FS * 600 / 1000;   // 0.6 s: longest the bump detector's background stays frozen
static const int BUMP_HOLD = FS * 60 / 1000;          // a bump flag lasts at least 60 ms (was 150)
static const int FREEZE_TAIL = FS * 300 / 1000;       // AGC / noise floors stay frozen this long after a bump or movement ends
static const int FREEZE_MAX = FS * 3;                 // ... and never longer than 3 s in a row: a louder scene is the new normal
static const int LIM_DELAY = 16;                      // 2 ms limiter look-ahead (power of two)
static const int32_t LIM_CEIL = 17000;                // limiter ceiling, about −5.7 dBFS; AGC aims its peaks at 11000
static const int NB_MAX = FS * 12 / 1000;             // a burst longer than 12 ms is not a burst: stop blanking...
static const int NB_COOL = FS * 150 / 1000;           // ... for 150 ms and let the reference catch up
static const int NB_TAIL = FS * 3 / 2000;             // keep blanking 1.5 ms after the burst
static const int NB_FLAG_LO = 22, NB_FLAG_HI = 30;    // flag history bits that gate the delayed sample (needs LOOKAHEAD >= 32)

// Oversampling: average of `os` (1, 2, 4 or 8) ADC conversions of one 8 kHz sample. For 4 and 8 the highest and lowest
// 1 or 2 are dropped first (a trimmed mean), so one conversion hit by a Wi-Fi burst does not reach the audio, and the
// rest is averaged down: white ADC noise falls by sqrt(kept conversions), and what is above 4 kHz is filtered out
// before it can fold back into the audio (the C3's ADC has no anti-alias filter of its own).
inline uint32_t osMean(const uint16_t* a, int os) {
  if (os <= 1) return a[0];
  if (os == 2) return ((uint32_t)a[0] + a[1] + 1) >> 1;
  uint16_t t[8];
  for (int i = 0; i < os; i++) { uint16_t v = a[i]; int j = i; while (j > 0 && t[j - 1] > v) { t[j] = t[j - 1]; j--; } t[j] = v; }
  int drop = os / 4, cnt = os - 2 * drop; uint32_t sum = 0;
  for (int i = drop; i < os - drop; i++) sum += t[i];
  return (sum + cnt / 2) / cnt;
}

// ---------------------------------------------------------------------------
// Biquad, direct form I, Q28 coefficients, output state with 8 extra bits so
// very low corner frequencies (3 Hz at 8 kHz) don't drown in rounding noise.
// ---------------------------------------------------------------------------
struct Biquad {
  int32_t b0 = 1 << 28, b1 = 0, b2 = 0, a1 = 0, a2 = 0;
  int32_t x1 = 0, x2 = 0, y1 = 0, y2 = 0;          // y in Q8
  int64_t err = 0;                                 // error feedback: the bits >>28 throws away
  bool on = false;

  void reset() { x1 = x2 = y1 = y2 = 0; err = 0; }
  void bypass() { on = false; reset(); }

  void setRaw(double B0, double B1, double B2, double A0, double A1, double A2) {
    const double s = (double)(1 << 28);
    b0 = (int32_t)lround(B0 / A0 * s); b1 = (int32_t)lround(B1 / A0 * s); b2 = (int32_t)lround(B2 / A0 * s);
    a1 = (int32_t)lround(A1 / A0 * s); a2 = (int32_t)lround(A2 / A0 * s);
    on = true; reset();
  }
  // RBJ audio-EQ cookbook designs
  void lowpass(double f, double q)  { double w = 2 * M_PI * f / FS, c = cos(w), al = sin(w) / (2 * q); setRaw((1 - c) / 2, 1 - c, (1 - c) / 2, 1 + al, -2 * c, 1 - al); }
  void highpass(double f, double q) { double w = 2 * M_PI * f / FS, c = cos(w), al = sin(w) / (2 * q); setRaw((1 + c) / 2, -(1 + c), (1 + c) / 2, 1 + al, -2 * c, 1 - al); }
  void bandpass(double f, double q) { double w = 2 * M_PI * f / FS, c = cos(w), al = sin(w) / (2 * q); setRaw(al, 0, -al, 1 + al, -2 * c, 1 - al); }
  void peaking(double f, double q, double db) {
    double A = pow(10.0, db / 40), w = 2 * M_PI * f / FS, c = cos(w), al = sin(w) / (2 * q);
    setRaw(1 + al * A, -2 * c, 1 - al * A, 1 + al / A, -2 * c, 1 - al / A);
  }

  inline int32_t run(int32_t x) {
    if (!on) return x;
    int64_t acc = ((int64_t)b0 * x + (int64_t)b1 * x1 + (int64_t)b2 * x2) << 8;
    acc -= (int64_t)a1 * y1 + (int64_t)a2 * y2;
    acc += err;                                       // without this a 3 Hz high-pass at 8 kHz
    int32_t y = (int32_t)(acc >> 28);                 // drifts hundreds of LSB off zero (Q8)
    err = acc - ((int64_t)y << 28);
    x2 = x1; x1 = x; y2 = y1; y1 = y;
    return y >> 8;
  }
};

// one-pole smoothing coefficient (Q16) for a time constant in seconds at rate hz
static inline int32_t coefQ16(double tau, double hz) {
  if (tau <= 0) return 65536;
  double k = 1.0 - exp(-1.0 / (tau * hz));
  int32_t q = (int32_t)lround(k * 65536.0);
  return q < 1 ? 1 : q;
}
// env += (x - env) * k, with separate up/down coefficients; values in Q8
static inline void follow(int32_t& env, int32_t x, int32_t kUp, int32_t kDown) {
  int32_t d = x - env;
  env += (int32_t)(((int64_t)d * (d > 0 ? kUp : kDown)) >> 16);
}
// Same, for a slow tracker kept in Q24 (x in Q8): a Q16 coefficient of 1..3 is too coarse to move a Q8 value by small amounts
static inline void followRef(int64_t& ref24, int32_t x, int32_t kUp, int32_t kDown) {
  int64_t d = ((int64_t)x << 16) - ref24;
  ref24 += (d * (d > 0 ? kUp : kDown)) >> 16;
}
static inline int32_t iabs(int32_t v) { return v < 0 ? -v : v; }

// ---------------------------------------------------------------------------
// Presets. Bands are where the noise suppressor listens; the EQ peak is a
// gentle lift for the thing you are trying to hear.
// ---------------------------------------------------------------------------
enum Preset : uint8_t { HEART = 0, LUNGS, VOICE, WIDE, RAW, NPRESETS };

struct PresetDef {
  const char* id;
  const char* label;
  float hp, lp;               // band limits
  float peakF, peakQ, peakDb; // 0 dB = no peak
  float bands[NBANDS];        // suppressor band centres
  bool ns, bump;              // suppressor and bump gate allowed
  float nbHz;                 // burst blanker listens above this; 0 = blanker off for the preset
};

static const PresetDef PRESETS[NPRESETS] = {
  // heart sounds S1/S2 sit at roughly 20–150 Hz
  {"heart", "Heart sounds",  15,  250,  45, 0.8f, 6, {25, 50, 95, 170},      true,  true, 1200},
  // breath sounds: broadband hiss, most energy 100–1000 Hz
  {"lungs", "Lungs / breath", 100, 1500, 400, 0.7f, 4, {150, 300, 600, 1100}, true,  true, 2200},
  // throat / larynx vibration while speaking: fundamental 85–255 Hz plus harmonics
  {"voice", "Larynx / voice", 70,  3000, 200, 0.7f, 4, {120, 250, 600, 1500}, true,  true, 0},
  // everything audible, suppression on
  {"wide",  "Wide",          15,  3400,   0, 1.0f, 0, {60, 200, 700, 2000},   true,  true, 0},
  // the Doppler audio as it comes, only AGC and the limiter
  {"raw",   "Raw Doppler",    3,  3600,   0, 1.0f, 0, {60, 200, 700, 2000},   false, false, 0},
};

struct Params {
  uint8_t preset = HEART;
  uint8_t nsStrength = 60;    // 0 = suppressor off .. 100 = aggressive
  uint8_t bumpSens = 50;      // 0 = bump gate off .. 100 = trigger on small knocks
  bool agc = true;
  bool blanker = true;        // drop short wideband bursts (Wi-Fi / supply glitches) before they reach the chain
  uint8_t maxGainDb = 36;     // AGC ceiling (0..48)
  uint8_t manualGainDb = 12;  // used when agc == false (0..48)
};

// ---------------------------------------------------------------------------
// The chain
// ---------------------------------------------------------------------------
class AudioChain {
 public:
  AudioChain() { configure(Params()); }

  void configure(const Params& p) {
    p_ = p;
    if (p_.preset >= NPRESETS) p_.preset = HEART;
    if (p_.maxGainDb > 48) p_.maxGainDb = 48;
    if (p_.manualGainDb > 48) p_.manualGainDb = 48;
    const PresetDef& d = PRESETS[p_.preset];

    det_.highpass(3, 0.707);
    hp_.highpass(d.hp, 0.707);
    lp_.lowpass(d.lp, 0.707);
    if (d.peakDb > 0) peak_.peaking(d.peakF, d.peakQ, d.peakDb); else peak_.bypass();
    for (int i = 0; i < NBANDS; i++) bp_[i].bandpass(d.bands[i], 1.2);

    nbOn_ = p_.blanker && d.nbHz > 0;
    if (nbOn_) hfd_.highpass(d.nbHz, 0.707); else hfd_.bypass();
    nsOn_ = d.ns && p_.nsStrength > 0;
    bumpOn_ = d.bump && p_.bumpSens > 0;
    // over-subtraction factor 0.5..2.5 (Q8) and the floor each band may be pushed down to
    overQ8_ = 128 + (int32_t)p_.nsStrength * 512 / 100;
    double floorDb = -6.0 - 0.18 * p_.nsStrength;               // -6 dB .. -24 dB
    gMinQ15_ = (int32_t)lround(pow(10.0, floorDb / 20) * 32768);
    // bump threshold: fast envelope this many times above the background of
    // typical peaks (Q4). sens 1 → 30x (30 dB), 50 → 9.5x (20 dB), 100 → 3x (10 dB)
    double k = 30.0 * pow(0.1, p_.bumpSens / 100.0);
    bumpKQ4_ = (int32_t)lround(k * 16);

    // envelopes
    kFastUp_ = coefQ16(0.0005, FS); kFastDn_ = coefQ16(0.010, FS);
    kSlowUp_ = coefQ16(0.3, FS); kSlowDn_ = coefQ16(3.0, FS);   // background = "typical peaks"
    kBandUp_ = coefQ16(0.004, FS);  kBandDn_ = coefQ16(0.040, FS);
    kNfDn_   = coefQ16(0.15, FS / CTRL_EVERY); kNfUp_ = coefQ16(6.0, FS / CTRL_EVERY);
    kGUp_    = coefQ16(0.003, FS / CTRL_EVERY); kGDn_ = coefQ16(0.030, FS / CTRL_EVERY);
    kPkUp_   = coefQ16(0.005, FS); kPkDn_ = coefQ16(1.0, FS); kPkDnFast_ = coefQ16(0.08, FS);
    kLtSlow_ = coefQ16(10.0, FS / CTRL_EVERY); kLtWarm_ = coefQ16(0.3, FS / CTRL_EVERY); kLtCatch_ = coefQ16(1.5, FS / CTRL_EVERY);
    duckLowQ15_ = (int32_t)lround(pow(10.0, -(4.0 + 0.14 * p_.bumpSens) / 20.0) * 32768);   // −5 dB (sens 10) .. −18 dB (sens 100)
    ltWarm_ = 3 * FS / CTRL_EVERY; ltLevel_ = 0; exc_ = false; excAge_ = 0;
    kAgcDn_  = coefQ16(0.10, FS / CTRL_EVERY); kAgcUp_ = coefQ16(1.2, FS / CTRL_EVERY);   // the limiter covers the first 100 ms
    kDuckDn_ = coefQ16(0.001, FS);  kDuckUp_ = coefQ16(0.025, FS);
    kLimAtk_ = coefQ16(0.00025, FS); kLimRel_ = coefQ16(0.040, FS);
    kHfUp_ = coefQ16(0.0002, FS); kHfDn_ = coefQ16(0.001, FS);
    kRefUp_ = coefQ16(0.5, FS); kRefDn_ = coefQ16(0.05, FS); kRefFast_ = coefQ16(0.02, FS);
    kNbAtkU_ = coefQ16(0.00015, FS); kNbAtk_ = coefQ16(0.0003, FS); kNbRel_ = coefQ16(0.001, FS);
    kMvUp_ = coefQ16(3.0, FS); kMvDn_ = coefQ16(6.0, FS);
    // movement: fast envelope this many times the 3 s reference (Q4). sens 50 → 6x (15.6 dB), 100 → 3.5x, 10 → 8x
    mvKQ4_ = (int32_t)lround((8.0 - 4.5 * p_.bumpSens / 100.0) * 16);

    maxGainQ8_ = (int32_t)lround(pow(10.0, p_.maxGainDb / 20.0) * 256);
    manGainQ8_ = (int32_t)lround(pow(10.0, p_.manualGainDb / 20.0) * 256);
    if (!p_.agc) gainQ8_ = manGainQ8_;
    else if (gainQ8_ <= 0 || gainQ8_ > maxGainQ8_) gainQ8_ = 256;
    primed_ = 0;
  }

  const Params& params() const { return p_; }

  // One sample in, one sample out (int16, ready for a DAC / the phone).
  inline int16_t process(int32_t in) {
    // --- burst blanker: wideband bursts (Wi-Fi beacons, supply glitches) show up in a band the preset
    //     does not use, so they can be found there and cut out of the band that is used ---------------
    int32_t inD = in;                                      // what the bump / movement detectors see
    bool blankNow = false;
    if (nbOn_) {
      int32_t hf = hfd_.run(in);
      follow(hfEnv_, iabs(hf) << 8, kHfUp_, kHfDn_);
      int32_t ref = (int32_t)(hfRef_ >> 16);
      bool burst = hfEnv_ > ref * NB_K + (NB_MIN << 8);
      if (nbCool_ > 0) { nbCool_--; burst = false; followRef(hfRef_, hfEnv_, kRefFast_, kRefDn_); }
      else if (burst) { nbHold_ = NB_TAIL; if (++nbRun_ > NB_MAX) { nbCool_ = NB_COOL; nbRun_ = 0; } }
      else { nbRun_ = 0; if (nbHold_ > 0) nbHold_--; followRef(hfRef_, hfEnv_, kRefUp_, kRefDn_); }
      blankNow = burst || nbHold_ > 0;
      flagHist_ = (flagHist_ << 1) | (blankNow ? 1u : 0u);
      follow(gU_, blankNow ? 0 : 32768, kNbRel_, kNbAtkU_);
      inD = (int32_t)(((int64_t)in * gU_) >> 15);
      // the delayed sample is blanked if a burst was flagged 2..10 samples after it: the gain is closed before the burst arrives
      uint64_t win = (flagHist_ >> NB_FLAG_LO) & ((1u << (NB_FLAG_HI - NB_FLAG_LO + 1)) - 1);
      follow(gD_, win ? 0 : 32768, kNbRel_, kNbAtk_);
    }

    // --- bump detector on the near-raw signal --------------------------------
    int32_t dx = det_.run(inD);
    int32_t a = iabs(dx) << 8;                             // Q8
    follow(fast_, a, kFastUp_, kFastDn_);
    bool clip = iabs(in) > 15800;                          // ADC near a rail = mechanical shock
    if (primed_ < FS / 2) { primed_++; follow(slow_, fast_, 2000, 2000); mvRef_ = (int64_t)fast_ << 16; }   // quick start-up
    bool trig = bumpOn_ && (clip || ((int64_t)fast_ * 16 > (int64_t)slow_ * bumpKQ4_ && fast_ > (12 << 8)));
    if (trig) hold_ = BUMP_HOLD;                           // re-arm hold
    if (hold_ > 0) { hold_--; bump_ = true; if (bumpAge_ < (1 << 30)) bumpAge_++; } else { bump_ = false; bumpAge_ = 0; }
    // Background frozen during a bump: a knock must not teach the detector that knocks are normal. But only
    // for BUMP_MAX_FREEZE: a "bump" that lasts longer than that is the new normal. Without this limit, a
    // background that had sunk below the ADC noise floor (input dead-flat for a few seconds: ADC pinned at
    // a rail, MAX4466 saturated or unplugged) re-triggered the gate on plain noise, which froze the
    // background again: the audio stayed ducked for good (tests/test_dsp_stability.cpp, scene 3).
    if (!bump_ || bumpAge_ > BUMP_MAX_FREEZE) follow(slow_, fast_, kSlowUp_, kSlowDn_);
    // Movement: a long loud stretch the 0.3 s "slow" background simply follows. A 3 s reference sees it.
    bool moving = bumpOn_ && primed_ >= FS / 2 && fast_ > (30 << 8) && (int64_t)fast_ * 16 > (mvRef_ >> 16) * mvKQ4_;
    if (!moving || mvAge_ > FREEZE_MAX) followRef(mvRef_, fast_, kMvUp_, kMvDn_);
    mvAge_ = moving ? (mvAge_ < (1 << 30) ? mvAge_ + 1 : mvAge_) : 0;
    // AGC level, AGC gain and the noise floors do not learn from a knock or a movement (and its ringing for 300 ms),
    // so the heart is back at its old level the moment it is over. At most 3 s in a row, then the new scene is normal.
    if (trig || moving) freeze_ = FREEZE_TAIL; else if (freeze_ > 0) freeze_--;
    if (freeze_ > 0) { if (freezeAge_ < (1 << 30)) freezeAge_++; } else freezeAge_ = 0;
    frozen_ = freeze_ > 0 && freezeAge_ <= FREEZE_MAX;
    follow(duck_, bump_ ? duckLowQ15_ : 32768, kDuckUp_, kDuckDn_);   // −5..−18 dB (the bump slider) while bumping, back in ~100 ms

    // --- look-ahead so the duck lands on the bump's leading edge -------------
    int32_t x = dl_[dlPos_]; dl_[dlPos_] = in; dlPos_ = (dlPos_ + 1) % LOOKAHEAD;
    if (nbOn_) x = (int32_t)(((int64_t)x * gD_) >> 15);

    // --- band limit + emphasis -------------------------------------------------
    x = lp_.run(peak_.run(hp_.run(x)));

    // --- noise suppressor: y = g_res·(x − Σbp) + Σ g_i·bp_i ---------------------
    int32_t y = x;
    if (nsOn_) {
      int32_t sum = 0, acc = 0, gmax = 0;
      for (int i = 0; i < NBANDS; i++) {
        int32_t b = bp_[i].run(x);
        follow(env_[i], iabs(b) << 8, kBandUp_, kBandDn_);
        sum += b;
        acc += (int32_t)(((int64_t)b * g_[i]) >> 15);
        if (g_[i] > gmax) gmax = g_[i];
      }
      y = (int32_t)(((int64_t)(x - sum) * gmax) >> 15) + acc;
    }

    // --- control rate: noise floors, band gains, AGC -----------------------------
    if (++ctrl_ >= CTRL_EVERY) { ctrl_ = 0; control(); }

    // --- duck, gain ------------------------------------------------------------
    y = (int32_t)(((int64_t)y * duck_) >> 15);
    if (!frozen_) {
      follow(level_, iabs(y) << 8, kPkUp_, exc_ ? kPkDnFast_ : kPkDn_);   // peak-ish level: heart sounds are spiky, but an excursion lets go fast
      if (!exc_) follow(noiseLvl_, level_, kNfUp8k(), kNfDn8k());         // slow minimum of the smoothed level
    }
    y = (int32_t)(((int64_t)y * gainQ8_) >> 8);

    // --- peak limiter with 2 ms look-ahead: a knock is squeezed to the ceiling, not muted -------------
    int32_t m = iabs(y);
    int32_t tg = m > LIM_CEIL ? (int32_t)(((int64_t)LIM_CEIL << 15) / m) : 32768;
    follow(limG_, tg, kLimRel_, kLimAtk_);                 // falling = attack, rising = release
    int32_t yd = ld_[ldPos_]; ld_[ldPos_] = y; ldPos_ = (ldPos_ + 1) & (LIM_DELAY - 1);
    y = (int32_t)(((int64_t)yd * limG_) >> 15);
    m = iabs(y);
    if (m > 24000) { m = 24000 + ((m - 24000) >> 2); if (m > 32767) { m = 32767; clipped_ = true; } y = y < 0 ? -m : m; }
    return (int16_t)y;
  }

  // telemetry for the phone / OLED
  int32_t dbgFast() const { return fast_ >> 8; }
  int32_t dbgSlow() const { return slow_ >> 8; }
  bool bumpActive() const { return bump_; }
  bool frozen() const { return frozen_ || exc_; }                 // AGC / noise floors held (knock or movement in progress)
  bool blanking() const { return nbOn_ && (flagHist_ & 1); }
  int limDb() const { return (int)lround(20.0 * log10((limG_ + 1) / 32768.0)); }   // not per-sample
  bool clippedAndClear() { bool c = clipped_; clipped_ = false; return c; }
  int gainDb() const { return gainQ8_ <= 0 ? -99 : (int)lround(20.0 * log10(gainQ8_ / 256.0)); }   // not per-sample
  // average suppression across bands in dB (0 = nothing removed)
  int nsAttenDb() const {
    if (!nsOn_) return 0;
    double s = 0; for (int i = 0; i < NBANDS; i++) s += g_[i];
    return (int)lround(20.0 * log10((s / NBANDS) / 32768.0 + 1e-6));
  }

 private:
  Params p_;
  Biquad det_, hfd_, hp_, peak_, lp_, bp_[NBANDS];
  bool nsOn_ = false, bumpOn_ = false, nbOn_ = false;
  int32_t duckLowQ15_ = 8231;
  static const int32_t EXC_ON = 35, EXC_OFF = 25;          // excursion: level 3.5x the 10 s typical level (off again at 2.5x), x10
  int32_t kPkDnFast_ = 1, kLtSlow_ = 1, kLtWarm_ = 1, kLtCatch_ = 1, ltWarm_ = 0, excAge_ = 0; int64_t ltLevel_ = 0; bool exc_ = false;
  static const int32_t NB_K = 5;                           // burst = high-band envelope 5x its typical level ...
  static const int32_t NB_MIN = 24;                        // ... and above this many sample units
  int32_t kLimAtk_ = 1, kLimRel_ = 1, kHfUp_ = 1, kHfDn_ = 1, kRefUp_ = 1, kRefDn_ = 1, kRefFast_ = 1, kNbAtkU_ = 1, kNbAtk_ = 1, kNbRel_ = 1, kMvUp_ = 1, kMvDn_ = 1, mvKQ4_ = 96;
  int32_t hfEnv_ = 0, gU_ = 32768, gD_ = 32768, nbRun_ = 0, nbHold_ = 0, nbCool_ = 0;
  int64_t hfRef_ = 0, mvRef_ = 0;                          // Q24: slow trackers need the extra bits
  uint64_t flagHist_ = 0;
  int32_t mvAge_ = 0, freeze_ = 0, freezeAge_ = 0, limG_ = 32768; bool frozen_ = false;
  int32_t ld_[LIM_DELAY] = {0}; int ldPos_ = 0;
  int32_t overQ8_ = 256, gMinQ15_ = 4096, bumpKQ4_ = 160;
  int32_t kFastUp_, kFastDn_, kSlowUp_, kSlowDn_, kBandUp_, kBandDn_, kNfDn_, kNfUp_, kGUp_, kGDn_, kPkUp_, kPkDn_, kAgcDn_, kAgcUp_, kDuckDn_, kDuckUp_;
  int32_t fast_ = 0, slow_ = 0, duck_ = 32768;
  int32_t hold_ = 0, bumpAge_ = 0; bool bump_ = false; bool clipped_ = false; int32_t primed_ = 0;
  int32_t dl_[LOOKAHEAD] = {0}; int dlPos_ = 0;
  int32_t env_[NBANDS] = {0}, nf_[NBANDS] = {0}, g_[NBANDS] = {32768, 32768, 32768, 32768};
  int ctrl_ = 0;
  int32_t level_ = 0, noiseLvl_ = 0;
  int32_t gainQ8_ = 256, maxGainQ8_ = 16384, manGainQ8_ = 1024;

  // wideband noise-floor coefficients at the full sample rate
  int32_t kNfUp8k() const { return 1; }                    // ~8 s rise at 8 kHz (Q16 = 1 is the slowest)
  int32_t kNfDn8k() const { return 54; }                   // ~0.15 s fall

  void control() {
    // Excursion = the (peak-ish) level is far above its own 10 s typical level: a knock, a movement, a hand on the sensor.
    // The AGC holds its gain through it (the limiter covers the loudness) for up to 3 s, so the heart is back at full
    // level the moment it is over instead of seconds later. Undetected by the bump / movement detectors or not.
    if (ltLevel_ == 0 && level_ > 0) ltLevel_ = (int64_t)level_ << 16;
    if (ltWarm_ > 0) { ltWarm_--; exc_ = false; excAge_ = 0; followRef(ltLevel_, level_, kLtWarm_, kLtWarm_); }
    else {
      int64_t lt = ltLevel_ >> 16;
      exc_ = lt > 0 && (int64_t)level_ * 10 > lt * (exc_ ? EXC_OFF : EXC_ON);
      if (exc_) { if (excAge_ < (1 << 30)) excAge_++; } else excAge_ = 0;
      if (!exc_) followRef(ltLevel_, level_, kLtSlow_, kLtSlow_);
      else if (excAge_ > FREEZE_MAX / CTRL_EVERY) followRef(ltLevel_, level_, kLtCatch_, kLtCatch_);   // lasted > 3 s: the new normal
    }
    const bool hold = frozen_ || (exc_ && excAge_ < FREEZE_MAX / CTRL_EVERY);
    if (nsOn_) {
      for (int i = 0; i < NBANDS; i++) {
        int32_t e = env_[i];
        if (!frozen_ && !exc_) {
          if (nf_[i] == 0) nf_[i] = e;
          // minimum tracking: fall fast to quieter stretches, rise slowly
          follow(nf_[i], e, kNfUp_, kNfDn_);
        }
        // Wiener-ish: g = 1 − over·noise/env, clamped to [gMin, 1]
        int32_t gt;
        if (e <= 0) gt = gMinQ15_;
        else {
          int64_t r = ((int64_t)nf_[i] * overQ8_ << 7) / e;   // Q15 of over·nf/env
          gt = 32768 - (int32_t)(r > 32768 ? 32768 : r);
          if (gt < gMinQ15_) gt = gMinQ15_;
        }
        follow(g_[i], gt, kGUp_, kGDn_);
      }
    }
    if (p_.agc) {
      if (!hold && level_ > 0) {
        // aim the peaks at ~ -9 dBFS ...
        int64_t want = ((int64_t)11000 << 16) / level_;     // Q8 (level is Q8)
        // ... but never lift the noise floor (its peaks) above ~ -24 dBFS
        if (noiseLvl_ > 0) { int64_t cap = ((int64_t)2000 << 16) / noiseLvl_; if (want > cap) want = cap; }
        if (want > maxGainQ8_) want = maxGainQ8_;
        if (want < 64) want = 64;                            // -12 dB floor
        follow(gainQ8_, (int32_t)want, kAgcUp_, kAgcDn_);
        if (gainQ8_ < 1) gainQ8_ = 1;
      }
    } else {
      gainQ8_ = manGainQ8_;
    }
  }
};

// ---------------------------------------------------------------------------
// Vitals path: boxcar-decimate the DC-removed input 80:1 → 100 Hz for the
// phone's waveform, heart-rate and breathing estimates.
// ---------------------------------------------------------------------------
class Decimator {
 public:
  static const int RATIO = 80;
  // returns true when a 100 Hz sample is ready in out
  bool push(int32_t v, int16_t& out) {
    acc_ += v;
    if (++n_ < RATIO) return false;
    int32_t s = acc_ / RATIO;
    acc_ = 0; n_ = 0;
    out = (int16_t)(s > 32767 ? 32767 : s < -32768 ? -32768 : s);
    return true;
  }
 private:
  int32_t acc_ = 0; int n_ = 0;
};

}  // namespace blipdsp
