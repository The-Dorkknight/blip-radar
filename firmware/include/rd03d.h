// Blip — RD-03D frame parser (also reads the HLK-LD2450, which uses the same frame)
// Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
// Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
//
// Plain C++ (no Arduino dependency) so the same code is compiled natively by
// tests/test_parser.cpp and by the ESP32 firmware.
//
// Frame layout (Ai-Thinker Rd-03D serial protocol, 30 bytes, little-endian):
//   AA FF 03 00                      header
//   [x lo][x hi][y lo][y hi][v lo][v hi][res lo][res hi]   target 1
//   ... same 8 bytes for target 2 and target 3 (all zero = no target)
//   55 CC                            tail
// Sign encoding: bit 15 of x, y and v is the SIGN bit (1 = positive),
// the lower 15 bits are the magnitude. x and y in mm, v in cm/s, res in mm.
// Worked example from Ai-Thinker: x = 0x030E -> 782 mm, sign bit 0 -> -782 mm;
// y = 0x86B1 -> sign bit 1, 0x06B1 = 1713 mm; v = 0x0010 -> -16 cm/s.
// (An all-zero target decodes to x=0, y=0, v=0, res=0 => "absent".)
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace rd03d {

static const uint8_t HDR0 = 0xAA, HDR1 = 0xFF, HDR2 = 0x03, HDR3 = 0x00;
static const uint8_t TAIL0 = 0x55, TAIL1 = 0xCC;
static const size_t FRAME_LEN = 30;
static const int MAX_TARGETS = 3;

// Command frames (12 bytes). Sent once at boot; the module answers with an
// ACK frame that the parser simply ignores.
// Mode changes must be wrapped in "enable configuration" ... "end configuration"
// (as Stevee87's sketch and the Ai-Thinker protocol note do); a bare mode
// command is likely to be ignored. Send each with ~200 ms between them.
static const uint8_t CMD_ENABLE_CONFIG[14] = {0xFD,0xFC,0xFB,0xFA,0x04,0x00,0xFF,0x00,0x01,0x00,0x04,0x03,0x02,0x01};
static const uint8_t CMD_END_CONFIG[12]    = {0xFD,0xFC,0xFB,0xFA,0x02,0x00,0xFE,0x00,0x04,0x03,0x02,0x01};
static const uint8_t CMD_SINGLE_TARGET[12] = {0xFD,0xFC,0xFB,0xFA,0x02,0x00,0x80,0x00,0x04,0x03,0x02,0x01};
static const uint8_t CMD_MULTI_TARGET[12]  = {0xFD,0xFC,0xFB,0xFA,0x02,0x00,0x90,0x00,0x04,0x03,0x02,0x01};

struct Target {
  bool     present;
  int16_t  x_mm;      // + = right of the radar, - = left (standing behind it, looking where it looks;
                      //   ESPHome's rd03d and ld2450 docs agree). Blip had this backwards until 2026-11-14.
  int16_t  y_mm;      // + = in front of the radar
  int16_t  v_cms;     // + = moving away, - = approaching (sign as the module reports it)
  uint16_t res_mm;    // distance gate resolution reported by the module
};

struct Frame {
  Target t[MAX_TARGETS];
  uint8_t count;      // number of present targets
};

// Decode one 15-bit-magnitude + sign-bit value.
static inline int16_t decode_signed(uint8_t lo, uint8_t hi) {
  uint16_t raw = (uint16_t)lo | ((uint16_t)hi << 8);
  int16_t mag = (int16_t)(raw & 0x7FFF);
  return (raw & 0x8000) ? mag : (int16_t)(-mag);
}

// Decode a complete, already-validated 30-byte frame.
static inline void decode(const uint8_t* f, Frame& out) {
  out.count = 0;
  for (int i = 0; i < MAX_TARGETS; i++) {
    const uint8_t* p = f + 4 + i * 8;
    Target& t = out.t[i];
    bool allzero = true;
    for (int k = 0; k < 8; k++) if (p[k]) { allzero = false; break; }
    t.x_mm   = decode_signed(p[0], p[1]);
    t.y_mm   = decode_signed(p[2], p[3]);
    t.v_cms  = decode_signed(p[4], p[5]);
    t.res_mm = (uint16_t)p[6] | ((uint16_t)p[7] << 8);
    t.present = !allzero;
    if (t.present) out.count++;
  }
}

// Single-target mode done in firmware: keep only the nearest present target.
// Used for the HLK-LD2450, which always reports up to three targets and has
// no RD-03D mode commands. Harmless on the RD-03D, which already does this.
static inline void keep_nearest(Frame& f) {
  int best = -1;
  int64_t bestD = 0;
  for (int i = 0; i < MAX_TARGETS; i++) {
    const Target& t = f.t[i];
    if (!t.present) continue;
    int64_t d = (int64_t)t.x_mm * t.x_mm + (int64_t)t.y_mm * t.y_mm;
    if (best < 0 || d < bestD) { best = i; bestD = d; }
  }
  f.count = best < 0 ? 0 : 1;
  for (int i = 0; i < MAX_TARGETS; i++)
    if (i != best && f.t[i].present) { f.t[i].present = false; }
}

// Byte-at-a-time stream parser. Resynchronises on the header, tolerates
// the ACK frames the module sends after a command, and never blocks.
class Parser {
 public:
  Parser() : n_(0), frames_(0), bad_(0) {}

  // Feed one byte. Returns true when a complete frame was decoded into `out`.
  bool feed(uint8_t b, Frame& out) {
    // Header hunting: keep the last up-to-4 bytes until they spell the header.
    if (n_ < 4) {
      buf_[n_++] = b;
      if (!header_ok_prefix()) {
        // slide: drop the first byte and retry (handles AA AA FF 03 00 ...)
        resync();
      }
      return false;
    }
    buf_[n_++] = b;
    if (n_ < FRAME_LEN) return false;
    // Full length reached: check tail.
    if (buf_[FRAME_LEN - 2] == TAIL0 && buf_[FRAME_LEN - 1] == TAIL1) {
      decode(buf_, out);
      frames_++;
      n_ = 0;
      return true;
    }
    bad_++;
    resync();
    return false;
  }

  uint32_t frames() const { return frames_; }
  uint32_t bad()    const { return bad_; }

 private:
  uint8_t  buf_[FRAME_LEN];
  size_t   n_;
  uint32_t frames_, bad_;

  bool header_ok_prefix() const {
    static const uint8_t H[4] = {HDR0, HDR1, HDR2, HDR3};
    for (size_t i = 0; i < n_ && i < 4; i++) if (buf_[i] != H[i]) return false;
    return true;
  }
  // Drop the first byte and re-run the header check on what is left.
  void resync() {
    while (n_ > 0) {
      for (size_t i = 1; i < n_; i++) buf_[i - 1] = buf_[i];
      n_--;
      size_t keep = n_ < 4 ? n_ : 4;
      bool ok = true;
      static const uint8_t H[4] = {HDR0, HDR1, HDR2, HDR3};
      for (size_t i = 0; i < keep; i++) if (buf_[i] != H[i]) { ok = false; break; }
      if (ok) {
        // If more than 4 bytes survived the header is intact; keep them all.
        return;
      }
    }
  }
};

}  // namespace rd03d
