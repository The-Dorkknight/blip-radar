#!/usr/bin/env python3
"""Blip — radar node simulator (no hardware needed, Python 3 standard library only).

Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.

It also hosts the **Flash tab** (tools/flasher.py): build and flash a real board
from the same page. Serves the same web UI and the same HTTP + WebSocket protocol as the ESP32
firmware, with three pretend people wandering around and a synthetic
"Stetho" channel: 8 kHz audio packets (heart sounds, breath hiss, voice buzz
or Doppler warble depending on the preset, with the odd knock "ducked") and
100 Hz chest-motion packets. The sound is synthesised to look and sound
plausible; it is NOT run through the firmware's real DSP (that is tested in
tests/test_audio_dsp.cpp). Use it to try the
phone UI on a PC, to develop the UI, and to take screenshots.

    python3 tools/sim_radar.py            # http://127.0.0.1:8080/
    python3 tools/sim_radar.py --port 9000 --no-browser
    python3 tools/sim_radar.py --frames examples/frames_synthetic.hex   # replay RD-03D bytes
    python3 tools/sim_radar.py --no-flash                              # hide the Flash tab

Also exercises the real RD-03D byte layout: the simulated targets are first
encoded into genuine 30-byte frames and then decoded again by a Python port
of the C++ parser (tools/rd03d_py.py), so an encoding mistake would show up
on screen.
"""
import argparse
import base64
import hashlib
import json
import math
import os
import random
import socket
import struct
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flasher  # noqa: E402
import rd03d_py  # noqa: E402
import tracker_py  # noqa: E402

__version__ = "0.2.2-wip"
__build_date__ = time.strftime("%Y-%m-%d %H:%M")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "web", "index.html")

STATE = {
    "multi": True, "oled": 2, "stetho": True, "ssid": "Blip-Radar", "pass": "blipblip",
    "filter": "raw", "sleep": 0, "messy": True,
    "preset": "heart", "ns": 60, "bump": 50, "agc": True, "maxgain": 36, "gain": 12, "out": 0, "ovol": 60,
    "frames": 0, "bad": 0, "fps": 0,
}
CLIENTS = set()
CLIENTS_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Simulated world
# ---------------------------------------------------------------------------
class Walker:
    def __init__(self, seed):
        r = random.Random(seed)
        self.x = r.uniform(-1500, 1500)
        self.y = r.uniform(1500, 5000)
        self.heading = r.uniform(0, 2 * math.pi)
        self.speed = r.uniform(300, 900)       # mm/s
        self.on = True
        self.r = r

    def step(self, dt):
        if self.r.random() < 0.02:
            self.heading += self.r.uniform(-0.8, 0.8)
        if self.r.random() < (0.002 if self.on else 0.03):
            self.on = not self.on              # people stand still now and then
        if not self.on:
            return
        self.x += math.cos(self.heading) * self.speed * dt
        self.y += math.sin(self.heading) * self.speed * dt
        # keep inside the ±60° sector, 0.5..7.5 m
        d = math.hypot(self.x, self.y)
        ang = math.degrees(math.atan2(self.x, self.y))
        if d > 7500 or d < 500 or abs(ang) > 58:
            self.heading += math.pi + self.r.uniform(-0.5, 0.5)
            self.x = max(-6000, min(6000, self.x))
            self.y = max(600, min(7400, self.y))

    def radial_speed_cms(self):
        if not self.on:
            return 0
        d = math.hypot(self.x, self.y) or 1
        vx, vy = math.cos(self.heading) * self.speed, math.sin(self.heading) * self.speed
        return int(round((vx * self.x + vy * self.y) / d / 10))


WALKERS = [Walker(1), Walker(2), Walker(3)]
TRACKER = tracker_py.Tracker()
MESS = random.Random(99)
LAST_FRAME = rd03d_py.Frame()
REPLAY = None


