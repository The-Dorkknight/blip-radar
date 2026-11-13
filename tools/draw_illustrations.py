#!/usr/bin/env python3
"""Blip — draws the wiring diagrams, the MAX4466 mod + audio-out diagram, the
DSP before/after chart, OLED previews and the Doppler-physics chart used in
the README, DESIGN_NOTES and the Pages site.

Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.

    python3 tools/draw_illustrations.py          # writes docs/images/*.webp (+ .svg sources)

Pin numbers are read from firmware/platformio.ini so the pictures cannot drift
from the firmware. The OLED previews are rendered by the firmware's own
drawing code (firmware/include/oled_draw.h) compiled for the PC.
"""
import math
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "docs", "images")
os.makedirs(IMG, exist_ok=True)

GREEN, BG, LINE, DIM, TXT = "#39ff8a", "#06120b", "#1f6b3f", "#7fb597", "#d9f5e3"


def pins_from_ini():
    ini = open(os.path.join(ROOT, "firmware", "platformio.ini")).read()
    out = {}
    for env in ("c3-supermini", "s3-pico"):
        block = ini.split(f"[env:{env}]")[1].split("\n[")[0]
        out[env] = {k: int(v) for k, v in re.findall(r"-DPIN_(\w+)=(-?\d+)", block)}
    return out


def wiring_svg(env, board_name, pins, filename, board_pins_note):
    W, H = 1040, 760
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="DejaVu Sans, Arial, sans-serif">',
         f'<rect width="{W}" height="{H}" fill="{BG}"/>',
         f'<text x="20" y="34" fill="{GREEN}" font-size="22" font-weight="bold">Blip wiring — {board_name}</text>',
         f'<text x="20" y="56" fill="{DIM}" font-size="13">Pins from firmware/platformio.ini env:{env}.</text>',
         f'<text x="20" y="74" fill="{DIM}" font-size="13">{board_pins_note}</text>']

    def box(x, y, w, h, title, lines, col=GREEN):
        s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#0b1d12" stroke="{col}" stroke-width="2"/>')
        s.append(f'<text x="{x + 12}" y="{y + 26}" fill="{col}" font-size="16" font-weight="bold">{title}</text>')
        for i, ln in enumerate(lines):
            s.append(f'<text x="{x + 12}" y="{y + 50 + i * 20}" fill="{TXT}" font-size="14">{ln}</text>')

    def wire(x1, y1, x2, y2, label, col, ly=-7, fx=0.5):
        s.append(f'<path d="M{x1},{y1} C{(x1 + x2) / 2},{y1} {(x1 + x2) / 2},{y2} {x2},{y2}" fill="none" stroke="{col}" stroke-width="3"/>')
        s.append(f'<text x="{x1 + (x2 - x1) * fx}" y="{y1 + (y2 - y1) * fx + ly}" fill="{col}" font-size="12" text-anchor="middle">{label}</text>')

    L, LW = 30, 250            # left column
    mx, mw = 400, 250          # mcu column
    R, RW = 760, 260           # right column
    box(mx, 100, mw, 400, board_name, [
        "USB-C: power + flashing",
        f"GPIO{pins['RADAR_RX']}  ← radar TX",
        f"GPIO{pins['RADAR_TX']}  → radar RX",
        f"GPIO{pins['OLED_SDA']}  SDA",
        f"GPIO{pins['OLED_SCL']}  SCL",
        f"GPIO{pins['STETHO_I']}  ADC ← MAX4466 OUT",
        f"GPIO{pins['PDM_OUT']}  earphones (delta-sigma)",
        f"GPIO{pins['I2S_BCLK']}/{pins['I2S_WS']}/{pins['I2S_DOUT']}  I2S BCLK/WS/DIN",
        "5V / VBUS → radar, CDM324",
        "3V3 → OLED, MAX4466",
        "GND common to all",
        "LED: slow blink = no radar," if pins.get("STATUS_LED", -1) >= 0 else "(no status LED here)",
        "fast blink = frames flowing" if pins.get("STATUS_LED", -1) >= 0 else "",
    ])
    box(L, 100, LW, 150, "Ai-Thinker RD-03D", ["5V  (≥200 mA, ripple <100 mV)", "GND", "TX  3.3 V logic, 256000 8N1", "RX"], "#5ad0ff")
    box(L, 300, LW, 140, "SSD1306 OLED (optional)", ['0.91" 128×32 or 0.96" 128×64', "VCC → 3V3,  GND", "SDA, SCL  (I2C address 0x3C)", "Pick the size in Settings"], "#ffd34d")
    box(R, 100, RW, 170, "Stetho (optional)", ["CDM324 / HB100 IF pin", "→ MAX4466 board, mic and", "   mic bias resistor removed", "see hardware/max4466-mod.md", "NOT a medical device"], "#ff8fd6")
    box(R, 300, RW, 170, "Audio out (optional)", [f"Earphones: GPIO{pins['PDM_OUT']} → 470 Ω", "  → 100 nF to GND → 220 µF", "  → 3.5 mm tip + ring", "I2S amp: MAX98357A board,", "  VIN 5 V, 4–8 Ω speaker"], "#c9a0ff")
    box(R, 500, RW, 130, "Old phone", ["Join Wi-Fi: Blip-Radar", "password: blipblip", "open http://192.168.4.1/", "(the captive portal opens it)"], GREEN)
    # radar wires (left box right edge -> mcu left edge)
    wire(L + LW, 140, mx, 140, "5 V", "#ff5c5c", ly=-6, fx=0.25)
    wire(L + LW, 164, mx, 164, "GND", "#9aa", ly=-6, fx=0.75)
    wire(L + LW, 188, mx, 188, f"TX → GPIO{pins['RADAR_RX']}", "#5ad0ff", ly=-6, fx=0.4)
    wire(L + LW, 212, mx, 212, f"RX ← GPIO{pins['RADAR_TX']}", "#5ad0ff", ly=14, fx=0.6)
    # oled wires
    wire(L + LW, 365, mx, 250, f"SDA → GPIO{pins['OLED_SDA']}", "#ffd34d", ly=-10)
    wire(L + LW, 385, mx, 270, f"SCL → GPIO{pins['OLED_SCL']}", "#ffd34d", ly=16)
    # amp wires
    wire(mx + mw, 230, R, 185, f"OUT→GPIO{pins['STETHO_I']}", "#ff8fd6", ly=-12, fx=0.45)
    wire(mx + mw, 250, R, 205, "power", "#ff5c5c", ly=18, fx=0.45)
    wire(mx + mw, 330, R, 380, "audio", "#c9a0ff", ly=-12, fx=0.45)
    # wifi
    s.append(f'<path d="M{mx + mw},480 C 700,480 700,600 {R},600" fill="none" stroke="{GREEN}" stroke-width="2" stroke-dasharray="6 5"/>')
    s.append(f'<text x="705" y="560" fill="{GREEN}" font-size="12" text-anchor="middle">Wi-Fi hotspot</text>')
    s.append(f'<text x="20" y="{H - 60}" fill="{DIM}" font-size="12">Keep the radar wires short. 5 V from the ESP32 board\'s USB/5V pin is fine for a bench test; never power the radar from 3V3.</text>')
    s.append(f'<text x="20" y="{H - 40}" fill="{DIM}" font-size="12">Radar TX/RX are 3.3 V logic, so no level shifter is needed. OLED and amp are optional: leave them off and Blip still works.</text>')
    s.append(f'<text x="20" y="{H - 20}" fill="{DIM}" font-size="12">Firmware compiles for this board; not verified on real hardware yet (v0.2.0-wip). Drawn by tools/draw_illustrations.py.</text>')
    s.append('</svg>')
    open(os.path.join(IMG, filename), "w").write("\n".join(s))


