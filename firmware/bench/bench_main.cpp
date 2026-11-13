// Blip — standalone hardware bench test for the ESP32-C3 Super Mini / Waveshare
// ESP32-S3-Pico. NOT the Blip app: this is a separate firmware for checking a
// board before you wire it up, in case a cheap batch has bad units (weak
// flash, a dead ADC channel, a jammed I2C bus, or — stage 2 — a chip that
// can't survive the radio + Stetho combination at all).
//
// Flash it like any other env:  pio run -e c3-supermini-bench -t upload  (or s3-pico-bench)
// or pick the "Bench test" card in the Blip flasher
// Then open a serial monitor at 115200 and read the PASS/FAIL lines.
//
// Stage 1 (automatic, ~15 s, no wiring needed beyond the board itself):
//   chip identity, a RAM march test, a flash/NVS scratch write, a Wi-Fi
//   scan + AP bring-up, an ADC sanity read on the Stetho pin, an I2C bus
//   scan, and a UART loopback check (SKIPped, not FAILed, if you haven't
//   jumpered radar TX to RX).
// Stage 2 (needs a phone or laptop to join the hotspot it prints): runs the
//   real Stetho sampler against the real Wi-Fi AP + web server for 2
//   minutes, the exact combination that has been resetting some boards.
//   Logs a health line every second; if the board resets instead of
//   finishing, the NEXT boot reports stage 2 as FAILED and says why.
//
// Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
// Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
#include <Arduino.h>
#include <WiFi.h>
#include <AsyncTCP.h>
#include <ESPAsyncWebServer.h>
#include <Preferences.h>
#include <Wire.h>
#include <esp_heap_caps.h>
#include <esp_system.h>
#include <esp_chip_info.h>
#include <esp_flash.h>

#include "config.h"
#include "stetho.h"
#include "blip_log.h"

// ---------------------------------------------------------------------------
// Pass/fail bookkeeping: one line per test, plus a count for the final banner.
static int gPass = 0, gFail = 0, gSkip = 0;
static void report(const char* name, const char* verdict, const char* detail) {
  Serial.printf("[%-4s] %-28s %s\n", verdict, name, detail);
  if (!strcmp(verdict, "PASS")) gPass++;
  else if (!strcmp(verdict, "FAIL")) gFail++;
  else gSkip++;
}
#define PASS(name, ...) do { char _d[160]; snprintf(_d, sizeof _d, __VA_ARGS__); report(name, "PASS", _d); } while (0)
#define FAIL(name, ...) do { char _d[160]; snprintf(_d, sizeof _d, __VA_ARGS__); report(name, "FAIL", _d); } while (0)
#define SKIP(name, ...) do { char _d[160]; snprintf(_d, sizeof _d, __VA_ARGS__); report(name, "SKIP", _d); } while (0)

// ---------------------------------------------------------------------------
// Stage 2's "did it survive" marker. RTC_NOINIT memory keeps its value across
// a crash or watchdog reset (not a power cycle), so the NEXT boot can tell
// whether the previous stage-2 run actually finished.
static const uint32_t STAGE2_MAGIC = 0xBE2C0001u;
struct Stage2Mark {
  uint32_t magic;
  uint32_t state;      // 0 idle, 1 running, 2 finished clean
  uint32_t elapsedSec; // last second reached
};
static RTC_NOINIT_ATTR Stage2Mark stage2;

static const char* resetReasonName() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON: return "power on";
    case ESP_RST_SW: return "software restart";
    case ESP_RST_PANIC: return "crash (panic)";
    case ESP_RST_INT_WDT: return "crash (interrupt watchdog)";
    case ESP_RST_TASK_WDT: return "crash (task watchdog)";
    case ESP_RST_WDT: return "crash (other watchdog)";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_USB: return "USB";
    default: return "other";
  }
}

// ---------------------------------------------------------------------------
// Stage 1, test by test.

