// What does one second of Stetho audio cost the ESP32-C3's CPU core?
// Compiled for RV32IMC with the same compiler PlatformIO uses for the C3, run in an emulator (Unicorn)
// and counted instruction by instruction. This is the per-sample path of Stetho::taskLoop():
// DC tracker, 80:1 vitals decimator, the audio chain, mu-law, packet byte, plus the once-per-block
// and once-per-packet telemetry (gainDb()/nsAttenDb() use double log10, in software on a chip with no FPU).
// The host (run.py) writes the settings into memory at CFG and the test input is made on-chip by an LCG.
#include <stdint.h>
#include <sys/reent.h>
#include "audio_dsp.h"
using namespace blipdsp;
extern "C" {
void __attribute__((noinline)) mark_begin() { asm volatile(""); }
void __attribute__((noinline)) mark_end() { asm volatile(""); }
struct _reent* __getreent(void) { static char r[2048]; return (struct _reent*)r; }   // newlib wants one for errno
}
volatile int32_t sink;
static uint32_t rng = 1;
static inline int32_t noise(int amp) { rng = rng * 1664525u + 1013904223u; return (int32_t)((rng >> 16) & 0xffff) % (2 * amp + 1) - amp; }

struct Path {
  AudioChain chain; Decimator dec; int32_t dc = 2048 << 14; uint8_t pkt[256]; int n = 0; int blk = 0;
  inline void sample(int32_t v) {
    dc += ((v << 14) - dc) >> 14;
    int32_t s = (v - (dc >> 14)) << 3;
    int16_t vs; if (dec.push(s, vs)) sink = vs;
    int16_t o = chain.process(s);
    pkt[n] = mulaw(o);
    if (++n == 256) { n = 0; sink = chain.gainDb() + chain.nsAttenDb(); chain.clippedAndClear(); }   // pushAudio(): per 32 ms packet
    sink = o;
    if (++blk == 64) { blk = 0; sink = chain.gainDb() + chain.nsAttenDb() + chain.bumpActive(); }     // taskLoop(): per 8 ms block
  }
};

extern "C" int main() {
  Path path;
  volatile uint32_t* cfg = (volatile uint32_t*)0x80300000;     // preset, ns, bump, agc, N
  Params p; p.preset = (uint8_t)cfg[0]; p.nsStrength = (uint8_t)cfg[1]; p.bumpSens = (uint8_t)cfg[2]; p.agc = cfg[3] != 0;
  path.chain.configure(p);
  int N = (int)cfg[4];
  for (int i = 0; i < N; i++) path.sample(2700 + noise(120) + ((i % 3000) < 40 ? (((i / 40) & 1) ? 300 : -300) : 0));   // warm-up, not counted
  mark_begin();
  for (int i = 0; i < N; i++) path.sample(2700 + noise(120) + ((i % 3000) < 40 ? (((i / 40) & 1) ? 300 : -300) : 0));
  mark_end();
  return 0;
}
