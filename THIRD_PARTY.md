# Third-party notices

Blip's own code is licensed under the PolyForm Noncommercial License 1.0.0 (see LICENSE.md). That licence covers only Matthew Armstrong's code and documents in this repository. Everything listed below keeps its own licence, and none of these projects or companies is affiliated with or endorses Blip.

| Component | Used for | Licence (see their site) |
|---|---|---|
| arduino-esp32 (Espressif) | Arduino core for ESP32-C3/S3 | https://github.com/espressif/arduino-esp32 |
| ESPAsyncWebServer and AsyncTCP (ESP32Async fork) | HTTP + WebSocket server | https://github.com/ESP32Async/ESPAsyncWebServer |
| U8g2 (olikraus) | SSD1306 OLED driver | https://github.com/olikraus/u8g2 |
| PlatformIO | build system | https://platformio.org |
| Python 3 standard library | simulator, tools | https://www.python.org |
| matplotlib, Pillow, Playwright | drawing the illustrations and screenshots (dev-time only) | their respective sites |

Downloaded on demand, not included in this repository:

| Component | Used for | Licence |
|---|---|---|
| earlynerd, *HLK-LD2450_FW*, commit `92d0ed11cc34` | the flasher's experimental **LD2450 custom firmware** tab downloads this project on first use into `.cache/` and runs its own tools (`stock_uart.py`, `uart_upload.py`, `restore_stock.py`, `tools/live_radar.py`) | MIT, Copyright (c) 2026 earlynerd: https://github.com/earlynerd/HLK-LD2450_FW. Its stock `.ufw` images and code extracted from them are Hi-Link's / the SDK vendors' material, which that project does not license; Blip neither bundles nor redistributes them |
| pyserial, lz4, numpy | installed into `.venv` by that tab, for those tools | their respective sites |

Inspiration and reverse-engineering sources (no code copied):
- Stevee87, *Arduino-ESP32-Radarproject* (MIT): https://github.com/Stevee87/Arduino-ESP32-Radarproject
- Ai-Thinker Rd-03D specification and serial protocol documents.
- Electronic Clinic's RD-03D write-up (a captured two-target frame is reused in the tests).
- Papers cited in DESIGN_NOTES.md.

Trademarks (ESP32, Arduino, Waveshare, Ai-Thinker, Raspberry Pi Pico) belong to their owners.