def encode_frame(walkers):
    """Real 30-byte RD-03D frame. With STATE["messy"] (default) the room is
    imperfect like a real one: position noise, chip slots that swap, a wall
    reflection of the first walker, a fan wobbling in the corner and the odd
    one-frame flicker. That is what the Smart filter is for; --clean turns it off."""
    def enc(v):
        v = int(round(v))
        return struct.pack("<H", (0x8000 if v >= 0 else 0) | (abs(v) & 0x7FFF))
    n = 3 if STATE["multi"] else 1
    dets = []
    if STATE["messy"]:
        for w in walkers[:2]:
            if w.on:
                dets.append((w.x + MESS.gauss(0, 110), w.y + MESS.gauss(0, 60), w.radial_speed_cms()))
        w = walkers[0]
        r = math.hypot(w.x, w.y) or 1
        if w.on and MESS.random() < 0.7:                       # reflection 1.3 m behind walker 1
            dets.append((w.x / r * (r + 1300) + MESS.gauss(0, 110), w.y / r * (r + 1300), w.radial_speed_cms()))
        if MESS.random() < 0.8:                                # fan in the corner
            dets.append((-1800 + MESS.gauss(0, 90), 5500 + MESS.gauss(0, 90), MESS.randint(-15, 15)))
        if MESS.random() < 0.1:                                # flicker
            dets.append((MESS.uniform(-3000, 3000), MESS.uniform(800, 7000), MESS.randint(-40, 40)))
        MESS.shuffle(dets)
    else:
        dets = [(w.x, w.y, w.radial_speed_cms()) for w in walkers if w.on]
    dets = dets[:n]
    b = bytes([0xAA, 0xFF, 0x03, 0x00])
    for i in range(3):
        if i < len(dets):
            x, y, v = dets[i]
            b += enc(x) + enc(y) + enc(v) + struct.pack("<H", 360)
        else:
            b += bytes(8)
    return b + bytes([0x55, 0xCC])


def targets_json():
    t = []
    if STATE["filter"] == "smart":
        h = []
        if LAST_FRAME.alive:
            for (i, x, y, v) in TRACKER.visible():
                d = math.hypot(x, y)
                t.append({"id": i, "x": x, "y": y, "v": v, "res": 0, "d": round(d), "a": round(math.degrees(math.atan2(x, y)), 1)})
            h = [{"id": i, "x": x, "y": y, "why": why} for (i, x, y, why) in TRACKER.hidden()]
        return json.dumps({"ms": int(time.time() * 1000) & 0xFFFFFFFF, "alive": LAST_FRAME.alive, "fps": STATE["fps"],
                           "f": "smart", "sleep": False, "t": t, "h": h})
    if LAST_FRAME.alive:
        for i, tg in enumerate(LAST_FRAME.t):
            if not tg.present:
                continue
            d = math.hypot(tg.x_mm, tg.y_mm)
            a = math.degrees(math.atan2(tg.x_mm, tg.y_mm))
            t.append({"id": i + 1, "x": tg.x_mm, "y": tg.y_mm, "v": tg.v_cms, "res": tg.res_mm, "d": round(d), "a": round(a, 1)})
    return json.dumps({"ms": int(time.time() * 1000) & 0xFFFFFFFF, "alive": LAST_FRAME.alive, "fps": STATE["fps"], "f": "raw", "sleep": False, "t": t})


START = time.time()

# Lab switches (same names and ranges as firmware/include/lab.h) and a pretend crash:
# /api/lab?simcrash=N makes this simulator "reset" N seconds later, the way a node
# watchdog-resets: WebSocket pages dropped, the HTTP side silent for a moment, the boot
# counter up by one, every Lab switch back to its default. Used by tests/test_soak.py.
LAB_DEFAULT = {"pace": 0, "dsp": 0, "send": 0, "text": 0, "src": 0, "prio": 5, "quiet": 0, "skip": 0, "os": 0, "nb": 0}
LAB = dict(LAB_DEFAULT)
LAB_RANGES = {"pace": (0, 2), "dsp": (0, 2), "send": (0, 2), "text": (0, 3), "src": (0, 1), "prio": (1, 24), "quiet": (0, 1), "skip": (0, 7), "os": (0, 8), "nb": (0, 1)}
BOOT = {"n": 1, "down_until": 0.0, "crash_at": 0.0, "reason": "power on", "t0": time.time()}