def max4466_svg():
    """CDM324 -> modded MAX4466 board -> ESP32, the DC warning, and the earphone filter."""
    W, H = 1040, 700
    P, WARN, OUTC = "#ff8fd6", "#ff5c5c", "#c9a0ff"
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="DejaVu Sans, Arial, sans-serif">',
         f'<rect width="{W}" height="{H}" fill="{BG}"/>',
         f'<defs><marker id="a" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="{GREEN}"/></marker></defs>',
         f'<text x="20" y="34" fill="{P}" font-size="22" font-weight="bold">Stetho front end — CDM324 into a modded MAX4466 board</text>',
         f'<text x="20" y="56" fill="{DIM}" font-size="13">No op-amp biasing to build: the MAX4466 board already has its mid-rail bias, gain pot and coupling caps. Not yet built and measured.</text>']
    blocks = [
        (20, "CDM324 / HB100", ["5 V, ~30–40 mA", "IF pin: µV–mV", "24 GHz: 160 Hz/(m/s)", "10.5 GHz: 70 Hz/(m/s)"]),
        (225, "MAX4466 board", ["mic capsule removed", "bias resistor removed", "gain pot ×25–×125", "3V3: OUT idles 1.65 V"]),
        (430, "ESP32 ADC (DMA)", ["8 kHz, 12-bit", "DC tracker removes", "the 1.65 V idle level", "rail = shock flag"]),
        (635, "DSP on the ESP32", ["bump gate", "EQ: heart/lungs/voice", "4-band noise cut", "AGC + limiter"]),
    ]
    for x, title, lines in blocks:
        s.append(f'<rect x="{x}" y="80" width="175" height="140" rx="10" fill="#0b1d12" stroke="{P}" stroke-width="2"/>')
        s.append(f'<text x="{x + 10}" y="106" fill="{P}" font-size="15" font-weight="bold">{title}</text>')
        for i, ln in enumerate(lines):
            s.append(f'<text x="{x + 10}" y="{130 + i * 20}" fill="{TXT}" font-size="13">{ln}</text>')
        s.append(f'<path d="M{x + 175},150 L{x + 200},150" stroke="{GREEN}" stroke-width="3" marker-end="url(#a)"/>')
    outs = [(80, "Phone (WebSocket)", "16 ms packets, ~40 ms buffer"), (130, "3.5 mm earphones", "delta-sigma (I2S PDM) + RC"), (180, "I2S amp + speaker", "MAX98357A board")]
    for y, t, sub in outs:
        s.append(f'<rect x="840" y="{y}" width="185" height="44" rx="8" fill="#0b1d12" stroke="{OUTC}" stroke-width="2"/>')
        s.append(f'<text x="850" y="{y + 19}" fill="{OUTC}" font-size="12" font-weight="bold">{t}</text>')
        s.append(f'<text x="850" y="{y + 36}" fill="{DIM}" font-size="10">{sub}</text>')
    # warning panel
    s.append(f'<rect x="20" y="250" width="1000" height="150" rx="10" fill="#2a0b0b" stroke="{WARN}" stroke-width="2"/>')
    s.append(f'<text x="36" y="278" fill="{WARN}" font-size="17" font-weight="bold">⚠  DC on the old mic pads — read before you solder</text>')
    warn = ["The pad the mic's + leg used is pulled up to VCC through the mic bias resistor (~2 kΩ). Wire the radar's IF pin straight onto it and",
            "that DC (~1.5 mA) is pushed into the CDM324's mixer diode: best case a shifted, noisy IF, worst case a damaged module.",
            "Fix it one of two ways:  (1) remove (or cut the track to) the bias resistor, and keep the board's own coupling cap — it does the DC blocking;",
            "or  (2) leave the board alone and put a DC-blocking cap in series with the IF lead (10–47 µF, + towards the MAX4466 pad).",
            "Never connect the IF pin to MAX4466 OUT or VCC. Power the MAX4466 from 3V3 so its output stays inside the ESP32 ADC range."]
    for i, w in enumerate(warn):
        s.append(f'<text x="36" y="{304 + i * 19}" fill="{TXT}" font-size="12.5">{w}</text>')
    # earphone filter schematic
    y0 = 500
    s.append(f'<text x="20" y="{y0 - 50}" fill="{OUTC}" font-size="17" font-weight="bold">Earphone output (delta-sigma) — one pin, three parts</text>')
    s.append(f'<text x="40" y="{y0 + 5}" fill="{TXT}" font-size="14">GPIO (PDM)</text>')
    s.append(f'<path d="M130,{y0} L200,{y0}" stroke="{OUTC}" stroke-width="2"/>')
    s.append(f'<rect x="200" y="{y0 - 10}" width="70" height="20" fill="none" stroke="{OUTC}" stroke-width="2"/><text x="235" y="{y0 - 16}" fill="{TXT}" font-size="12" text-anchor="middle">470 Ω</text>')
    s.append(f'<path d="M270,{y0} L420,{y0}" stroke="{OUTC}" stroke-width="2"/><circle cx="330" cy="{y0}" r="4" fill="{OUTC}"/>')
    s.append(f'<path d="M330,{y0} L330,{y0 + 40} M315,{y0 + 40} L345,{y0 + 40} M315,{y0 + 48} L345,{y0 + 48} M330,{y0 + 48} L330,{y0 + 80} M318,{y0 + 80} L342,{y0 + 80} M323,{y0 + 86} L337,{y0 + 86}" stroke="{OUTC}" stroke-width="2" fill="none"/>')
    s.append(f'<text x="352" y="{y0 + 50}" fill="{TXT}" font-size="12">100 nF (≈3.4 kHz low-pass)</text>')
    s.append(f'<path d="M420,{y0 - 14} L420,{y0 + 14} M432,{y0 - 14} L432,{y0 + 14}" stroke="{OUTC}" stroke-width="3"/><text x="410" y="{y0 - 20}" fill="{TXT}" font-size="12">+</text>')
    s.append(f'<text x="426" y="{y0 + 32}" fill="{TXT}" font-size="12" text-anchor="middle">220 µF</text>')
    s.append(f'<path d="M432,{y0} L560,{y0}" stroke="{OUTC}" stroke-width="2"/>')
    s.append(f'<text x="570" y="{y0 + 5}" fill="{TXT}" font-size="14">3.5 mm tip + ring (both ears, mono) · sleeve → GND</text>')
    notes = ["The ESP32's I2S peripheral in PDM mode outputs a 1-bit delta-sigma stream (~2 MHz). The RC smooths it into audio; the 220 µF blocks the 1.65 V average",
             "and, with a 32 Ω earphone, keeps the bass down to ~20 Hz (heart sounds live at 20–150 Hz). Start with Node volume low. One output at a time:",
             "earphones OR the I2S amp. The amp board (MAX98357A): VIN 5 V, GND, BCLK, LRC → WS, DIN; GAIN and SD left open; 4–8 Ω speaker on its terminals."]
    for i, n in enumerate(notes):
        s.append(f'<text x="20" y="{y0 + 130 + i * 20}" fill="{DIM}" font-size="12">{n}</text>')
    s.append('</svg>')
    open(os.path.join(IMG, "max4466-mod.svg"), "w").write("\n".join(s))


