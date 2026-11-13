// Blip — OLED picture, drawn into a plain 1-bit buffer (no Arduino, no U8g2).
// Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
// Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
//
// The buffer uses the SSD1306 page layout (one byte = 8 pixels stacked
// vertically), so oled.h can copy it straight into U8g2's frame buffer, and
// tests/oled_render.cpp can render the *same code* on a PC for the README
// pictures. Fonts are tiny hand-drawn bitmaps defined below.
//
// Each person is a circle with their distance inside it: whole metres in a
// normal digit, tenths in a smaller raised digit, so 2.3 m reads "2³" with no
// decimal point to squeeze in. The nearest person is drawn inverted (solid).
#pragma once
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>

namespace blip_oled {

// ---- fonts ------------------------------------------------------------------
// 3x5: digits, a few capitals and symbols (each row: 3 bits, MSB = left)
struct Glyph3 { char c; uint8_t r[5]; };
static const Glyph3 F3[] = {
  {'0', {7, 5, 5, 5, 7}}, {'1', {2, 6, 2, 2, 7}}, {'2', {7, 1, 7, 4, 7}}, {'3', {7, 1, 7, 1, 7}},
  {'4', {5, 5, 7, 1, 1}}, {'5', {7, 4, 7, 1, 7}}, {'6', {7, 4, 7, 5, 7}}, {'7', {7, 1, 2, 2, 2}},
  {'8', {7, 5, 7, 5, 7}}, {'9', {7, 5, 7, 1, 7}},
  {'A', {2, 5, 7, 5, 5}}, {'D', {6, 5, 5, 5, 6}}, {'G', {3, 4, 5, 5, 3}}, {'H', {5, 5, 7, 5, 5}},
  {'I', {7, 2, 2, 2, 7}}, {'M', {5, 7, 7, 5, 5}}, {'N', {6, 5, 5, 5, 5}}, {'O', {2, 5, 5, 5, 2}},
  {'P', {6, 5, 6, 4, 4}}, {'R', {6, 5, 6, 5, 5}}, {'S', {3, 4, 2, 1, 6}}, {'T', {7, 2, 2, 2, 2}},
  {'W', {5, 5, 7, 7, 5}}, {'X', {5, 5, 2, 5, 5}}, {'.', {0, 0, 0, 0, 2}}, {'-', {0, 0, 7, 0, 0}},
  {' ', {0, 0, 0, 0, 0}},
};
// 4x6 digits (128x32 blips) and 5x7 digits (128x64 blips)
static const uint8_t F4[10][6] = {
  {6, 9, 9, 9, 9, 6}, {2, 6, 2, 2, 2, 7}, {6, 9, 2, 4, 8, 15}, {14, 1, 6, 1, 1, 14}, {9, 9, 15, 1, 1, 1},
  {15, 8, 14, 1, 1, 14}, {6, 8, 14, 9, 9, 6}, {15, 1, 2, 4, 4, 4}, {6, 9, 6, 9, 9, 6}, {6, 9, 9, 7, 1, 6}};
static const uint8_t F5[10][7] = {
  {14, 17, 17, 17, 17, 17, 14}, {4, 12, 4, 4, 4, 4, 14}, {14, 17, 1, 2, 4, 8, 31}, {30, 1, 1, 14, 1, 1, 30},
  {2, 6, 10, 18, 31, 2, 2}, {31, 16, 30, 1, 1, 17, 14}, {6, 8, 16, 30, 17, 17, 14}, {31, 1, 2, 4, 8, 8, 8},
  {14, 17, 17, 14, 17, 17, 14}, {14, 17, 17, 15, 1, 2, 12}};

// ---- canvas -------------------------------------------------------------------
struct Canvas {
  static const int W = 128;
  int H = 64;
  uint8_t buf[128 * 64 / 8];