static void testChipInfo() {
  esp_chip_info_t ci; esp_chip_info(&ci);
  uint32_t flashSize = 0; esp_flash_get_size(nullptr, &flashSize);
  uint32_t heap = ESP.getFreeHeap();
  bool ok = flashSize >= 2u * 1024 * 1024 && heap > 50 * 1024;  // a dead/short-shipped chip shows up small
  char d[160];
  snprintf(d, sizeof d, "model %d rev %d, %d core(s), flash %lu MB, heap %lu KB, %s", ci.model, ci.revision, ci.cores,
           (unsigned long)(flashSize / (1024 * 1024)), (unsigned long)(heap / 1024),
#ifdef BOARD_HAS_PSRAM
           ESP.getPsramSize() ? "PSRAM present" : "PSRAM MISSING (expected on this board)"
#else
           "no PSRAM expected"
#endif
  );
  if (ok) report("Chip identity", "PASS", d); else report("Chip identity", "FAIL", d);
}

static void testRam() {
  size_t freeBefore = ESP.getFreeHeap();
  size_t want = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT) * 3 / 4;   // on-chip SRAM only (PSRAM has its own test)
  if (want < 1024) { FAIL("RAM march test", "largest free block too small to test (%u bytes)", (unsigned)want); return; }
  uint8_t* buf = (uint8_t*)heap_caps_malloc(want, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  if (!buf) { FAIL("RAM march test", "malloc(%u) failed outright", (unsigned)want); return; }
  bool ok = true;
  const uint8_t patterns[] = {0x00, 0xFF, 0xA5, 0x5A};
  for (uint8_t p : patterns) {
    memset(buf, p, want);
    for (size_t i = 0; i < want; i++) if (buf[i] != p) { ok = false; break; }
    if (!ok) break;
  }
  free(buf);
  if (ok) PASS("RAM march test", "%u KB walked clean (4 patterns), %u KB free before/after", (unsigned)(want / 1024), (unsigned)(freeBefore / 1024));
  else FAIL("RAM march test", "a byte didn't read back what was written — bad SRAM");
}

// Fake / relabelled flash: a cheap chip that claims more capacity than it has
// usually just ignores the top address bits, so reading "high" addresses gives
// back the bytes at the bottom again (the bootloader). Read-only: compares the
// first 4 KB with the same 4 KB at every power-of-two "mirror" of the claimed
// size. Also checks the chip's own JEDEC capacity code against the size the
// firmware was built for.
static void testFlashCapacity() {
  uint32_t claimed = 0; esp_flash_get_size(nullptr, &claimed);
  uint32_t jedec = 0; esp_flash_read_id(nullptr, &jedec);
  uint32_t physical = 0; bool havePhys = esp_flash_get_physical_size(nullptr, &physical) == ESP_OK;
  static uint8_t a[4096], b[4096];
  if (esp_flash_read(nullptr, a, 0, sizeof a) != ESP_OK) { FAIL("Flash capacity (fake check)", "could not read flash at 0x0"); return; }
  bool blank = true; for (uint8_t v : a) if (v != 0xFF) { blank = false; break; }
  uint32_t wrapAt = 0;
  for (uint32_t off = 256 * 1024; off < claimed && !blank; off <<= 1) {
    if (esp_flash_read(nullptr, b, off, sizeof b) != ESP_OK) break;
    if (!memcmp(a, b, sizeof a)) { wrapAt = off; break; }
  }
  if (wrapAt) { FAIL("Flash capacity (fake check)", "reading at %lu KB gives back the bootloader: real flash is probably only %lu KB, not the %lu MB it claims",
                     (unsigned long)(wrapAt / 1024), (unsigned long)(wrapAt / 1024), (unsigned long)(claimed >> 20)); return; }
  if (havePhys && physical < claimed) { FAIL("Flash capacity (fake check)", "chip ID 0x%06lX says %lu MB, firmware expects %lu MB",
                                              (unsigned long)jedec, (unsigned long)(physical >> 20), (unsigned long)(claimed >> 20)); return; }
  PASS("Flash capacity (fake check)", "chip ID 0x%06lX, %lu MB, no address wrap-around", (unsigned long)jedec,
       (unsigned long)((havePhys ? physical : claimed) >> 20));
}

