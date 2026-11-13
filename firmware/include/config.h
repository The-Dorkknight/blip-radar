// Blip — build-time configuration (pins come from platformio.ini per board)
// Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
// Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
#pragma once

#ifndef BLIP_VERSION
#define BLIP_VERSION "0.2.2-wip"
#endif
#ifndef BLIP_BOARD
#define BLIP_BOARD "unknown board"
#endif
#ifndef BLIP_BOARD_ID
#define BLIP_BOARD_ID "x"
#endif

// --- Wi-Fi hotspot ----------------------------------------------------------
// The radar is its own access point. Join it from the old phone, then open
// http://192.168.4.1/ (the captive portal usually opens it for you).
#define AP_SSID_DEFAULT  "Blip-Radar"
#define AP_PASS_DEFAULT  "blipblip"      // WPA2 needs 8+ characters; change in Settings
#define AP_CHANNEL       6
#define AP_MAX_CLIENTS   4

// --- Radar UART -------------------------------------------------------------
#define RADAR_BAUD       256000
#ifndef PIN_RADAR_RX
#define PIN_RADAR_RX     20
#endif
#ifndef PIN_RADAR_TX
#define PIN_RADAR_TX     21
#endif

// Radar model. 0 = Ai-Thinker RD-03D (default). 1 = HLK-LD2450 (Hi-Link), the
// same 30-byte output frame but no RD-03D configuration commands: it reports up
// to three targets by default, and Single mode is done in firmware.
// Set with -DRADAR_LD2450=1 (or use the c3-supermini-ld2450 / s3-pico-ld2450 envs).
#ifndef RADAR_LD2450
#define RADAR_LD2450     0
#endif

// --- OLED (optional, SSD1306 over I2C, address 0x3C) -----------------------
#ifndef PIN_OLED_SDA
#define PIN_OLED_SDA     6
#endif
#ifndef PIN_OLED_SCL
#define PIN_OLED_SCL     7
#endif
#define OLED_REFRESH_MS  100

// --- Stetho channel (optional CW Doppler IF input through a MAX4466 board) ---
#ifndef PIN_STETHO_I
#define PIN_STETHO_I     1
#endif
#ifndef STETHO_AUDIO_FRAME
#define STETHO_AUDIO_FRAME 256           // samples per audio packet to the phone: 256 = 32 ms at 8 kHz (fewer, bigger packets keep up on weak Wi-Fi)
#endif
// Audio outputs (one at a time). The I2S peripheral drives either an I2S amp
// board (BCLK/WS/DOUT) or, in PDM mode, a 1-bit delta-sigma stream on
// PIN_PDM_OUT for earphones through an RC filter. -1 = not available.
#ifndef PIN_I2S_BCLK
#define PIN_I2S_BCLK     -1
#endif
#ifndef PIN_I2S_WS
#define PIN_I2S_WS       -1
#endif
#ifndef PIN_I2S_DOUT
#define PIN_I2S_DOUT     -1
#endif
#ifndef PIN_PDM_OUT
#define PIN_PDM_OUT      -1
#endif
// Optional: a high-side switch (e.g. a P-MOSFET module) on the RD-03D's 5 V,
// so the radar's 24 GHz sweep can be switched off while you listen with a
// CDM324 on the same band. HIGH = radar powered. -1 = not fitted.
#ifndef PIN_RADAR_PWR
#define PIN_RADAR_PWR    -1
#endif

// Optional: the same kind of high-side switch on the CDM324/HB100's 5 V, so
// the Stetho radar only transmits while Stetho is on (and not auto-asleep).
// HIGH = module powered. -1 = not fitted (module always on).
#ifndef PIN_STETHO_PWR
#define PIN_STETHO_PWR   -1
#endif

// --- Status LED -------------------------------------------------------------
#ifndef PIN_STATUS_LED
#define PIN_STATUS_LED   -1
#endif
#ifndef STATUS_LED_INVERTED
#define STATUS_LED_INVERTED 0
#endif

// --- Rates ------------------------------------------------------------------
#define WS_TARGET_RATE_MS 50             // max 20 target updates/s to the phone
