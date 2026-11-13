// Blip — native tests for the RD-03D parser (no hardware needed)
// Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
// Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
//
// Build + run:  g++ -std=c++11 -I firmware/include tests/test_parser.cpp -o /tmp/test_parser && /tmp/test_parser
#include "rd03d.h"
#include <cstdio>
#include <cstring>
#include <vector>

static int fails = 0;
#define CHECK(cond, msg) do { if (cond) printf("PASS  %s\n", msg); else { printf("FAIL  %s\n", msg); fails++; } } while (0)

// Example frame straight from the Ai-Thinker protocol document:
// target 1 at x=-782 mm, y=+1713 mm, v=-16 cm/s, res=360 mm; targets 2,3 absent.
static const uint8_t DOC_FRAME[30] = {
  0xAA,0xFF,0x03,0x00,
  0x0E,0x03, 0xB1,0x86, 0x10,0x00, 0x68,0x01,
  0,0,0,0,0,0,0,0,
  0,0,0,0,0,0,0,0,
  0x55,0xCC };

// Two-target frame captured by the Electronic Clinic write-up (multi-target mode).
static const uint8_t TWO_FRAME[30] = {
  0xAA,0xFF,0x03,0x00,
  0x05,0x01, 0x19,0x82, 0x00,0x00, 0x68,0x01,
  0xE3,0x81, 0x33,0x88, 0x20,0x80, 0x68,0x01,
  0,0,0,0,0,0,0,0,
  0x55,0xCC };

int main() {
  // 1. Sign decoding
  CHECK(rd03d::decode_signed(0x0E,0x03) == -782,  "x 0x030E -> -782 mm (sign bit clear = negative)");
  CHECK(rd03d::decode_signed(0xB1,0x86) == 1713,  "y 0x86B1 -> +1713 mm (sign bit set = positive)");
  CHECK(rd03d::decode_signed(0x10,0x00) == -16,   "v 0x0010 -> -16 cm/s");
  CHECK(rd03d::decode_signed(0x00,0x80) == 0,     "0x8000 -> +0");

  // 2. Whole frame decode
  rd03d::Frame fr;
  rd03d::decode(DOC_FRAME, fr);
  CHECK(fr.count == 1, "doc frame: one target present");
  CHECK(fr.t[0].present && fr.t[0].x_mm == -782 && fr.t[0].y_mm == 1713 && fr.t[0].v_cms == -16 && fr.t[0].res_mm == 360, "doc frame: target 1 fields");
  CHECK(!fr.t[1].present && !fr.t[2].present, "doc frame: targets 2,3 absent");

  rd03d::decode(TWO_FRAME, fr);
  CHECK(fr.count == 2, "two-target frame: count 2");
  CHECK(fr.t[0].x_mm == -261 && fr.t[0].y_mm == 537 && fr.t[0].v_cms == 0, "two-target frame: t1 = (-261, 537) 0 cm/s");
  CHECK(fr.t[1].x_mm == 483 && fr.t[1].y_mm == 2099 && fr.t[1].v_cms == 32, "two-target frame: t2 = (483, 2099) +32 cm/s");

  // 3. Stream parser with junk, a stray ACK and a torn frame in front
  rd03d::Parser p;
  std::vector<uint8_t> stream;
  const uint8_t junk[] = {0x12, 0xAA, 0xAA, 0xFF, 0x03, 0x01, 0xFD, 0xFC, 0xFB, 0xFA, 0x08, 0x00, 0x80, 0x01, 0x00, 0x00, 0x04, 0x03, 0x02, 0x01};
  stream.insert(stream.end(), junk, junk + sizeof(junk));
  stream.insert(stream.end(), DOC_FRAME, DOC_FRAME + 15);          // torn frame (first half only)
  stream.insert(stream.end(), DOC_FRAME, DOC_FRAME + 30);          // good
  stream.insert(stream.end(), TWO_FRAME, TWO_FRAME + 30);          // good
  stream.insert(stream.end(), DOC_FRAME, DOC_FRAME + 30);          // good
  int got = 0; rd03d::Frame last;
  for (uint8_t b : stream) if (p.feed(b, last)) got++;
  CHECK(got == 3, "stream: 3 frames recovered from junk + ACK + torn frame");
  CHECK(last.count == 1 && last.t[0].y_mm == 1713, "stream: last frame decoded correctly");
  CHECK(p.frames() == 3, "stream: frame counter");

  // 4. A header-looking byte run inside a frame must not derail the next frame
  rd03d::Parser q; got = 0;
  uint8_t tricky[30]; memcpy(tricky, DOC_FRAME, 30);
  tricky[12] = 0xAA; tricky[13] = 0xFF;  // target 2 x bytes look like a header start
  for (int r = 0; r < 5; r++) for (int i = 0; i < 30; i++) if (q.feed(tricky[i], last)) got++;
  CHECK(got == 5, "stream: header-like bytes inside payload do not break framing");

  // 5. Single-target mode in firmware (used for the HLK-LD2450, which always sends three)
  rd03d::Frame s; rd03d::decode(TWO_FRAME, s);             // t1 at 537 mm forward, t2 at 2099 mm
  rd03d::keep_nearest(s);
  CHECK(s.count == 1 && s.t[0].present && s.t[0].y_mm == 537, "single: nearest of two kept");
  CHECK(!s.t[1].present && !s.t[2].present, "single: far target dropped");
  rd03d::Frame e; e.count = 0; for (auto& t : e.t) t.present = false;
  rd03d::keep_nearest(e);
  CHECK(e.count == 0, "single: empty frame stays empty");
  rd03d::Frame three; rd03d::decode(TWO_FRAME, three);
  three.t[2] = three.t[1]; three.t[2].y_mm = 300; three.t[2].x_mm = 0; three.t[2].present = true; three.count = 3;
  rd03d::keep_nearest(three);
  CHECK(three.count == 1 && three.t[2].present && three.t[2].y_mm == 300, "single: nearest of three kept, not the first");

  // 6. LD2450 uses the same 30-byte frame as the RD-03D (HLK manual: AA FF 03 00, 3 x 8 bytes, 55 CC).
  //    Same field layout, so the one parser serves both modules.
  rd03d::Parser ld; rd03d::Frame lf; got = 0;
  for (int i = 0; i < 30; i++) if (ld.feed(TWO_FRAME[i], lf)) got++;
  CHECK(got == 1 && lf.count == 2, "ld2450 frame layout decodes with the shared parser");

  printf("\nRESULT: %s (%d failures)\n", fails ? "FAIL" : "PASS", fails);
  return fails ? 1 : 0;
}
