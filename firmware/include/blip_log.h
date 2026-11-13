// Blip — node log: a small ring buffer of timestamped lines that also goes to
// the serial port. It lives in RTC memory, which survives a crash, a watchdog
// reset or a software restart (not a power cut), so after the node restarts
// the page (/api/log) still shows what it was doing just before.
// Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
// Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
#pragma once
#include <Arduino.h>
#include <stdarg.h>
#include <esp_attr.h>

namespace blog {

static const uint32_t LOG_SIZE = 4096;      // bytes of text kept (about 60 lines)
static const uint32_t MAGIC = 0xB10C0002u;

struct Ring {
  uint32_t magic;
  uint32_t head;      // next write position
  uint32_t used;      // bytes valid (<= LOG_SIZE)
  char buf[LOG_SIZE];
};
static RTC_NOINIT_ATTR Ring ring;
static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
inline volatile bool quiet = false;         // Lab switch: keep the ring, skip the Serial port

inline void put(const char* s, size_t n) {
  portENTER_CRITICAL(&mux);
  for (size_t i = 0; i < n; i++) {
    ring.buf[ring.head] = s[i];
    ring.head = (ring.head + 1) % LOG_SIZE;
    if (ring.used < LOG_SIZE) ring.used++;
  }
  portEXIT_CRITICAL(&mux);
}

// Call once at start-up. keep=false (power-on) starts an empty log.
inline void begin(bool keep) {
  if (!keep || ring.magic != MAGIC || ring.head >= LOG_SIZE || ring.used > LOG_SIZE) {
    ring.magic = MAGIC; ring.head = 0; ring.used = 0;
  }
}

// printf-style line: "[mm:ss.s] text\n", to the ring and the serial port.
inline void logf(const char* fmt, ...) {
  char line[200];
  uint32_t ms = millis();
  int n = snprintf(line, sizeof line, "[%02lu:%02lu.%lu] ", (unsigned long)(ms / 60000), (unsigned long)(ms / 1000 % 60),
                   (unsigned long)(ms / 100 % 10));
  va_list ap; va_start(ap, fmt);
  int m = vsnprintf(line + n, sizeof line - n - 1, fmt, ap);
  va_end(ap);
  if (m < 0) m = 0;
  n += m; if (n > (int)sizeof line - 2) n = sizeof line - 2;
  line[n++] = '\n'; line[n] = 0;
  put(line, n);
  if (!quiet) Serial.write((const uint8_t*)line, n);
}

// Copy the log, oldest first, into out (NUL-terminated). Returns length.
inline size_t copy(char* out, size_t cap) {
  portENTER_CRITICAL(&mux);
  uint32_t used = ring.used, start = (ring.head + LOG_SIZE - used) % LOG_SIZE;
  size_t n = used < cap - 1 ? used : cap - 1;
  uint32_t skip = used - n;
  for (size_t i = 0; i < n; i++) out[i] = ring.buf[(start + skip + i) % LOG_SIZE];
  portEXIT_CRITICAL(&mux);
  // start at a line boundary
  size_t s = 0;
  if (used == LOG_SIZE || skip) { while (s < n && out[s] != '\n') s++; if (s < n) s++; }
  memmove(out, out + s, n - s);
  out[n - s] = 0;
  return n - s;
}

}  // namespace blog
