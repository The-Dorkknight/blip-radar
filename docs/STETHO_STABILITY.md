# Stetho stability — what is verified, what is not, and how to find the rest

*Blip 0.2.2-wip. Written after a fresh review of the code, not from the earlier notes.*

## The symptom
On an ESP32-C3 (single core), 4–9 s after Stetho starts and a client is connected, `async_tcp` stops checking in with the task watchdog (5 s) and the board resets.

## Verified (measured or tested, not argued)
| Claim | How it was checked |
|---|---|
| The audio DSP does not starve the CPU | `tests/rv32_cost/run.py`: the chain is compiled for RV32IMC and run in an emulator with every instruction counted. About 1370 instr/sample = 10.9 M instr/s = **6.8 % of the core** (10 % at 1.5 cycles/instr). A starved core needs ~100 %. |
| The ADC mutex bug (opened by one task, closed by another) was real and is fixed | Earlier decoded crash log (`xTaskPriorityDisinherit`). Not the `async_tcp` freeze. |
| The bump gate could latch for seconds | `tests/test_dsp_stability.cpp` measured 10 s; now capped, release ≤ 750 ms. |
| DSP has no overflow / UB on hostile input | Same test under UBSan + ASan (full-scale, DC steps, square waves, silence, noise). |
| Status JSON could underflow its length | Fixed with a clamped appender; 2 KB buffer. |

## Refuted (by reading the pinned library source)
- Priority inversion on AsyncTCP / ESPAsyncWebServer locks (they are not the mutex type that inherits).
- A client being kicked when its WebSocket queue is full (the library drops the message instead).

## Still unknown
Why `async_tcp` goes quiet. Suspects, in rough order:
1. `loop()` is **free-running** (never sleeps) while the bench build, which does not freeze, sleeps 1 ms per pass.
2. Unguarded text pushes (targets/status) into the WebSocket.
3. Radar UART, OLED I²C, DNS server, USB-CDC logging.
4. NVS writes.
5. This particular board or its radio (the bench test exists to check that).

## One flash, many experiments
The firmware has runtime **Lab** switches (`/api/lab`, RAM-only, a reboot resets them):

| switch | 0 (shipped) | other values |
|---|---|---|
| `pace` | `loop()` free-running | 1 = `delay(1)`, 2 = `delay(10)` |
| `dsp` | full chain | 1 = bypass, 2 = silence |
| `send` | guarded send | 1 = drop all audio, 2 = unguarded `binaryAll` |
| `src` | ADC | 1 = synthetic heartbeat (no ADC at all) |
| `text` | normal | bit 1 = no targets, bit 2 = no status pushes |
| `quiet` | logging on | 1 = no serial logging |
| `skip` | all on | bit 1 = radar, 2 = OLED, 4 = DNS |
| `prio` | 5 | audio task priority 1–24 |

### Run it
1. Quick-flash the `c3-supermini` image from `firmware/prebuilt/` (Flasher tab).
2. Join the node's hotspot, then: `python3 tools/soak_test.py --plan quick`
   (8 trials of 60 s: baseline, pace, dsp, send, src, text, quiet, skip). `--plan full` for the whole matrix, `--repeat 3` to separate luck from cause.
3. Read `soak_report_*.md`. A switch that turns a freezing baseline into a clean run is the cause (or next to it). Combine with `--plan 'pace=1,send=1;pace=2'`.
4. If the **baseline** is clean for several minutes, the board is the suspect: run the same image on an S3-Pico or a second C3.

### No board needed
- `g++ -std=c++20 -O1 -fsanitize=address,undefined -I firmware/include tests/test_dsp_stability.cpp && ./a.out`
- `python3 tests/test_soak.py` (the harness against `tools/sim_radar.py`, including a simulated crash)
- `pip install unicorn && python3 tests/rv32_cost/run.py` (needs the PlatformIO RISC-V toolchain)
- All run in CI (`.github/workflows/build.yml`), except the RV32 cost test.

These cannot reproduce the freeze: it depends on the real Wi-Fi stack and radio. They remove everything else.

## Is PlatformIO the right path?
**For building: yes, keep it.** It pins the Arduino-ESP32 core and libraries so builds are reproducible, and CI uses it.
**For end users: no.** They should never need it. The Flasher's Quick-flash path writes the prebuilt whole-chip image with `esptool` (~40 MB) — keep that the default, "Build from source" the exception.
**ESP-IDF instead?** It would shave flash and RAM (Arduino is a layer over it) and give finer control of task priorities and watchdog configuration, but the freeze is in the Wi-Fi/lwIP/async_tcp interplay that ESP-IDF shares, and the port would mean replacing AsyncTCP/ESPAsyncWebServer with `esp_http_server`. Not worth it until the Lab shows the cause. If the cause turns out to be the async server itself, then `esp_http_server` with a plain WebSocket handler is the realistic fallback.