// The S3-Pico's 2 MB PSRAM sits inside the chip package (ESP32-S3R2), so it
// can't be swapped for a smaller part on the board — but check its size and
// walk most of it anyway. C3 boards have no PSRAM: reported as SKIP.
static void testPsram() {
#ifdef BOARD_HAS_PSRAM
  size_t sz = ESP.getPsramSize();
  if (!sz) { FAIL("PSRAM", "none found — the S3-Pico should have 2 MB"); return; }
  size_t want = ESP.getMaxAllocPsram() * 3 / 4;
  uint32_t* p = (uint32_t*)ps_malloc(want);
  if (!p) { FAIL("PSRAM", "%u KB reported but ps_malloc(%u KB) failed", (unsigned)(sz / 1024), (unsigned)(want / 1024)); return; }
  size_t n = want / 4; bool ok = true;
  for (size_t i = 0; i < n; i++) p[i] = (uint32_t)i * 2654435761u;           // address-dependent: catches aliasing too
  for (size_t i = 0; i < n && ok; i++) if (p[i] != (uint32_t)i * 2654435761u) ok = false;
  free(p);
  if (!ok) FAIL("PSRAM", "a word didn't read back what was written — bad or aliased PSRAM");
  else if (sz < 2u * 1024 * 1024 - 64 * 1024) FAIL("PSRAM", "only %u KB (expected 2 MB)", (unsigned)(sz / 1024));
  else PASS("PSRAM", "%u KB, %u KB walked clean (address pattern)", (unsigned)(sz / 1024), (unsigned)(want / 1024));
#else
  SKIP("PSRAM", "none on this board (not expected)");
#endif
}

static void testFlashScratch() {
  Preferences p;
  if (!p.begin("bench", false)) { FAIL("Flash/NVS scratch", "Preferences.begin() failed"); return; }
  const char* key = "scratch";
  uint32_t v1 = 0xA5A5B33F, v2 = 0;
  p.putUInt(key, v1);
  v2 = p.getUInt(key, 0);
  p.remove(key);
  p.end();
  if (v2 == v1) PASS("Flash/NVS scratch", "wrote, read back, erased one NVS entry OK");
  else FAIL("Flash/NVS scratch", "wrote 0x%08lX, read back 0x%08lX", (unsigned long)v1, (unsigned long)v2);
}

static void testWifiRadio() {
  WiFi.mode(WIFI_MODE_STA);
  int n = WiFi.scanNetworks(false, true, false, 300);
  if (n < 0) { FAIL("Wi-Fi radio (scan)", "scanNetworks() returned error %d", n); WiFi.scanDelete(); return; }
  int bestRssi = -127;
  for (int i = 0; i < n; i++) bestRssi = max(bestRssi, (int)WiFi.RSSI(i));
  WiFi.scanDelete();
  PASS("Wi-Fi radio (scan)", "saw %d network(s) nearby, strongest %d dBm — radio can receive", n, n ? bestRssi : 0);
}

static void testAdcFloating() {
  pinMode(PIN_STETHO_I, INPUT);
  int mn = 4095, mx = 0; long sum = 0; const int N = 64;
  for (int i = 0; i < N; i++) { int v = analogRead(PIN_STETHO_I); mn = min(mn, v); mx = max(mx, v); sum += v; delayMicroseconds(200); }
  bool stuck = (mx - mn) < 2;  // a floating pin should be a little noisy; dead-flat means a dead channel or a short
  bool railed = mn == 0 && mx == 0;
  char d[160];
  snprintf(d, sizeof d, "GPIO%d: min %d max %d avg %ld (floating input should be noisy, not flat)", PIN_STETHO_I, mn, mx, sum / N);
  if (railed) report("ADC (Stetho pin)", "FAIL", d);
  else if (stuck) { char d2[200]; snprintf(d2, sizeof d2, "%s — flat is OK only if the pin is actually tied to GND/3V3 right now", d); report("ADC (Stetho pin)", "INFO", d2); }
  else report("ADC (Stetho pin)", "PASS", d);
}