def dsp_chart():
    """Before/after of the firmware DSP on the synthetic test scene (tests/test_audio_dsp.cpp writes the CSV)."""
    import csv
    import subprocess
    import tempfile
    tmp = tempfile.mkdtemp()
    exe = os.path.join(tmp, "t")
    subprocess.run(["g++", "-std=c++17", "-O2", "-I", os.path.join(ROOT, "firmware", "include"),
                    os.path.join(ROOT, "tests", "test_audio_dsp.cpp"), "-o", exe], check=True)
    subprocess.run([exe, tmp], check=True, stdout=subprocess.DEVNULL)
    rows = list(csv.DictReader(open(os.path.join(tmp, "dsp_trace.csv"))))
    t = [float(r["t"]) for r in rows]
    xin = [int(r["in"]) for r in rows]
    xout = [int(r["out"]) for r in rows]
    kind = [int(r["kind"]) for r in rows]
    plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": "#0b1d12", "axes.edgecolor": LINE, "axes.labelcolor": TXT,
                         "xtick.color": DIM, "ytick.color": DIM, "text.color": TXT, "grid.color": LINE})
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 5), dpi=110, sharex=True)
    lo, hi = 11.0, 17.0
    sel = [i for i, v in enumerate(t) if lo <= v <= hi]
    a1.plot([t[i] for i in sel], [xin[i] for i in sel], color="#5ad0ff", lw=0.6)
    a1.set_ylabel("into the ESP32")
    a1.set_title("Synthetic scene: heart sounds (72 bpm) + noise + a knock every 3.3 s", fontsize=11)
    a2.plot([t[i] for i in sel], [xout[i] for i in sel], color=GREEN, lw=0.6)
    a2.set_ylabel("after the DSP")
    a2.set_xlabel("seconds  (heart preset, default settings; the knocks are ducked ~30 dB, the hiss between beats is cut)")
    for ax in (a1, a2):
        ax.grid(True, alpha=0.3)
        for i in sel:
            if kind[i] == 2 and (i == 0 or kind[i - 1] != 2):
                ax.axvspan(t[i], t[i] + 0.06, color="#ff5c5c", alpha=0.25, lw=0)
    fig.tight_layout()
    png = os.path.join(IMG, "dsp-demo.png")
    fig.savefig(png)
    Image.open(png).save(os.path.join(IMG, "dsp-demo.webp"), "WEBP", quality=90)
    os.remove(png)
    ex = os.path.join(ROOT, "examples")
    import shutil
    for n in ("dsp_before.wav", "dsp_after.wav"):
        shutil.copy(os.path.join(tmp, n), os.path.join(ex, n))


