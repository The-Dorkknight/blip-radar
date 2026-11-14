# How Blip works

Plain-English tour, then the protocol details.

## What it reads, what it changes, what it never does

- **Reads:** bytes from the RD-03D's TX pin (UART1, 256000 baud). Optionally one ADC pin (the Stetho channel, 8 kHz).
- **Writes to the radar:** a three-command sequence at boot and whenever you change mode, 200 ms apart: *enable configuration* (`FD FC FB FA 04 00 FF 00 01 00 04 03 02 01`), *single-target* (`FD FC FB FA 02 00 80 00 04 03 02 01`) or *multi-target* (`… 90 00 …`), then *end configuration* (`FD FC FB FA 02 00 FE 00 04 03 02 01`). v0.2.0 and earlier sent the mode command alone, which the module probably ignored. Nothing else is written; the radar's other settings are never altered.
- **Stores:** a handful of settings in the ESP32's NVS flash: mode, target filter, auto-sleep time, OLED size, the clutter options (minimum range, edge limit, handheld, strict ghost test), Stetho on/off and its clean-up/output settings, hotspot name and password. The Smart filter's clutter map lives in RAM only and is forgotten at power-off.
- **Never does:** connect to the internet, join your home Wi-Fi, record or log positions or audio, or send anything to anyone but the phone that joined its hotspot.

## The pieces

```
RD-03D ──UART 256000──▶ ESP32 ──Wi-Fi hotspot 192.168.4.1──▶ phone browser
                          │  ├─ /            the UI (gzipped HTML in flash)
                          │  ├─ /ws          WebSocket: targets JSON 20/s, Stetho audio 62/s + chest motion 10/s
                          │  ├─ /api/status  JSON: version, board, pins, counters, settings
                          │  ├─ /api/targets JSON: same as the WebSocket text frames (polling fallback)
                          │  └─ /api/config  ?mode= &filter=raw|smart &forget=1 &sleep=min &oled= &stetho=
                          │                   &preset= &ns= &bump= &agc= &maxgain= &gain= &out= &ovol=
                          │                   &radarOff= &ssid= &pass=
                          ├─ optional SSD1306 OLED mirror (I2C; found by a scan at 0x3C/0x3D at boot)
                          ├─ optional Stetho: ADC DMA 8 kHz → DSP task → phone / earphones / I2S amp
                          └─ optional power switches: RD-03D (PIN_RADAR_PWR), CDM324 (PIN_STETHO_PWR)
```

