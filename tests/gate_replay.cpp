// Helper for tests/test_gate_py.py: replays frames through the C++ gate.
// argv: minMm maxDeg handheld(0|1) [stuckS]   stdin: one frame per line "x y v x y v ..." (v in cm/s)
// stdout: one line per frame: "why0 why1 why2 ego"
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include "gate.h"

int main(int argc, char** argv) {
  blip_gate::Gate G;
  if (argc > 3) { G.cfg.minMm = (uint16_t)atoi(argv[1]); G.cfg.maxDeg = (uint8_t)atoi(argv[2]); G.cfg.handheld = atoi(argv[3]) != 0; }
  if (argc > 4) G.cfg.stuckS = (uint8_t)atoi(argv[4]);
  char line[512];
  while (fgets(line, sizeof line, stdin)) {
    rd03d::Frame f; memset(&f, 0, sizeof f);
    char* p = line; int k = 0;
    while (k < 3) {
      char* e; long x = strtol(p, &e, 10); if (e == p) break; p = e;
      long y = strtol(p, &e, 10); p = e;
      long v = strtol(p, &e, 10); p = e;
      f.t[k].present = true; f.t[k].x_mm = (int16_t)x; f.t[k].y_mm = (int16_t)y; f.t[k].v_cms = (int16_t)v; f.count++; k++;
    }
    G.apply(f, 0.05f);
    printf("%d %d %d %.0f\n", G.why(0), G.why(1), G.why(2), G.ego());
  }
  return 0;
}