def oled_previews():
    """Compiles tests/oled_render.cpp, which runs the firmware's own OLED drawing
    code (firmware/include/oled_draw.h) on the PC, and enlarges the result with a
    pixel-grid look. What you see is exactly what the firmware draws."""
    import subprocess
    import tempfile
    tmp = tempfile.mkdtemp()
    exe = os.path.join(tmp, "oled")
    subprocess.run(["g++", "-std=c++17", "-O2", "-I", os.path.join(ROOT, "firmware", "include"),
                    os.path.join(ROOT, "tests", "oled_render.cpp"), "-o", exe], check=True)
    subprocess.run([exe, tmp], check=True, stdout=subprocess.DEVNULL)
    for name, col in (("oled-128x64", (255, 240, 200)), ("oled-128x32", (90, 210, 255)), ("oled-128x64-nophone", (255, 240, 200))):
        im = Image.open(os.path.join(tmp, name + ".pbm")).convert("L")
        W, H = im.size
        scale = 5
        big = Image.new("RGB", (W * scale + 20, H * scale + 20), (20, 20, 24))
        px = im.load()
        bd = ImageDraw.Draw(big)
        for yy in range(H):
            for xx in range(W):
                if px[xx, yy] == 0:          # PBM: 1 = black = lit pixel after convert
                    bd.rectangle([10 + xx * scale, 10 + yy * scale, 10 + xx * scale + scale - 2, 10 + yy * scale + scale - 2], fill=col)
        big.save(os.path.join(IMG, name + ".webp"), "WEBP", lossless=True)


