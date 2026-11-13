// Blip — optional SSD1306 OLED output (0.91" 128x32 or 0.96" 128x64, I2C)
// Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
// Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
//
// The display type is a runtime setting (web UI > Settings) stored in NVS, so
// the same firmware drives either of the generic "0.9x inch" modules, or none.
#pragma once
#include "blip_log.h"
#include <Arduino.h>
#include <Wire.h>
#include <U8g2lib.h>
#include <math.h>
#include "config.h"
#include "rd03d.h"
#include "oled_draw.h"

// OLED_AUTO scans the I2C bus for a display (0x3C, then 0x3D). A bare SSD1306 cannot be asked its
// size over I2C, so Auto assumes 128x64; pick 128x32 in Settings for a 0.91" panel (it is remembered).
enum OledKind : uint8_t { OLED_NONE = 0, OLED_128X32 = 1, OLED_128X64 = 2, OLED_AUTO = 3 };

class Oled {
 public:
  Oled() : kind_(OLED_NONE), u8_(nullptr), lastDraw_(0) {}
 private:
  bool found_ = false;
  uint8_t addr_ = 0;
 public:

  // (Re)initialise for the chosen panel. Safe to call again with a new kind.
  void begin(OledKind kind) {
    end();
    found_ = false;
    kind_ = kind;
    if (kind_ == OLED_NONE) return;
    Wire.begin(PIN_OLED_SDA, PIN_OLED_SCL);
    Wire.setTimeOut(20);
    // Is there a display at all? Without one every frame would wait for I2C
    // timeouts and slow the whole node down. Both usual addresses are tried.
    addr_ = 0;
    static const uint8_t addrs[2] = {0x3C, 0x3D};
    for (uint8_t a : addrs) {
      Wire.beginTransmission(a);
      if (Wire.endTransmission() == 0) { addr_ = a; break; }
    }
    found_ = addr_ != 0;
    if (!found_) { blog::logf("OLED: nothing answers at 0x3C or 0x3D on SDA%d/SCL%d, display output off", PIN_OLED_SDA, PIN_OLED_SCL); kind_ = OLED_NONE; return; }
    if (kind_ == OLED_AUTO) { kind_ = OLED_128X64; blog::logf("OLED: found at 0x%02X, size cannot be read so assuming 128x64 (choose 128x32 in Settings if needed)", addr_); }
    else blog::logf("OLED: found at 0x%02X, %s", addr_, kind_ == OLED_128X32 ? "128x32" : "128x64");
    if (kind_ == OLED_128X32)
      u8_ = new U8G2_SSD1306_128X32_UNIVISION_F_HW_I2C(U8G2_R0, U8X8_PIN_NONE, PIN_OLED_SCL, PIN_OLED_SDA);
    else
      u8_ = new U8G2_SSD1306_128X64_NONAME_F_HW_I2C(U8G2_R0, U8X8_PIN_NONE, PIN_OLED_SCL, PIN_OLED_SDA);
    u8_->setI2CAddress(addr_ << 1);
    u8_->begin();
    u8_->setContrast(200);
    splash();
  }

  void end() {
    if (u8_) { u8_->clearDisplay(); delete u8_; u8_ = nullptr; }
    kind_ = OLED_NONE;
  }

  OledKind kind() const { return kind_; }
  bool found() const { return found_; }
  uint8_t addr() const { return addr_; }

  // Draw the radar picture. Call as often as you like; it rate-limits itself.
  // The picture itself is drawn by oled_draw.h (shared with the PC preview).
  void draw(const rd03d::Frame& fr, bool radarAlive, bool asleep, bool smart, int clients, const char* ip) {
    if (!u8_) return;
    uint32_t now = millis();
    if (now - lastDraw_ < OLED_REFRESH_MS) return;
    lastDraw_ = now;
    const int H = u8_->getDisplayHeight();
    blip_oled::Blip b[rd03d::MAX_TARGETS];
    for (int i = 0; i < rd03d::MAX_TARGETS; i++) b[i] = {fr.t[i].present, fr.t[i].x_mm, fr.t[i].y_mm};
    blip_oled::Status st{radarAlive, asleep, smart, clients, ip};
    blip_oled::render(canvas_, H, b, rd03d::MAX_TARGETS, st);
    // same page layout as U8g2's SSD1306 full frame buffer: copy and send
    memcpy(u8_->getBufferPtr(), canvas_.buf, (size_t)blip_oled::Canvas::W * H / 8);
    u8_->sendBuffer();
  }

 private:
  OledKind kind_;
  U8G2* u8_;
  uint32_t lastDraw_;
  blip_oled::Canvas canvas_;

  void splash() {
    u8_->clearBuffer();
    u8_->setFont(u8g2_font_6x12_tf);
    u8_->drawStr(0, 10, "Blip " BLIP_VERSION);
    u8_->setFont(u8g2_font_5x7_tf);
    u8_->drawStr(0, 20, "WiFi: " AP_SSID_DEFAULT);
    if (u8_->getDisplayHeight() > 32) {
      u8_->drawStr(0, 32, "http://192.168.4.1/");
      u8_->drawStr(0, 44, "WIP: may be broken");
    }
    u8_->sendBuffer();
  }
};
