#!/usr/bin/env python3
"""Blip: look inside a Stetho recording (the "Record 10 s -> WAV" button) and say what the static is.

    python3 tools/analyze_wav.py stetho_raw_os0_nb1_....wav [more.wav ...]

Python 3 standard library only. Prints, per file:
  - level, DC offset, how often the sound hit the rail (clipping)
  - how the energy spreads over frequency (so you can see hiss, hum, or a whistle)
  - short loud bursts above 1 kHz and whether they repeat on a fixed beat. About 9.8 per second (every 102.4 ms) is the Wi-Fi
    beacon; a burst rate that follows your movement is the Doppler signal itself clipping.
  - the heartbeat and breathing rate found by the same autocorrelation the page uses (rough)
Record in the Raw preset to look at what the ADC delivers, and in Heart to look at what the node's clean-up leaves.
Compare two recordings (for example 1x and 4x averaging) by running the tool on both.

Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""
import cmath
import math
import struct
import sys
import wave


def read_wav(path):
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise SystemExit(f"{path}: expected 16-bit audio")
        ch, fs, n = w.getnchannels(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    x = struct.unpack("<%dh" % (len(raw) // 2), raw)
    return [v / 32768.0 for v in x[::ch]], fs


def fft(a):
    n = len(a)
    if n == 1:
        return a
    ev, od = fft(a[0::2]), fft(a[1::2])
    t = [cmath.exp(-2j * math.pi * k / n) * od[k] for k in range(n // 2)]
    return [ev[k] + t[k] for k in range(n // 2)] + [ev[k] - t[k] for k in range(n // 2)]


def band_energy(x, fs, edges):
    """Mean power per band from Hann-windowed 2048-point blocks."""
    N = 2048
    win = [0.5 - 0.5 * math.cos(2 * math.pi * i / (N - 1)) for i in range(N)]
    acc = [0.0] * (N // 2)
    blocks = 0
    for s in range(0, len(x) - N, N // 2):
        seg = [x[s + i] * win[i] for i in range(N)]
        m = sum(seg) / N
        X = fft([v - m for v in seg])
        for k in range(N // 2):
            acc[k] += abs(X[k]) ** 2
        blocks += 1
    out = []
    for lo, hi in edges:
        a, b = int(lo * N / fs), max(int(lo * N / fs) + 1, int(hi * N / fs))
        out.append(sum(acc[a:b]) / max(1, blocks))
    return out


def highpass(x, fc, fs):
    a = math.exp(-2 * math.pi * fc / fs)
    y, px, py = [], 0.0, 0.0
    for v in x:
        py = a * (py + v - px)
        px = v
        y.append(py)
    return y


def envelope(x, n):
    return [math.sqrt(sum(v * v for v in x[i:i + n]) / n) for i in range(0, len(x) - n + 1, n)]


def median(v):
    s = sorted(v)
    return s[len(s) // 2] if s else 0.0


def autocorr_period(e, rate, pmin, pmax):
    """Strongest repeat period in an envelope, with a score 0..1 (1 = perfectly repeating)."""
    m = sum(e) / len(e)
    z = [v - m for v in e]
    e0 = sum(v * v for v in z) or 1.0
    best, bl, r = 0.0, 0, []
    lags = range(int(pmin * rate), min(int(pmax * rate) + 1, len(z) // 2))
    for L in lags:
        r.append(sum(z[i] * z[i - L] for i in range(L, len(z))) / e0)
    for i in range(1, len(r) - 1):
        if r[i] > r[i - 1] and r[i] >= r[i + 1] and r[i] > best:
            best, bl = r[i], list(lags)[i]
    return (bl / rate if bl else 0.0), best


def analyse(path):
    x, fs = read_wav(path)
    n = len(x)
    print(f"\n=== {path}\n{n / fs:.1f} s at {fs} Hz")
    if n < fs * 3:
        print("  too short to say much (record at least 10 s)")
        return
    dc = sum(x) / n
    rms = math.sqrt(sum((v - dc) ** 2 for v in x) / n)
    pk = max(abs(v - dc) for v in x)
    clip = sum(1 for v in x if abs(v) > 0.97) / n
    print(f"level: rms {20 * math.log10(rms + 1e-9):.1f} dBFS, peak {20 * math.log10(pk + 1e-9):.1f} dBFS, DC {dc * 100:+.2f} %, at the rail {clip * 100:.2f} % of the time")
    edges = [(20, 100), (100, 300), (300, 800), (800, 1500), (1500, 3000), (3000, 4000)]
    be = band_energy(x, fs, edges)
    tot = sum(be) or 1.0
    print("energy by band: " + "  ".join(f"{lo}-{hi} Hz {100 * e / tot:.0f}%" for (lo, hi), e in zip(edges, be)))

    # bursts above 1 kHz
    hp = highpass(highpass(x, 1000, fs), 1000, fs)
    step = max(1, fs // 1000)                       # 1 ms
    env = envelope(hp, step)
    base = median(env) or 1e-9
    thr = max(5 * base, 0.004)
    bursts, i = [], 0
    while i < len(env):
        if env[i] > thr:
            j = i
            while j < len(env) and env[j] > thr * 0.5:
                j += 1
            bursts.append((i, j - i))
            i = j + 20
        else:
            i += 1
    secs = n / fs
    print(f"short bursts above 1 kHz (>5x the usual): {len(bursts)} in {secs:.1f} s = {len(bursts) / secs:.1f} per second" + (f", typical length {median([b[1] for b in bursts])} ms" if bursts else ""))
    if len(bursts) >= 8:
        gaps = [(bursts[k + 1][0] - bursts[k][0]) for k in range(len(bursts) - 1)]
        g = median(gaps)
        near = sum(1 for d in gaps if abs(d - g) <= max(3, 0.08 * g)) / len(gaps)
        print(f"  usual gap between bursts: {g} ms; {near * 100:.0f}% of gaps within 8 % of it")
        if abs(g - 102.4) <= 6 and near > 0.5:
            print("  -> bursts on a 102.4 ms beat: this looks like the Wi-Fi beacon pulling the supply or the ADC. Try: 4x averaging, a 100 uF + 10 ohm filter on the MAX4466 supply, keep the radar away from the ESP32 antenna.")
        elif near > 0.6:
            print(f"  -> bursts are regular (about every {g} ms) but not at the Wi-Fi beacon interval: look for another periodic load (display refresh, LED, other radio).")
        else:
            print("  -> bursts are irregular: they follow something in the room (movement, clipping Doppler peaks) rather than a clock.")
    hf_share = sum(be[3:]) / tot
    if clip > 0.005:
        print(f"  -> the sound sits at the rail {clip * 100:.2f} % of the time: the Doppler peaks are clipping, which makes chirps. Lower the radar-board gain or the MAX4466 pot.")
    elif hf_share > 0.3:
        print(f"  -> {hf_share * 100:.0f} % of the energy is above 800 Hz: for a heartbeat that is mostly noise or aliasing (try averaging, and the Heart preset's blanker).")

    # heart and breath rhythm from the loudness
    e10 = envelope(x, fs // 100)
    p, sc = autocorr_period(e10, 100, 0.33, 1.5)
    if p and sc > 0.25:
        print(f"heartbeat-like rhythm: {60 / p:.0f} per minute (repeat strength {sc:.2f}; above 0.4 is a clear pattern)")
    else:
        print("heartbeat-like rhythm: none found")
    e1 = envelope(x, fs)
    e1 = e1 if len(e1) >= 8 else []
    if len(e1) >= 8:
        p, sc = autocorr_period(e1, 1, 1.5, 6.0)
        print(f"breathing-like rhythm: {60 / p:.0f} per minute (repeat strength {sc:.2f}; only meaningful on 30 s or more)" if p and sc > 0.3 and len(e1) >= 20 else "breathing-like rhythm: none found (needs 30 s or more)")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    for f in sys.argv[1:]:
        analyse(f)
