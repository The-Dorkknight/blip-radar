// Helper for tests/test_tracker_py.py: replays detections through the C++ tracker.
// stdin: one frame per line, "x y v x y v ..." (0–3 detections, v in cm/s)
// argv (optional): "strict" and/or "noclutter" switch those Cfg options on
// stdout: one line per frame, "id x y id x y ..." of the visible tracks
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cmath>
#include "tracker.h"

int main(int argc, char** argv) {
  blip_track::Tracker T;
  for (int i = 1; i < argc; i++) {
    if (!strcmp(argv[i], "strict")) T.cfg.strictGhost = true;
    if (!strcmp(argv[i], "noclutter")) T.cfg.noClutter = true;
  }
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
    T.update(f, 0.05f);
    rd03d::Frame o; uint16_t ids[3] = {0};
    T.visible(o, ids);
    for (int i = 0; i < 3; i++) if (o.t[i].present) printf("%u %d %d ", ids[i], o.t[i].x_mm, o.t[i].y_mm);
    printf("\n");
  }
  return 0;
}