def status_json():
    return json.dumps({
        "app": "Blip", "version": __version__, "build": __build_date__ + " (simulator)",
        "board": "Python simulator", "boardId": "sim", "wip": True, "sim": True, "flash": flasher.ENABLED,
        "ssid": STATE["ssid"], "ip": "127.0.0.1", "clients": len(CLIENTS),
        "radar": {"alive": LAST_FRAME.alive, "fps": STATE["fps"], "frames": STATE["frames"], "bad": STATE["bad"],
                  "mode": "multi" if STATE["multi"] else "single", "baud": 256000,
                  "powered": True, "pwrPin": -1, "offWhileListening": False, "filter": STATE["filter"], "asleep": False},
        "sleepMin": STATE["sleep"], "txp": STATE.get("txp", 1),
        "oled": STATE["oled"],
        "stetho": {"enabled": STATE["stetho"], "running": STATE["stetho"], "rate": 8000, "frame": 256, "pinI": 1,
                   "preset": STATE["preset"], "ns": STATE["ns"], "bump": STATE["bump"], "agc": STATE["agc"],
                   "maxgain": STATE["maxgain"], "gain": STATE["gain"], "out": STATE["out"], "ovol": STATE["ovol"],
                   "outs": {"earphone": True, "amp": True}, "overruns": 0, "dropped": 0, "pwrPin": -1, "asleep": False,
                   "err": "", "samples": STATE.get("st_samples", 0), "invalid": 0, "sent": STATE.get("st_sent", 0),
                   "skipped": 0,
                   "level": {"min": 1590, "avg": 1650, "max": 1710, "mv": True} if STATE["stetho"] else {"min": -1, "avg": -1, "max": -1, "mv": True}},
        "stetho2": {"blocks": STATE.get("st_samples", 0) // 64, "dspUs": 420, "dspUsMax": 900, "gapMaxMs": 9, "rdTimeouts": 0, "rdErrs": 0},
        "lab": dict(LAB),
        "node": {"heap": 182000, "heapMin": 171000, "loopMs": 2, "up": int(time.time() - BOOT["t0"]), "oledFound": True, "reset": BOOT["reason"], "boots": BOOT["n"]},
        "pins": {"radarRx": 20, "radarTx": 21, "sda": 6, "scl": 7, "adc": 1, "i2sBclk": 3, "i2sWs": 4, "i2sDout": 5, "pdm": 10, "radarPwr": -1},
    })


# ---------------------------------------------------------------------------
# Minimal WebSocket (RFC 6455) server-side framing
# ---------------------------------------------------------------------------
WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def ws_frame(payload, opcode):
    hdr = bytes([0x80 | opcode])
    n = len(payload)
    if n < 126:
        hdr += bytes([n])
    elif n < 65536:
        hdr += bytes([126]) + struct.pack(">H", n)
    else:
        hdr += bytes([127]) + struct.pack(">Q", n)
    return hdr + payload


def ws_broadcast(payload, opcode):
    data = ws_frame(payload, opcode)
    with CLIENTS_LOCK:
        dead = []
        for c in CLIENTS:
            try:
                c.sendall(data)
            except OSError:
                dead.append(c)
        for c in dead:
            CLIENTS.discard(c)


def ws_serve(sock):
    """Read client frames until close; we ignore their content."""
    with CLIENTS_LOCK:
        CLIENTS.add(sock)
    try:
        sock.sendall(ws_frame(status_json().encode(), 1))
        sock.settimeout(None)
        while True:
            h = sock.recv(2)
            if len(h) < 2:
                break
            op = h[0] & 0x0F
            n = h[1] & 0x7F
            if n == 126:
                n = struct.unpack(">H", sock.recv(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", sock.recv(8))[0]
            if h[1] & 0x80:
                sock.recv(4)
            while n > 0:
                chunk = sock.recv(min(n, 4096))
                if not chunk:
                    return
                n -= len(chunk)
            if op == 8:
                break
            if op == 9:
                sock.sendall(ws_frame(b"", 10))
    except OSError:
        pass
    finally:
        with CLIENTS_LOCK:
            CLIENTS.discard(sock)
        try:
            sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
HIJACKED = set()


class Server(ThreadingHTTPServer):
    def shutdown_request(self, request):
        if request in HIJACKED:      # WebSocket thread owns it now
            HIJACKED.discard(request)
            return
        super().shutdown_request(request)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if time.time() < BOOT["down_until"]:
            return self._send(503, "text/plain", b"node is restarting")
        if path == "/ws" and "websocket" in self.headers.get("Upgrade", "").lower():
            key = self.headers.get("Sec-WebSocket-Key", "")
            accept = base64.b64encode(hashlib.sha1((key + WS_MAGIC).encode()).digest()).decode()
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            self.close_connection = True
            sock = self.connection
            HIJACKED.add(sock)      # tell the server not to shut this socket down
            self.connection = None
            threading.Thread(target=ws_serve, args=(sock,), daemon=True).start()
            return
        if path.startswith("/api/flash/") or path == "/flasher.html":      # the Flash tab (this computer only)
            return flasher.handle(self, path, query)
        if path == "/" and flasher.ENABLED and flasher._local_only(self) is None:   # this computer: flasher first
            return flasher.handle(self, path, query)
        if path in ("/", "/sim", "/index.html"):          # the simulator (and what a phone on --lan gets)
            with open(INDEX, "rb") as f:
                return self._send(200, "text/html; charset=utf-8", f.read())
        if path == "/api/log":
            up = time.time() - START
            lines = ["[00:00.2] === Blip %s built %s on Python simulator, start #1, last reset: power on ===" % (__version__, __build_date__),
                     "[00:00.4] Wi-Fi transmit power 15 dBm", "[00:00.5] hotspot 'Blip-Radar' on channel 6 -> http://127.0.0.1/  (182 KB free)"]
            for t in range(10, int(up), 10):
                lines.append("[%02d:%02d.0] health: 180 KB free (lowest 171, biggest block 110) | 1 on hotspot, 1 page(s) | +4 requests +0 probes | loop 2 ms | %s"
                             % (t // 60, t % 60, "Stetho on 1650 mV, +312 sent +0 skipped +0 dropped" if STATE["stetho"] else "Stetho off"))
            return self._send(200, "text/plain; charset=utf-8", ("\n".join(lines[-60:]) + "\n").encode())
        if path == "/api/status":
            return self._send(200, "application/json", status_json())
        if path == "/api/quit":     # lets a newly started simulator replace this one
            if (self.command != "POST" or self.client_address[0] not in ("127.0.0.1", "::1")
                    or self.headers.get("X-Blip-Quit") != "1"
                    or self.headers.get("Sec-Fetch-Site", "none") not in ("none", "same-origin")):
                return self._send(403, "text/plain", b"no")
            self._send(200, "text/plain", b"bye")
            threading.Thread(target=lambda: (time.sleep(0.2), os._exit(0)), daemon=True).start()
            return
        if path == "/api/targets":
            return self._send(200, "application/json", targets_json())
        if path == "/api/config":
            from urllib.parse import parse_qs
            q = {k: v[0] for k, v in parse_qs(query).items()}
            if "mode" in q:
                STATE["multi"] = q["mode"] != "single"
            if "oled" in q:
                STATE["oled"] = max(0, min(3, int(q["oled"] or 0)))
            if "stetho" in q:
                STATE["stetho"] = q["stetho"] == "1"
            if "preset" in q and q["preset"] in PRESETS:
                STATE["preset"] = q["preset"]
            for k, lo, hi in (("ns", 0, 100), ("bump", 0, 100), ("maxgain", 0, 48), ("gain", 0, 48), ("out", 0, 2), ("ovol", 0, 100)):
                if k in q:
                    try:
                        STATE[k] = max(lo, min(hi, int(q[k])))
                    except ValueError:
                        pass
            if "filter" in q:
                STATE["filter"] = "smart" if q["filter"] == "smart" else "raw"
                TRACKER.reset()
            if "forget" in q:
                TRACKER.forget_clutter()
            if "txp" in q:
                STATE["txp"] = max(0, min(2, int(q["txp"]))) if q["txp"].isdigit() else 1
            if "sleep" in q:
                try:
                    STATE["sleep"] = max(0, min(60, int(q["sleep"])))
                except ValueError:
                    pass
            if "agc" in q:
                STATE["agc"] = q["agc"] == "1"
            if "ssid" in q and 1 <= len(q["ssid"]) <= 32:
                STATE["ssid"] = q["ssid"]
            if "pass" in q and 8 <= len(q["pass"]) <= 63:
                STATE["pass"] = q["pass"]
            return self._send(200, "application/json", status_json())
        if path == "/api/lab":
            from urllib.parse import parse_qs
            q = {k: v[0] for k, v in parse_qs(query).items()}
            if q.get("reset") == "1":
                LAB.update(LAB_DEFAULT)
            for k, (lo, hi) in LAB_RANGES.items():
                if k in q:
                    try:
                        LAB[k] = max(lo, min(hi, int(q[k])))
                    except ValueError:
                        pass
            if "simcrash" in q:           # simulator only: pretend to crash N seconds from now
                try:
                    BOOT["crash_at"] = time.time() + max(0.5, float(q["simcrash"]))
                except ValueError:
                    pass
            return self._send(200, "application/json", status_json())
        if path == "/api/reboot":
            return self._send(200, "text/plain", "rebooting (simulated)")
        self.send_response(302)
        self.send_header("Location", "/")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_GET

    def finish(self):
        if self.connection is None:  # handed over to the WebSocket thread
            return
        super().finish()


# ---------------------------------------------------------------------------
# Background producers
# ---------------------------------------------------------------------------
def radar_loop():
    global LAST_FRAME
    parser = rd03d_py.Parser()
    dt = 0.05
    count = 0
    t0 = time.time()
    replay_pos = 0
    while True:
        if REPLAY:
            chunk = REPLAY[replay_pos:replay_pos + 30]
            replay_pos = (replay_pos + 30) % max(30, len(REPLAY))
        else:
            for w in WALKERS:
                w.step(dt)
            chunk = encode_frame(WALKERS)
        for b in chunk:
            fr = parser.feed(b)
            if fr:
                fr.alive = True
                LAST_FRAME = fr
                count += 1
                TRACKER.update([(tg.x_mm, tg.y_mm, tg.v_cms) for tg in fr.t if tg.present], dt)
        STATE["frames"] = parser.frames
        STATE["bad"] = parser.bad
        if time.time() - t0 >= 1:
            STATE["fps"] = count
            count = 0
            t0 = time.time()
            ws_broadcast(status_json().encode(), 1)     # the node pushes its status once a second too
        ws_broadcast(targets_json().encode(), 1)
        time.sleep(dt)


PRESETS = ("heart", "lungs", "voice", "wide", "raw")


def mulaw(s):
    """G.711 mu-law, the same as blipdsp::mulaw() on the node."""
    sign = 0x80 if s < 0 else 0
    x = min(-s if sign else s, 32635) + 0x84
    exp = 7
    m = 0x4000
    while (x & m) == 0 and exp > 0:
        m >>= 1
        exp -= 1
    return ~(sign | (exp << 4) | ((x >> (exp + 3)) & 0x0F)) & 0xFF


def stetho_loop():
    """8 kHz 'A' packets of 128 samples + 100 Hz 'V' packets of 10, paced by the clock."""
    fs, frame = 8000, 256
    t = 0.0
    seq_a = seq_v = 0
    vbuf, vflags = [], 0
    vacc, vn = 0.0, 0
    lp = 0.0
    nxt = time.monotonic()
    while True:
        if not STATE["stetho"]:
            time.sleep(0.1)
            nxt = time.monotonic()
            continue
        preset = STATE["preset"]
        out, flags = [], 0
        for i in range(frame):
            tt = t + i / fs
            beat = (tt * 1.2) % 1.0 / 1.2                     # 72 bpm
            breath = math.sin(2 * math.pi * 0.25 * tt)
            knock = (tt % 7.3) < 0.08                          # someone bumps the table every 7.3 s
            noise = random.gauss(0, 1)
            lp += 0.15 * (noise - lp)
            if preset == "heart":
                v = 0.0
                if beat < 0.07:
                    v += 0.5 * math.sin(2 * math.pi * 45 * beat) * math.sin(math.pi * beat / 0.07)
                if 0.30 <= beat < 0.35:
                    v += 0.3 * math.sin(2 * math.pi * 70 * (beat - 0.3)) * math.sin(math.pi * (beat - 0.3) / 0.05)
                v += 0.02 * lp
            elif preset == "lungs":
                v = (0.05 + 0.12 * max(0.0, breath)) * noise
            elif preset == "voice":
                talking = (tt % 6.0) < 2.5
                f0 = 130 + 25 * math.sin(2 * math.pi * 0.7 * tt)
                v = (0.35 * sum(math.sin(2 * math.pi * f0 * h * tt) / h for h in (1, 2, 3, 4)) if talking else 0.0) + 0.02 * noise
            elif preset == "wide":
                v = 0.3 * math.sin(2 * math.pi * 45 * beat) * math.exp(-beat * 30) + 0.04 * noise
            else:                                              # raw Doppler: a walker warbling at ~0.8 m/s
                f = 130 + 60 * math.sin(2 * math.pi * 0.3 * tt)
                v = 0.4 * math.sin(2 * math.pi * f * tt) * (0.6 + 0.4 * math.sin(2 * math.pi * 1.7 * tt)) + 0.05 * noise
            if knock:
                flags |= 1
                k = 2.0 * math.exp(-((tt % 7.3) / 0.015)) * noise
                v = k if preset == "raw" else k * 0.03       # processed presets duck it ~30 dB
            out.append(int(max(-32767, min(32767, v * 20000))))
            # chest motion for 'V' (decimated 80:1)
            vacc += 0.6 * breath + 0.08 * math.exp(-beat * 8) * math.sin(2 * math.pi * 1.2 * tt) + 0.01 * noise
            vn += 1
            if vn == 80:
                vbuf.append(int(vacc / vn * 16384))
                vflags |= flags & 1
                vacc, vn = 0.0, 0
                if len(vbuf) == 10:
                    ws_broadcast(b"V" + bytes([vflags]) + struct.pack("<H", seq_v & 0xFFFF) + b"\0\0" + struct.pack("<10h", *vbuf), 2)
                    seq_v += 1
                    vbuf, vflags = [], 0
        t += frame / fs
        agc = 18 if preset != "raw" else 6
        nsdb = -9 if preset != "raw" and STATE["ns"] > 0 else 0
        STATE["st_samples"] = STATE.get("st_samples", 0) + frame
        STATE["st_sent"] = STATE.get("st_sent", 0) + 1
        if LAB["send"] != 1:          # Lab send=1: drained and thrown away
            ws_broadcast(b"U" + bytes([flags]) + struct.pack("<Hbb", seq_a & 0xFFFF, agc, nsdb) + bytes(mulaw(v) for v in out), 2)
        seq_a += 1
        nxt += frame / fs
        delay = nxt - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        elif delay < -0.5:
            nxt = time.monotonic()


def crash_watch():
    """Lab: carry out a pretend crash requested with /api/lab?simcrash=N (see BOOT above)."""
    while True:
        time.sleep(0.1)
        if BOOT["crash_at"] and time.time() >= BOOT["crash_at"]:
            BOOT["crash_at"] = 0.0
            if LAB["send"] != 0:          # the simulator's pretend culprit is the audio send: with it off, no crash
                continue
            BOOT["down_until"] = time.time() + 3.0
            BOOT["n"] += 1
            BOOT["reason"] = "crash (task watchdog)"
            BOOT["t0"] = time.time() + 3.0
            LAB.update(LAB_DEFAULT)
            with CLIENTS_LOCK:
                for c in list(CLIENTS):
                    try:
                        c.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    try:
                        c.close()
                    except OSError:
                        pass
                CLIENTS.clear()


def lan_ips():
    """This computer's addresses on the local network (no traffic is sent)."""
    ips = []
    for target in ("10.255.255.255", "192.168.255.255"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as so:
                so.connect((target, 9))
                ip = so.getsockname()[0]
                if ip not in ips and not ip.startswith("127."):
                    ips.append(ip)
        except OSError:
            pass
    return ips


def make_server(host, port):
    """Bind the port. If an old Blip simulator holds it, ask it to quit and take over;
    if something else holds it, use the next free port."""
    import urllib.request
    try:
        return Server((host, port), Handler), port
    except OSError as e:
        if e.errno not in (98, 48, 10048):
            raise
    old = False
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/status" % port, timeout=2) as r:
            old = '"flash"' in r.read().decode("utf-8", "replace")
    except Exception:
        pass
    if old:
        print("A Blip simulator is already running on port %d - stopping it and starting a fresh one." % port)
        try:
            urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/api/quit" % port, data=b"",
                                   headers={"X-Blip-Quit": "1"}, method="POST"), timeout=2).read()
        except Exception:
            pass
        for _ in range(20):
            time.sleep(0.25)
            try:
                return Server((host, port), Handler), port
            except OSError:
                pass
        print("The old simulator would not stop (close its window, or use --port).")
    else:
        print("Port %d is used by another program." % port)
    for p in range(port + 1, port + 20):
        try:
            srv = Server((host, p), Handler)
            print("Using port %d instead." % p)
            return srv, p
        except OSError:
            pass
    raise SystemExit("No free port found near %d. Try --port 9000." % port)


def main():
    global REPLAY
    ap = argparse.ArgumentParser(description="Blip radar node simulator")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--lan", action="store_true", help="also listen on the local network, so a phone can open it (the Flash tab stays this-computer-only)")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--frames", help="hex file of RD-03D bytes to replay instead of the random walkers")
    ap.add_argument("--clean", action="store_true", help="perfect room: no reflections, fan, flickers or noise")
    ap.add_argument("--no-flash", action="store_true", help="hide the Flash tab and refuse /api/flash/*")
    ap.add_argument("--version", action="version", version=f"Blip simulator {__version__} ({__build_date__}) — work in progress")
    a = ap.parse_args()
    STATE["messy"] = not a.clean
    flasher.ENABLED = not a.no_flash
    if a.frames:
        with open(a.frames) as f:
            REPLAY = bytes.fromhex("".join(line.split("#")[0] for line in f))
    threading.Thread(target=radar_loop, daemon=True).start()
    threading.Thread(target=stetho_loop, daemon=True).start()
    threading.Thread(target=crash_watch, daemon=True).start()
    host = "0.0.0.0" if a.lan else a.host
    srv, port = make_server(host, a.port)
    srv.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    print(f"Blip flasher + simulator {__version__} ({__build_date__}) — WORK IN PROGRESS")
    if flasher.ENABLED:
        print(f"Flasher:   {url}  (Ctrl+C to stop)")
        print(f"Simulator: {url}sim")
    else:
        print(f"Open {url}  (Ctrl+C to stop)")
    if a.lan:
        for ip in lan_ips():
            print(f"On your phone / another device on this network: http://{ip}:{port}/  (simulator; the flasher stays on this computer)")
    else:
        ips = lan_ips()
        if ips:
            print(f"This computer's network address is {ips[0]}. Start with --lan to open it from a phone.")
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        flasher.shutdown()


if __name__ == "__main__":
    main()