  void clear() { memset(buf, 0, sizeof buf); }
  void px(int x, int y, bool on = true) {
    if (x < 0 || x >= W || y < 0 || y >= H) return;
    uint8_t& b = buf[(y >> 3) * W + x];
    if (on) b |= (uint8_t)(1 << (y & 7)); else b &= (uint8_t)~(1 << (y & 7));
  }
  bool get(int x, int y) const { return x >= 0 && x < W && y >= 0 && y < H && (buf[(y >> 3) * W + x] >> (y & 7)) & 1; }
  void line(int x0, int y0, int x1, int y1, bool on = true) {           // Bresenham
    int dx = x1 > x0 ? x1 - x0 : x0 - x1, sx = x0 < x1 ? 1 : -1;
    int dy = y1 > y0 ? y0 - y1 : y1 - y0, sy = y0 < y1 ? 1 : -1, e = dx + dy;
    for (;;) { px(x0, y0, on); if (x0 == x1 && y0 == y1) break; int e2 = 2 * e; if (e2 >= dy) { e += dy; x0 += sx; } if (e2 <= dx) { e += dx; y0 += sy; } }
  }
  void dottedLine(int x0, int y0, int x1, int y1) {
    int n = (int)hypotf((float)(x1 - x0), (float)(y1 - y0));
    for (int i = 0; i <= n; i += 2) px(x0 + (x1 - x0) * i / (n ? n : 1), y0 + (y1 - y0) * i / (n ? n : 1));
  }
  void circle(int cx, int cy, int r, bool on = true) {                  // midpoint circle
    int x = r, y = 0, e = 1 - r;
    while (x >= y) {
      px(cx + x, cy + y, on); px(cx + y, cy + x, on); px(cx - y, cy + x, on); px(cx - x, cy + y, on);
      px(cx - x, cy - y, on); px(cx - y, cy - x, on); px(cx + y, cy - x, on); px(cx + x, cy - y, on);
      y++; if (e < 0) e += 2 * y + 1; else { x--; e += 2 * (y - x) + 1; }
    }
  }
  void disc(int cx, int cy, int r, bool on = true) {
    for (int y = -r; y <= r; y++) for (int x = -r; x <= r; x++) if (x * x + y * y <= r * r + r) px(cx + x, cy + y, on);
  }
  void bits(int x, int y, const uint8_t* rows, int w, int h, bool on = true) {
    for (int j = 0; j < h; j++) for (int i = 0; i < w; i++) if ((rows[j] >> (w - 1 - i)) & 1) px(x + i, y + j, on);
  }
  // 3x5 text, 1 px spacing; returns the width drawn
  int text(int x, int y, const char* s, bool on = true) {
    int x0 = x;
    for (; *s; s++) {
      for (const Glyph3& g : F3) if (g.c == *s) { bits(x, y, g.r, 3, 5, on); break; }
      x += 4;
    }
    return x - x0 - 1;
  }
  static int textW(const char* s) { int n = (int)strlen(s); return n ? n * 4 - 1 : 0; }
};

// ---- the picture ----------------------------------------------------------------
struct Blip { bool present; int x_mm, y_mm; };

struct Status {
  bool alive;          // radar frames arriving
  bool asleep;         // radar powered down by auto-sleep
  bool smart;          // experimental tracker on
  int phones;          // devices on the hotspot
  const char* ip;      // shown on the 128x64 panel
};

// The distance badge: circle, whole metres, raised smaller tenths digit.
inline void drawBadge(Canvas& c, int cx, int cy, int mm, bool big, bool inverted) {
  int d10 = (mm + 50) / 100;                     // tenths of a metre, rounded
  if (d10 > 99) d10 = 99;
  int m = d10 / 10, t = d10 % 10;
  int r = big ? 7 : 6;
  c.disc(cx, cy, r + 1, false);                  // black halo so grid lines don't touch it
  if (inverted) c.disc(cx, cy, r, true); else c.circle(cx, cy, r, true);
  bool ink = !inverted;
  if (big) {                                     // 5x7 metres + 3x5 tenths = 9 px wide
    int x = cx - 4, y = cy - 3;
    c.bits(x, y, F5[m], 5, 7, ink);
    for (const Glyph3& g : F3) if (g.c == '0' + t) { c.bits(x + 6, y, g.r, 3, 5, ink); break; }
  } else {                                       // 4x6 metres + 3x5 tenths = 8 px wide
    int x = cx - 4, y = cy - 3;
    c.bits(x, y, F4[m], 4, 6, ink);
    for (const Glyph3& g : F3) if (g.c == '0' + t) { c.bits(x + 5, y, g.r, 3, 5, ink); break; }
  }
}

// Tiny 5x5 icons for the corners (rows, MSB = left)
static const uint8_t ICON_WIFI[5]  = {62, 65, 28, 34, 8};     // 7 px wide Wi-Fi fan, drawn next to the phone count
static const uint8_t ICON_SMART[5] = {4, 14, 31, 14, 4};      // a diamond: Smart filter on

// No status line: the scope uses the whole panel. Everything else lives in the
// empty corners outside the 120° sector, or only appears when something is wrong.
//   top-left:  ◆ when the Smart filter is on
//   top-right: Wi-Fi icon + number of phones on the hotspot
//   bottom-left (128x64 only): the IP address, only while no phone is connected
//   centre: "NO RADAR" / "SLEEP" in a box, only when that's the case
inline void render(Canvas& c, int height, const Blip* b, int n, const Status& st) {
  c.H = height; c.clear();
  const int W = Canvas::W, H = height;
  bool big = H > 32;

  // the scope: 120° sector, rings every 2 m to 8 m (dotted), three bearing lines.
  // The sector is stretched sideways to fill the panel's width; badges carry the
  // true distance, so the slight distortion costs nothing.
  const float RANGE_MM = 8000.0f;
  int cx = W / 2, cy = H - 1, Rx = 72, Ry = H - 2;
  for (int ring = 1; ring <= 4; ring++) {
    for (int a = -60; a <= 60; a += (ring < 3 ? 6 : 3)) {
      float rad = a * 0.0174533f;
      c.px(cx + (int)lroundf(Rx * ring / 4.0f * sinf(rad)), cy - (int)lroundf(Ry * ring / 4.0f * cosf(rad)));
    }
  }
  for (int a = -60; a <= 60; a += 60) {
    float rad = a * 0.0174533f;
    c.dottedLine(cx, cy, cx + (int)lroundf(Rx * sinf(rad)), cy - (int)lroundf(Ry * cosf(rad)));
  }

  // corners
  if (st.smart) c.bits(0, 0, ICON_SMART, 5, 5);
  char s[16];
  snprintf(s, sizeof s, "%d", st.phones > 9 ? 9 : st.phones);
  c.bits(W - 7, 0, ICON_WIFI, 7, 5);
  c.text(W - 9 - Canvas::textW(s), 0, s);
  if (big && st.ip && st.phones == 0) c.text(0, H - 5, st.ip);

  if (!st.alive || st.asleep) {
    const char* m = st.asleep ? "SLEEP" : "NO RADAR";
    int w = Canvas::textW(m), x = (W - w) / 2, y = H / 2 - 3;
    for (int yy = y - 2; yy < y + 7; yy++) for (int xx = x - 3; xx < x + w + 3; xx++) c.px(xx, yy, false);
    c.text(x, y, m);
    return;
  }
  // nearest first gets drawn last (on top) and inverted
  int order[8], m = 0, nearest = -1, nd = 1 << 30;
  for (int i = 0; i < n && m < 8; i++) if (b[i].present) {
    order[m++] = i;
    int d = (int)hypotf((float)b[i].x_mm, (float)b[i].y_mm);
    if (d < nd) { nd = d; nearest = i; }
  }
  int r = big ? 7 : 6;
  for (int pass = 0; pass < 2; pass++) for (int k = 0; k < m; k++) {
    int i = order[k];
    if ((pass == 1) != (i == nearest)) continue;
    // module: +x is to the radar's left, so it goes to the screen's left
    int px = cx - (int)lroundf(b[i].x_mm / RANGE_MM * Rx);
    int py = cy - (int)lroundf(b[i].y_mm / RANGE_MM * Ry);
    if (px < r) px = r;
    if (px > W - 1 - r) px = W - 1 - r;
    if (py < r) py = r;
    if (py > H - 1 - r) py = H - 1 - r;
    int d = (int)hypotf((float)b[i].x_mm, (float)b[i].y_mm);
    drawBadge(c, px, py, d, big, i == nearest);
  }
}

}  // namespace blip_oled
