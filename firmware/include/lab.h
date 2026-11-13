// Blip — "Lab" switches: turn parts of the node on and off WHILE IT RUNS, so one
// flash can answer "which part is making Stetho freeze?" instead of one flash per
// guess. Driven over HTTP (see tools/soak_test.py, or just type the URL):
//
//   http://192.168.4.1/api/lab?pace=1&dsp=1     set some switches
//   http://192.168.4.1/api/lab?reset=1          back to the shipped behaviour
//   http://192.168.4.1/api/lab                  show the current switches
//
// Every switch defaults to 0 (= exactly the shipped behaviour) and is held in RAM
// only: a reboot, crash included, puts everything back to the defaults, so a
// switch combination that crashes the node can never leave it in a boot loop.
//
// Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
// Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
#pragma once
#include <stdint.h>

namespace lab {

struct Flags {
  // loop() pacing. 0 = free-running (shipped: loop() never sleeps), 1 = delay(1) at the
  // end of every pass (what the bench test does), 2 = delay(10).
  volatile uint8_t pace = 0;
  // Audio chain. 0 = full chain (shipped), 1 = chain bypassed (DC-removed ADC straight
  // to mu-law), 2 = silence. Isolates "is it the DSP?".
  volatile uint8_t dsp = 0;
  // Audio to the phone. 0 = shipped (guarded: only when every phone's queue has room),
  // 1 = drained and thrown away (nothing audio goes out), 2 = unguarded binaryAll() on
  // every packet (the earlier latency rework). Isolates "is it the WebSocket send?".
  volatile uint8_t send = 0;
  // Text pushes. bit0 = no target pushes, bit1 = no status pushes.
  volatile uint8_t text = 0;
  // Sample source. 0 = ADC DMA (shipped), 1 = synthetic 8 kHz source paced by the RTOS:
  // the ADC driver is never touched. Isolates "is it the ADC driver?". Needs a
  // Stetho restart (done for you).
  volatile uint8_t src = 0;
  // Priority of the audio task (default 5; loopTask is 1, async_tcp 10, lwIP 18).
  // Needs a Stetho restart (done for you).
  volatile uint8_t prio = 5;
  // 1 = no Serial output at all (the log ring and /api/log still work).
  volatile uint8_t quiet = 0;
  // Skip parts of loop(). bit0 = radar UART, bit1 = OLED, bit2 = DNS server.
  volatile uint8_t skip = 0;
  // ADC oversampling. 0/1 = 8 kHz, as shipped. 2 = 16 kHz, 4 (or 3) = 32 kHz, 8 (5..8) = 64 kHz: every 8 kHz sample is
  // then the average of 2 / 4 / 8 ADC conversions (with the highest and lowest dropped for 4 and 8, so a short burst
  // of Wi-Fi noise on one conversion is thrown away). Lower noise, no aliasing of what is above 4 kHz. Needs a Stetho restart (done for you).
  volatile uint8_t os = 0;
  // 1 = burst blanker off (default 0 = on). Live.
  volatile uint8_t nb = 0;
};


inline Flags f;

// 1, 2, 4 or 8 conversions per 8 kHz sample
inline int osFactor() { uint8_t v = f.os; return v <= 1 ? 1 : v == 2 ? 2 : v <= 4 ? 4 : 8; }

}  // namespace lab