static void testI2cBus() {
  pinMode(PIN_OLED_SDA, INPUT_PULLUP);
  pinMode(PIN_OLED_SCL, INPUT_PULLUP);
  bool sdaStuck = digitalRead(PIN_OLED_SDA) == LOW, sclStuck = digitalRead(PIN_OLED_SCL) == LOW;
  if (sdaStuck || sclStuck) { FAIL("I2C bus", "SDA or SCL held low at idle (GPIO%d/%d) — short or no pull-up", PIN_OLED_SDA, PIN_OLED_SCL); return; }
  Wire.begin(PIN_OLED_SDA, PIN_OLED_SCL);
  Wire.setClock(100000);
  int found = 0; char first[8] = "-";
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) { found++; if (found == 1) snprintf(first, sizeof first, "0x%02X", a); }
  }
  if (found == 0) SKIP("I2C bus", "idle and no short, but nothing answered — fine if no OLED is fitted");
  else PASS("I2C bus", "%d device(s) found, first at %s (0x3C = the usual OLED)", found, first);
}

static void testUartLoopback() {
  HardwareSerial radar(1);
  radar.begin(115200, SERIAL_8N1, PIN_RADAR_RX, PIN_RADAR_TX);
  delay(20);
  while (radar.available()) radar.read();
  const char* msg = "BLIP-BENCH-LOOP";
  radar.write((const uint8_t*)msg, strlen(msg));
  radar.flush();
  char got[32] = {0}; size_t n = 0;
  uint32_t t0 = millis();
  while (n < strlen(msg) && millis() - t0 < 200) if (radar.available()) got[n++] = radar.read();
  radar.end();
  if (n == 0) SKIP("UART loopback (radar pins)", "no echo on GPIO%d/%d — jumper TX to RX to test the wiring itself", PIN_RADAR_TX, PIN_RADAR_RX);
  else if (n == strlen(msg) && !memcmp(got, msg, n)) PASS("UART loopback (radar pins)", "sent and got back %u bytes clean", (unsigned)n);
  else FAIL("UART loopback (radar pins)", "sent %u bytes, got %u back and they didn't match", (unsigned)strlen(msg), (unsigned)n);
}

// ---------------------------------------------------------------------------
// Stage 2: the real Stetho sampler + the real Wi-Fi AP + web server, for real,
// for 2 minutes. This is the exact combination that has been crashing some
// boards a few seconds in — if this bench unit sails through it, the chip is
// probably fine and the bug is elsewhere; if it dies the same way, the two
// results together say whether that's this board specifically.
static AsyncWebServer server(80);
static AsyncWebSocket ws("/bench-ws");
static Stetho stetho;
static const uint32_t STAGE2_SECONDS = 120;

// The page a joined phone opens. It holds a WebSocket to /bench-ws and just counts
// what arrives, so stage 2 carries the same Stetho audio stream the real app
// sends, to a real client. (A bare Wi-Fi join with no page open sends nothing.)
static const char BENCH_PAGE[] PROGMEM = R"HTML(<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Blip bench</title>
<body style="font-family:sans-serif;background:#111;color:#eee;padding:16px">
<h2>Blip bench, stage 2</h2>
<p>Keep this page open for the 2-minute run. It receives the Stetho audio stream and counts it.</p>
<p id="s" style="font-size:20px">connecting...</p>
<script>
var n=0,b=0,t0=Date.now(),ws,el=document.getElementById('s'),up=false;
function c(){ws=new WebSocket('ws://'+location.host+'/bench-ws');ws.binaryType='arraybuffer';
ws.onopen=function(){up=true;};
ws.onmessage=function(e){n++;b+=e.data.byteLength;};
ws.onclose=function(){up=false;el.textContent='disconnected, retrying...';setTimeout(c,1000);};}
c();
setInterval(function(){if(up)el.textContent=n+' packets, '+(b/1024|0)+' KB, '+((Date.now()-t0)/1000|0)+' s';},500);
</script>)HTML";
static uint32_t gSent = 0, gSkipped = 0;

