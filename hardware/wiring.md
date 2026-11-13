# Wiring

See the diagrams in `docs/images/` (drawn from `firmware/platformio.ini` by `tools/draw_illustrations.py`).

| Signal | ESP32-C3 Super Mini | Waveshare ESP32-S3-Pico | Note |
|---|---|---|---|
| Radar TX → ESP RX | GPIO20 | GPIO12 | UART1, 256000 8N1, 3.3 V logic |
| Radar RX ← ESP TX | GPIO21 | GPIO11 | mode command only |
| Radar 5V | 5V pin | VBUS | ≥200 mA peak, ripple <100 mV; never 3V3 |
| OLED SDA / SCL | GPIO6 / GPIO7 | GPIO17 / GPIO18 | SSD1306 at 0x3C, powered from 3V3 |
| Stetho: MAX4466 OUT | GPIO1 | GPIO7 | ADC1; MAX4466 on 3V3 — see [max4466-mod.md](max4466-mod.md) |
| Earphones (delta-sigma) | GPIO10 | GPIO16 | through the RC filter in [audio-out.md](audio-out.md) |
| I2S amp BCLK / LRC / DIN | GPIO3 / GPIO4 / GPIO5 | GPIO13 / GPIO14 / GPIO15 | MAX98357A board |
| Radar power switch (optional) | not assigned | not assigned | set `PIN_RADAR_PWR` to use one |
| CDM324 power switch (optional) | not assigned | not assigned | set `PIN_STETHO_PWR`; same kind of high-side switch |

Notes
- The RD-03D connector is a 1.25 mm 4-pin socket (5V, GND, TX, RX). Keep the wires short; the module is ESD sensitive.
- The C3 Super Mini's USB-C 5V pin can feed the radar for bench tests. For battery use add a 1S cell + 5 V boost (the radar wants 5 V, the datasheet asks for an LDO or a low-ripple DC-DC).
- Keep metal away from the radar's antenna face; a metal plate *behind* it shields the back lobe.
- Only ADC1 pins work while Wi-Fi is on (C3: GPIO0–4, S3: GPIO1–10), which is why the Stetho input is where it is.
- **Optional radar power switch:** to switch the RD-03D off while a CDM324 listens on the same band, put a high-side switch on its 5 V (a P-MOSFET module or a logic-level load switch). Then set `-DPIN_RADAR_PWR=<gpio>` in `platformio.ini` and pick *Radar off* in Settings. Don't switch its ground: the UART lines would then back-feed the module.
- **Optional CDM324 power switch:** the CDM324/HB100 has no enable pin and transmits whenever powered. Put the same kind of high-side switch on its 5 V and set `-DPIN_STETHO_PWR=<gpio>`; it then only runs while Stetho is on, and Auto-sleep can turn it off. Don't run it straight from a GPIO: it wants 5 V at about 35 mA.
- How to build the switch: a P-MOSFET (e.g. AO3401) in the 5 V line, its gate pulled up to 5 V with 10 kΩ, and a small N-MOSFET (e.g. 2N7002 or AO3400) from that gate to GND driven by the GPIO. GPIO high = N-FET on = P-FET on = module powered. A 3.3 V pin can't switch a P-FET on 5 V directly.
- Free pins: on the C3 use **GPIO0** for one switch; a second has to be **GPIO2**, a strapping pin that must not be pulled low at boot. An N-MOSFET gate draws no current, so that's fine, but don't use a bipolar transistor or a pull-down there. On the S3-Pico, GPIO8 and GPIO9 are free.
- **HLK-LD2450 instead of the RD-03D:** same 5 V / GND / UART wiring in the table above. Its header is labelled from the module's side (5V, GND, RX, TX), so its **TX** goes to the board's **RX** pin (GPIO20 on the C3, GPIO12 on the S3-Pico) and its **RX** to the board's **TX** pin. Build with `c3-supermini-ld2450` or `s3-pico-ld2450`.
- The firmware compiles for both boards (v0.2.2-wip), with the RD-03D and with the LD2450 option. None of this has been verified on real hardware yet.