def physics_chart():
    freqs = {"HB100 10.5 GHz": 10.525e9, "CDM324 / RD-03D 24 GHz": 24.125e9, "60 GHz (MR60BHA1 class)": 60e9}
    motions = [("breathing ~5 mm", 5e-3), ("heartbeat ~0.4 mm", 0.4e-3)]
    plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": "#0b1d12", "axes.edgecolor": LINE, "axes.labelcolor": TXT,
                         "xtick.color": DIM, "ytick.color": DIM, "text.color": TXT, "grid.color": LINE})
    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=110)
    xs = range(len(freqs))
    width = 0.36
    for k, (label, amp) in enumerate(motions):
        vals = [4 * math.pi * amp / (3e8 / f) for f in freqs.values()]   # phase swing (rad) = 4π·Δx/λ
        bars = ax.bar([x + (k - 0.5) * width for x in xs], vals, width, label=label, color=[GREEN, "#5ad0ff"][k])
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v * 1.05, f"{v:.2f} rad", ha="center", fontsize=9, color=TXT)
    ax.set_yscale("log")
    ax.set_xticks(list(xs))
    ax.set_xticklabels(list(freqs.keys()))
    ax.set_ylabel("round-trip phase swing (rad)")
    ax.set_title("Chest motion as Doppler phase swing, 4π·Δx/λ  —  higher frequency = bigger signal", fontsize=11)
    ax.axhline(2 * math.pi, ls="--", color="#ffb347", lw=1)
    ax.text(2.45, 2 * math.pi * 1.1, "one full cycle (2π)", color="#ffb347", fontsize=9, ha="right")
    ax.grid(True, axis="y", alpha=0.4)
    ax.legend(facecolor="#0b1d12", edgecolor=LINE)
    fig.tight_layout()
    fig.savefig(os.path.join(IMG, "doppler-physics.png"))
    Image.open(os.path.join(IMG, "doppler-physics.png")).save(os.path.join(IMG, "doppler-physics.webp"), "WEBP", quality=92)
    os.remove(os.path.join(IMG, "doppler-physics.png"))


def svg_to_webp(name):
    """Render an SVG with Chromium (Playwright) and save as WebP."""
    from playwright.sync_api import sync_playwright
    src = os.path.join(IMG, name)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1100, "height": 650}, device_scale_factor=2)
        svg = open(src, encoding="utf-8").read()
        pg.set_content(f'<html><body style="margin:0;background:{BG}">{svg}</body></html>')
        pg.wait_for_timeout(300)
        png = os.path.join(IMG, name.replace(".svg", ".png"))
        pg.locator("svg").screenshot(path=png)
        b.close()
    Image.open(png).convert("RGB").save(os.path.join(IMG, name.replace(".svg", ".webp")), "WEBP", quality=90)
    os.remove(png)


def main():
    pins = pins_from_ini()
    wiring_svg("c3-supermini", "ESP32-C3 Super Mini", pins["c3-supermini"], "wiring-c3-supermini.svg",
               "GPIO20/21 are the pads marked RX/TX. Only ADC1 pins (GPIO0–4) work with Wi-Fi on, so the MAX4466 goes to GPIO1.")
    wiring_svg("s3-pico", "Waveshare ESP32-S3-Pico", pins["s3-pico"], "wiring-s3-pico.svg",
               "GPIO11/12 sit at Pico positions GP0/GP1, GPIO13–16 at GP2–GP5, GPIO17/18 at GP6/GP7, GPIO7 at A1 — check Waveshare's pinout.")
    max4466_svg()
    dsp_chart()
    for n in ("wiring-c3-supermini.svg", "wiring-s3-pico.svg", "max4466-mod.svg"):
        svg_to_webp(n)
    oled_previews()
    physics_chart()
    print("illustrations written to", IMG)


if __name__ == "__main__":
    sys.exit(main())