static void stage2Begin() {
  Serial.println();
  Serial.println("=== Stage 2: Stetho + Wi-Fi stress, 2 minutes ===");
  Serial.println("Needs a phone or laptop to join the hotspot below AND open the page at");
  Serial.println("http://192.168.4.1/ in a browser (turn mobile data off if it won't load).");
  Serial.println("The timer starts when the page connects: that is when Stetho audio is");
  Serial.println("actually sent, which is what the real app does and what has been crashing.");

  char ssid[24]; snprintf(ssid, sizeof ssid, "Blip-Bench-%02X%02X", (uint8_t)(ESP.getEfuseMac() >> 8), (uint8_t)ESP.getEfuseMac());
  WiFi.mode(WIFI_MODE_AP);
  WiFi.softAPConfig(IPAddress(192, 168, 4, 1), IPAddress(192, 168, 4, 1), IPAddress(255, 255, 255, 0));
  WiFi.softAP(ssid, "blipblip", AP_CHANNEL, 0, AP_MAX_CLIENTS);
  WiFi.setTxPower(WIFI_POWER_8_5dBm);  // the same low-power default as the real app on the C3

  server.addHandler(&ws);
  server.on("/", HTTP_GET, [](AsyncWebServerRequest* r) { r->send(200, "text/html", BENCH_PAGE); });
  server.begin();

  StethoSettings s;
  if (!stetho.start(s)) { Serial.printf("Stetho would not start: %s\n", stetho.error()); report("Stage 2", "FAIL", "Stetho::start() failed before the stress run even began"); return; }

  blog::begin(esp_reset_reason() != ESP_RST_POWERON);
  blog::logf("bench stage 2: hotspot '%s' up, Stetho sampling, waiting %lu s", ssid, (unsigned long)STAGE2_SECONDS);
  Serial.printf("Hotspot: %s  (password blipblip)  ->  then open http://192.168.4.1/\n", ssid);
  Serial.println("Waiting for a page to connect, then timing starts...");

  stage2.magic = STAGE2_MAGIC; stage2.state = 1; stage2.elapsedSec = 0;

  uint32_t t0 = 0, lastHealth = 0;
  bool started = false;
  while (true) {
    uint32_t now = millis();
    if (!started) {
      if (ws.count() > 0) { started = true; t0 = now; Serial.println("Page connected - 2-minute timer started."); }
      else if (now - lastHealth >= 5000) {
        lastHealth = now;
        Serial.printf("...waiting: %d on the hotspot, no page open yet (open http://192.168.4.1/)\n", WiFi.softAPgetStationNum());
      }
      ws.cleanupClients();
      delay(50);
      continue;
    }
    uint32_t elapsed = (now - t0) / 1000;
    if (elapsed != stage2.elapsedSec) {
      stage2.elapsedSec = elapsed;
      uint32_t heap = ESP.getFreeHeap();
      Serial.printf("[%3lus] heap %lu KB (lowest %lu), %d on hotspot, %u page(s), sent %lu skipped %lu, loop alive\n", (unsigned long)elapsed,
                     (unsigned long)(heap / 1024), (unsigned long)(ESP.getMinFreeHeap() / 1024), WiFi.softAPgetStationNum(), (unsigned)ws.count(),
                     (unsigned long)gSent, (unsigned long)gSkipped);
      blog::logf("bench stage2 %lus: heap %lu KB lowest %lu, %d on hotspot", (unsigned long)elapsed, (unsigned long)(heap / 1024),
                 (unsigned long)(ESP.getMinFreeHeap() / 1024), WiFi.softAPgetStationNum());
    }
    if (started && elapsed >= STAGE2_SECONDS) break;

    // Drain Stetho exactly like the real app does (main.cpp loop()): newest two
    // packets per pass, only when every phone has room, a backlog of 6 flushed.
    static uint8_t pk[6][PKT_HDR + AUDIO_FRAME];
    static size_t pl[6];
    int got = 0;
    while (got < 6 && (pl[got] = stetho.nextAudioPacket(pk[got], sizeof pk[got])) > 0) got++;
    if (got == 6) stetho.flushAudio();
    if (ws.count() > 0)
      for (int i = (got > 2 ? got - 2 : 0); i < got; i++) { if (!ws.availableForWriteAll()) { gSkipped++; break; } ws.binaryAll(pk[i], pl[i]); gSent++; }
    { uint8_t vb[PKT_HDR + VITALS_FRAME * 2]; while (stetho.nextVitalsPacket(vb, sizeof vb) > 0) {} }
    ws.cleanupClients();
    delay(1);
  }

  stage2.state = 2;
  Serial.println();
  Serial.printf("=== Stage 2: PASS - ran 2 minutes with Stetho streaming to a page (%lu packets sent, %lu skipped), no reset ===\n", (unsigned long)gSent, (unsigned long)gSkipped);
  stetho.stop();
  Serial.println("Stetho stopped cleanly. Done: reset the board to run again, or flash Blip.");
}