Everything runs in the Arduino `loop()` except Wi-Fi/TCP (handled by ESPAsyncWebServer's own tasks) and the Stetho audio task (priority 5), which wakes every 64 samples from the ADC's DMA, runs the DSP, writes the I2S output and queues packets that `loop()` sends. On the single-core C3 this is fine because the loop never blocks: the UART parser is fed byte by byte, the OLED redraws at most 10 times a second, and WebSocket sends are dropped when nobody is listening or the TCP buffer is full.

## The RD-03D frame

Every report is exactly 30 bytes, little-endian:

```
AA FF 03 00                                  header
x_lo x_hi  y_lo y_hi  v_lo v_hi  r_lo r_hi   target 1  (8 bytes)
x_lo x_hi  y_lo y_hi  v_lo v_hi  r_lo r_hi   target 2
x_lo x_hi  y_lo y_hi  v_lo v_hi  r_lo r_hi   target 3
55 CC                                        tail
```

- `x`, `y` in mm, `v` in cm/s, `r` ("distance resolution", the range gate) in mm.
- **Sign encoding:** bit 15 is the *sign flag* — set means positive, clear means negative — and the lower 15 bits are the magnitude. Ai-Thinker's own worked example: `0E 03` → 0x030E = 782 with the flag clear → **−782 mm**; `B1 86` → 0x86B1, flag set, 0x06B1 → **+1713 mm**; `10 00` → **−16 cm/s**.
- An all-zero 8-byte slot means "no target".
- `+x` is to the radar's **left** (looking out from behind it), `+y` straight ahead. Blip computes distance = √(x²+y²) and bearing = atan2(x, y).
- Speed sign: negative values were observed while approaching. Treat the sign as "as reported by the module" until verified on hardware.

The module also answers commands with ACK frames (`FD FC FB FA … 04 03 02 01`); the parser just resynchronises on the next `AA FF 03 00` and counts the discard in `bad`.

Note: several online sketches decode the frame as `value − 0x200` / `− 0x8000` / `− 0x10`. That matches the worked example only by coincidence for one target; Blip follows the sign-bit rule, which is what the Ai-Thinker protocol note actually describes and what makes the second captured target in `tests/test_parser.cpp` land at a sensible (+483, +2099) mm.

## JSON on the wire

Targets (WebSocket text frame or `GET /api/targets`):

```json
{"ms":123456,"alive":true,"fps":21,"f":"smart","sleep":false,"t":[
  {"id":7,"x":-782,"y":1713,"v":-16,"res":0,"d":1883,"a":-24.5}],
 "h":[{"id":9,"x":-1100,"y":3000,"why":"ghost"}]}
```

`f` is the target filter. With `raw`, `t` is the module's three slots as they come (`id` 1–3 = slot number). With `smart`, `t` holds Blip's own confirmed tracks: `id` is a track number that stays with a person, and `res` is 0. `h` lists what the Smart filter is hiding and why (`ghost` = likely reflection, `clutter` = wobbling in place); the phone draws these as dashed rings when *Show filtered* is on. `g` (any mode) lists what the clutter options dropped before that (`near`, `edge`, `scenery`), and `ego` is the estimated walking speed in mm/s while handheld mode is on.

`d` is mm, `a` is degrees (+ left). `alive` turns false 1.5 s after the last good frame.

Stetho (WebSocket binary frames, little-endian, 6-byte header):

| Byte | 'U' audio | 'V' chest motion |
|---|---|---|
| 0 | `0x55` | `0x56` |
| 1 | flags: bit0 bump being ducked, bit1 output clipped, bit2 ADC at a rail | same |
| 2–3 | sequence number (uint16) | sequence number |
| 4 | AGC gain, dB (int8) | 0 |
| 5 | noise suppression, average dB (int8, ≤ 0) | 0 |
| 6… | 256 × G.711 mu-law byte at 8000 Hz (32 ms), **after** the node's clean-up | 10 × int16 at 100 Hz (100 ms), raw (DC removed, 80:1 averaged) |

The page also still plays the older `'A'` packets (`0x41`, int16 samples). The node's status JSON and target JSON go over the same WebSocket as text; all of it is sent from one task, text first.

The node's clean-up chain (`firmware/include/audio_dsp.h`) is bump gate → preset EQ → 4-band noise suppressor → AGC → limiter. The design is in DESIGN_NOTES.md §11.

The phone:
- **Sound:** a ring-buffer player keeps about 40 ms queued, follows the node's clock and skips ahead if it ever lags. It uses an AudioWorklet on https/localhost and a ScriptProcessor on the node's plain-http page. Add `?player=sp` to the URL to force the fallback.
- **Chest motion:** 0.1–5 Hz for the drawn trace and the breathing estimate (zero-crossings over 8 s), 0.8–3 Hz for the heart rate (first autocorrelation peak between 0.33 and 1.5 s lag). Samples flagged as bumps are held instead of drawn as spikes.
- The node also plays the same processed audio to 3.5 mm earphones (I2S PDM delta-sigma) or an I2S amp board, with or without a phone (hardware/audio-out.md).

## Clutter options (gate, experimental)

`firmware/include/gate.h` runs on every frame before Raw or Smart: drop contacts closer than the set minimum range or beyond the set edge angle; in handheld mode, turn each remaining contact's closing speed into a guess at our own walking speed (closing speed / cos bearing), take the guess at least two contacts agree on, hold it 1.5 s, and drop every contact that fits it. `tools/gate_py.py` is the simulator's copy; `tests/test_gate_py.py` checks the two agree.

## Smart target filter (experimental)

`firmware/include/tracker.h`, on top of the module's output, ~20 times a second:

1. **Gate:** drop detections closer than 10 cm, further than 8 m or outside ±65°.
2. **Predict** every track forward with a constant-velocity model.
3. **Associate:** try every pairing of the (≤ 3) detections with the (≤ 6) tracks and keep the cheapest. Distance counts against the gate (0.7 m plus how far a 3.5 m/s walker could go since the track was last seen), and a new track costs more than any match.
4. **Alpha-beta filter** (α 0.5, β 0.15) to smooth position and estimate velocity.
5. **Confirm** a new track only once it has been seen in 3 of its last 5 frames. One-frame flickers never show.
6. **Coast** through missed frames for up to 1 s, then drop the track.
7. **Ghost test:** a track that sits ≥ 0.5 m *behind* a moving track, within 10° of the same bearing, with the module's Doppler speed matching it, for 1 s → hidden as a likely wall reflection. A track that might be one is held back from showing while the test runs.
8. **Clutter map:** a track that keeps being reported but whose ~1 s average position stays within 0.4 m of one spot for 30 s (fan, curtain, swaying plant) is muted. The spot is remembered as a 1.5 m patch of a 0.5 m grid that fades over ~8 minutes; a track sitting still there is re-muted after 3 s instead of 30, and anything that starts up on that spot again is tracked but stays muted. Either comes back if it moves 0.8 m away.

The OLED, the tracker ping and the Scope all use the filtered targets when Smart is on. `tools/tracker_py.py` is a Python copy used by the simulator; `tests/test_tracker_py.py` checks the two agree frame by frame.

## Auto-sleep

With *Auto-sleep* set to N minutes:
- if no phone is connected and the OLED is off for N minutes, the RD-03D is powered down (needs `PIN_RADAR_PWR`);
- if no phone is connected and no node audio output is chosen for N minutes, Stetho stops and the CDM324 is powered down (needs `PIN_STETHO_PWR`; without it only the processing stops).

A phone joining the hotspot wakes both. When the CDM324 comes back on, the first 0.6 s of audio is muted to hide the switch-on thump.

## Captive portal

The node answers every DNS query with 192.168.4.1 and redirects the usual connectivity-check URLs (`/generate_204`, `/hotspot-detect.html`, `/connecttest.txt`…) to `/`. Most phones then pop the page up by themselves.

## The node log

`firmware/include/blip_log.h` keeps the last ~4 KB of timestamped lines in RTC memory (`RTC_NOINIT_ATTR`), which survives a crash, a watchdog reset or `ESP.restart()`, but not a power cut. Every line also goes to the USB serial port. Every 10 s `loop()` adds a health line:

```
[03:20.0] health: 96 KB free (lowest 81, biggest block 52) | 1 on hotspot, 1 page(s) | +3 requests +12 probes | loop 14 ms | Stetho on 1650 mV, +312 sent +0 skipped +0 dropped
```

To read it: Settings → *Node log* on the page (`/api/log`), or the flasher's **🔌 USB log** button, which shows the serial output without flashing. Free memory that only goes down across health lines is a leak. A lot of *probes* means a phone or laptop keeps checking for internet (captive portal). Wi-Fi *left, reason N* lines say why a device dropped.

## The flasher

The launcher's first page is the **Blip Flasher** (`/`, red): `tools/flasher.py` takes `web/flash_home.html` and inlines `web/flasher.html` with a fresh per-run token. Only this computer gets it; any other client asking for `/` gets the simulator. The simulator, the same page the ESP32 serves, is at `/sim` and shows a small **⚡ Flasher** button back when the status says `"flash": true`. Neither flasher file is in the firmware, so the board's embedded page stays the same size. `--no-flash` turns all of it off and `/` is the simulator again.

```
browser ──/api/flash/info────────▶ boards, radars, serial ports, is PlatformIO there?
        ──/api/flash/start (POST)▶ {board, radar, port, monitor}   needs X-Blip-Token
        ──/api/flash/log?from=N──▶ state, 5 step statuses, upload %, tips, new log lines
        ──/api/flash/cancel (POST)
Quick flash:       check firmware/prebuilt/<image> against manifest.json → find/install esptool (.venv)
                   → esptool --chip <chip> --port <port> write_flash 0x0 <image> → serial_tail.py
Build from source: embed_web.py → find/install PlatformIO (.venv) → pio run -e <env> → -t upload → serial_tail.py
```

- **Bundled firmware:** `tools/make_prebuilt.py` copies each env's `firmware.factory.bin` (bootloader + partition table + app) to `firmware/prebuilt/blip-<env>-full.bin` and writes `manifest.json`: version, build time, each image's SHA-256 and size, and a SHA-256 over the firmware source (`firmware/src`, `firmware/include` except the generated `web_ui.h`, `platformio.ini`, `web/index.html`, line endings normalised). Quick flash refuses an image whose checksum doesn't match, and warns (but still flashes the bundle) when your source hash differs.
- **Auto-detect:** Quick flash uses the one USB serial port it can see (ttyACM/ttyUSB, cu.usb*, or the COM ports Windows lists); with none or several it stops and asks, rather than let esptool probe every serial port on the machine.

- **Only this computer:** requests must come from a loopback address with a `localhost`/`127.0.0.1` Host header (stops DNS rebinding); cross-site requests are refused; start and cancel need a random token that is generated per run and only put into the page.
- **No shell:** commands are argument lists. The board and radar pick an env from a fixed table; the port must be one the flasher itself found.
- **Progress:** esptool's "Writing at … (N %)" lines drive the bar for the big segment (the app); the small ones (bootloader, partitions) show as a busy bar. The log keeps one progress line per 10 %.
- **Tips:** each output line is matched against a short list of known problems (port permission, board not in download mode, no internet, Git or `python3-venv` missing, port busy, disk full).
- **Serial output:** `tools/serial_tail.py` opens the port with DTR/RTS low (no reset), retrying for a few seconds while the C3 re-appears on USB.
- **Tests:** `tests/test_flasher.py` runs the whole thing against `tests/fake_pio.py`, which prints what PlatformIO and esptool print and can fail the usual ways.

## The simulator

`tools/sim_radar.py` is a stand-in for the whole node: the same URLs, the same JSON, the same WebSocket binary frames (its Stetho sound is synthesised to look plausible, not run through the real DSP), Python standard library only. Its three walkers are **encoded into real 30-byte RD-03D frames and decoded again** by a Python port of the parser before they reach the page, so the byte layout is exercised every time you run it. `--frames examples/frames_synthetic.hex` replays a hex dump instead.
