// Renders the OLED picture on a PC with the firmware's own drawing code
// (firmware/include/oled_draw.h) and writes PBM files. Used by
// tools/draw_illustrations.py for the README previews, and as a smoke test.
//   g++ -std=c++17 -I firmware/include tests/oled_render.cpp -o /tmp/o && /tmp/o outdir
#include <cstdio>
#include <string>
#include "oled_draw.h"

static void save(const blip_oled::Canvas& c, const std::string& path) {
  FILE* f = fopen(path.c_str(), "w"); if (!f) return;
  fprintf(f, "P1\n%d %d\n", blip_oled::Canvas::W, c.H);
  for (int y = 0; y < c.H; y++) { for (int x = 0; x < blip_oled::Canvas::W; x++) fputc(c.get(x, y) ? '1' : '0', f); fputc('\n', f); }
  fclose(f);
}

int main(int argc, char** argv) {
  std::string dir = argc > 1 ? argv[1] : ".";
  // the same three people as the other README pictures: 1.9 m, 2.2 m, 5.4 m
  blip_oled::Blip b[3] = {{true, -782, 1713}, {true, 483, 2099}, {true, -2010, 5055}};
  blip_oled::Status st{true, false, true, 1, "192.168.4.1"};
  blip_oled::Canvas c;
  blip_oled::render(c, 64, b, 3, st); save(c, dir + "/oled-128x64.pbm");
  blip_oled::render(c, 32, b, 3, st); save(c, dir + "/oled-128x32.pbm");
  blip_oled::Status nophone{true, false, false, 0, "192.168.4.1"};
  blip_oled::render(c, 64, b, 3, nophone); save(c, dir + "/oled-128x64-nophone.pbm");
  blip_oled::Status off{false, false, false, 0, "192.168.4.1"};
  blip_oled::render(c, 64, b, 3, off); save(c, dir + "/oled-128x64-noradar.pbm");
  int lit = 0; blip_oled::render(c, 64, b, 3, st); for (int y = 0; y < 64; y++) for (int x = 0; x < 128; x++) lit += c.get(x, y);
  printf("rendered; %d pixels lit on the 128x64 picture\n", lit);
  return lit > 100 ? 0 : 1;
}