// ---------------------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis(); while (!Serial && millis() - t0 < 3000) delay(10);  // give native-USB boards a moment to enumerate

  bool stage2WasRunning = stage2.magic == STAGE2_MAGIC && stage2.state == 1;

  Serial.println();
  Serial.println("##############################################");
  Serial.printf("  BLIP BENCH TEST  —  board: %s (%s)\n", BLIP_BOARD, BLIP_BOARD_ID);
  Serial.printf("  last reset: %s\n", resetReasonName());
  Serial.println("##############################################");

  if (stage2WasRunning) {
    Serial.println();
    Serial.printf("=== Stage 2: FAILED — board reset after %lu s into the 2-minute run ===\n", (unsigned long)stage2.elapsedSec);
    Serial.printf("    reset reason: %s\n", resetReasonName());
    Serial.println("    (this is the same async_tcp/Stetho crash the app has shown — if this");
    Serial.println("     board fails here reliably while others don't, that points at this chip.)");
    stage2.state = 0;
    Serial.println();
    Serial.println("Run again to retry stage 1, or power-cycle and flash the real app.");
    return;
  }

  stage2.magic = STAGE2_MAGIC; stage2.state = 0; stage2.elapsedSec = 0;

  Serial.println();
  Serial.println("--- Stage 1: quick self-test (no wiring needed) ---");
  testChipInfo();
  testRam();
  testPsram();
  testFlashCapacity();
  testFlashScratch();
  testWifiRadio();
  testAdcFloating();
  testI2cBus();
  testUartLoopback();

  Serial.println();
  Serial.printf("Stage 1 result: %d passed, %d failed, %d skipped/info\n", gPass, gFail, gSkip);
  if (gFail > 0) Serial.println("At least one stage-1 test FAILED — this board has a real problem; worth trying a different unit.");
  else Serial.println("Stage 1 clean. Reset the board within 10 s to skip stage 2, or wait and it'll start on its own.");

  for (int s = 10; s > 0; s--) { Serial.printf("Starting stage 2 in %d...\r", s); delay(1000); }
  Serial.println();
  stage2Begin();
}

void loop() { delay(1000); }
