// Heart / breath pattern recognition (the CycleTracker block in web/index.html), tested under Node on synthetic data.
//   node tests/test_vitals_pr.js
// What this proves: the maths finds a repeating pattern when there is one at realistic signal-to-noise, reports the right rate (not half or
// double), says "no pattern" on noise and irregular knocks, survives bump-flagged stretches, lost packets and heart-rate variability,
// predicts the next beat, and that the optional gate leaves the beats alone and only quietens the gaps.
// What it cannot prove: that a real chest looks like this. Synthetic data only: see docs/STETHO_SIGNAL_NOTES.md for what to check on real recordings.
'use strict';
const load = require('./pr_load.js');
const {VitalsPR, CycleTracker} = load();
let fails = 0;
const check = (ok, msg) => { console.log((ok ? 'PASS  ' : 'FAIL  ') + msg); if (!ok) fails++; };

let seed = 1;
const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
const gauss = () => { let s = 0; for (let i = 0; i < 6; i++) s += rnd(); return (s - 3) * 1.41421356; };
function bq(type, f, q, fs) { const w = 2 * Math.PI * f / fs, c = Math.cos(w), al = Math.sin(w) / (2 * q); let b0, b1, b2; if (type === 'lp') { b0 = (1 - c) / 2; b1 = 1 - c; b2 = b0; } else { b0 = (1 + c) / 2; b1 = -(1 + c); b2 = b0; }
  const a0 = 1 + al, a1 = -2 * c / a0, a2 = (1 - al) / a0; b0 /= a0; b1 /= a0; b2 /= a0; let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  return v => { const y = b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2; x2 = x1; x1 = v; y2 = y1; y1 = y; return y; }; }
// noise as the chain delivers it: band-limited to the preset's passband, unit rms
function bandNoise(N, rms, lo, hi, fs = 8000) { const h = bq('hp', lo, 0.707, fs), l = bq('lp', hi, 0.707, fs), l2 = bq('lp', hi, 0.707, fs), x = new Float32Array(N); let s2 = 0;
  for (let i = 0; i < N; i++) x[i] = l2(l(h(gauss()))); for (let i = fs; i < N; i++) s2 += x[i] * x[i]; const g = rms / Math.sqrt(s2 / (N - fs)); for (let i = 0; i < N; i++) x[i] *= g; return x; }

// 8 kHz heart audio: S1 (48 Hz) and S2 (68 Hz, 0.7x) bursts, S1-S2 gap 0.30 s (shorter when the heart is fast), band-limited noise, optional beat-to-beat jitter
function heartAudio(secs, bpm, pk, noise, o = {}) {
  const N = Math.round(secs * 8000), x = new Float32Array(N), s1 = []; let t = 0.3;
  while (t * 8000 < N) { s1.push(t); const i0 = Math.round(t * 8000);
    for (let k = 0; k < 720 && i0 + k < N; k++) { const tt = k / 8000; x[i0 + k] += pk * Math.exp(-tt / 0.022) * Math.sin(2 * Math.PI * 48 * tt); }
    const i1 = i0 + Math.round(Math.min(0.30, 0.42 * 60 / bpm) * 8000);
    for (let k = 0; k < 560 && i1 + k < N; k++) { const tt = k / 8000; x[i1 + k] += (o.s2 ?? 0.7) * pk * Math.exp(-tt / 0.016) * Math.sin(2 * Math.PI * 68 * tt); }
    t += 60 / bpm * (1 + (o.hrv || 0) * (rnd() - 0.5)); }
  const nz = bandNoise(N, noise, 15, 250); for (let i = 0; i < N; i++) x[i] += nz[i];
  return {x, s1, N};
}
// feed audio the way packets arrive: 256 samples at a time; returns per-update stats after `settle` seconds
function feed(x, opt = {}) {
  const pr = opt.pr || new VitalsPR(); let upd = 0, locked = 0, weak = 0; const errs = [], bps = [];
  for (let i = 0; i < x.length; i += 256) {
    const f = x.subarray(i, Math.min(i + 256, x.length)), t = i / 8000;
    if (opt.loss && rnd() < opt.loss) { pr.gap(256); continue; }                                   // a packet that never arrived
    const bad = opt.badAt ? opt.badAt(t) : false; pr.audio(bad ? f.map(v => v * 8) : f, bad);       // a bump: loud garbage, flagged
    if (t > (opt.settle ?? 12) && pr.heart.updates && (i % 2048) < 256) { upd++; if (pr.heart.locked) locked++; if (pr.heart.weak || pr.heart.locked) { weak++; bps.push(pr.heart.bpm); } }
  }
  bps.sort((a, b) => a - b); return {pr, upd, lock: locked / Math.max(1, upd), weak: weak / Math.max(1, upd), bpm: bps.length ? bps[bps.length >> 1] : NaN};
}

// ---- 1) heart rate from the sound ------------------------------------------------------------------------------------------------
console.log('--- heart sound: rate and lock vs rate and signal (S1 peak / in-band noise rms) ---');
for (const bpm of [48, 60, 72, 90, 110, 140]) for (const snr of [6, 4]) {
  seed = 100 + bpm; const {x} = heartAudio(40, bpm, snr, 1), r = feed(x), err = Math.abs(r.bpm - bpm);
  const need = snr >= 6 ? r.lock >= 0.9 : bpm < 55 ? r.weak >= 0.4 : r.weak >= 0.9;      // known limit: 48 bpm in weak signal has only ~6 beats in the 8 s window, so it is shown less often (never wrongly)
  check(need && err <= 2.5, `${String(bpm).padStart(3)} bpm, S1 ${snr}x the noise: locked ${(100 * r.lock).toFixed(0)}% / shown ${(100 * r.weak).toFixed(0)}% of the time, reads ${r.bpm.toFixed(1)} bpm`);
}
{ seed = 7; const {x} = heartAudio(40, 72, 6, 1, {hrv: 0.12}), r = feed(x), err = Math.abs(r.bpm - 72);
  check(r.weak >= 0.8 && err <= 3, `heart rate varies +-6 % beat to beat: still reads ${r.bpm.toFixed(1)} bpm (rate shown ${(100 * r.weak).toFixed(0)}% of the time)`); }
{ seed = 8; const {x} = heartAudio(40, 72, 6, 1, {s2: 1.0}), r = feed(x);
  check(Math.abs(r.bpm - 72) <= 2.5, `S2 as loud as S1 does not halve or double the rate: ${r.bpm.toFixed(1)} bpm`); }
{ seed = 9; const {x} = heartAudio(40, 78, 6, 1), N = x.length;
  const r = feed(x, {badAt: t => (t % 3.1) < 0.25});                                                      // a bump flagged every 3.1 s
  check(Math.abs(r.bpm - 78) <= 2.5 && r.weak > 0.8, `a flagged bump every 3.1 s (250 ms of loud garbage each): reads ${r.bpm.toFixed(1)} bpm`); }
{ seed = 10; const {x} = heartAudio(40, 78, 6, 1), r = feed(x, {loss: 0.06});
  check(Math.abs(r.bpm - 78) <= 2.5 && r.weak > 0.8, `6 % of the packets lost (clock kept by gap()): reads ${r.bpm.toFixed(1)} bpm`); }

// ---- 2) no pattern -> no lock -------------------------------------------------------------------------------------------------------
console.log('--- nothing repeating ---');
for (const sd of [3, 11, 29, 47]) { seed = sd; const x = bandNoise(8000 * 200, 1, 15, 250), r = feed(x);
  check(r.lock === 0 && r.weak < 0.05, `band-limited noise, seed ${sd}: locked ${(100 * r.lock).toFixed(1)}% , rate shown ${(100 * r.weak).toFixed(1)}% of the time`); }
{ seed = 5; const N = 8000 * 200, x = bandNoise(N, 1, 15, 250); let t = 1; while (t < 198) { const i0 = Math.round(t * 8000); for (let k = 0; k < 800; k++) x[i0 + k] += 12 * Math.exp(-k / 150) * Math.sin(k * 0.04); t += 0.6 + 2.5 * rnd(); }
  const r = feed(x); check(r.lock === 0 && r.weak < 0.2, `irregular knocks 0.6-3.1 s apart: locked ${(100 * r.lock).toFixed(1)}% , a (weak) rate shown ${(100 * r.weak).toFixed(1)}% of the time`); }

// ---- 3) predicting the next beat ----------------------------------------------------------------------------------------------------
console.log('--- prediction ---');
{ seed = 21; const {x, s1} = heartAudio(40, 72, 6, 1, {hrv: 0.03}); const pr = new VitalsPR(); const errs = [];
  // after each lock update ask for the next envelope peak and compare with the S1 that actually followed (envelope peak sits ~10 ms after the onset)
  const asked = [];
  for (let i = 0; i < x.length; i += 256) { pr.audio(x.subarray(i, Math.min(i + 256, x.length)), false); const t = i / 8000;
    if (t > 14 && pr.heart.locked && (i % 8192) < 256) asked.push([t, pr.heart.nextPeak(pr.time())]); }
  if (process.env.DBG) console.log(asked.map(([t, p]) => { let b = 9, bs = 0; for (const s of s1) if (Math.abs(s + 0.010 - p) < Math.abs(b)) { b = s + 0.010 - p; } return (p - t).toFixed(2) + ':' + (-b * 1000).toFixed(0); }).join(' '));
  for (const [t, p] of asked) { if (p > 39) continue; let best = 9; for (const s of s1) { const d = Math.abs(s + 0.010 - p); if (d < best) best = d; } errs.push(best); }
  errs.sort((a, b) => a - b);
  check(errs.length > 10 && errs[errs.length >> 1] < 0.035 && errs[Math.floor(errs.length * 0.9)] < 0.08, `predicted time of the next S1 (3 % beat-to-beat jitter; random-walk drift makes more than this unpredictable by any method): median miss ${(1000 * errs[errs.length >> 1]).toFixed(0)} ms, 90th percentile ${(1000 * errs[Math.floor(errs.length * 0.9)]).toFixed(0)} ms (${errs.length} predictions)`); }

// ---- 4) the optional gate: beats untouched, gaps quieter, nothing happens without a lock -------------------------------------------------
console.log('--- gate ---');
function gateTest(x, s1, depth, label, hrv) {
  const pr = new VitalsPR(); const out = new Float32Array(x.length); let eBeat = 0, eGap = 0, nBeat = 0, nGap = 0, iBeat = 0, iGap = 0;
  const inBeat = new Uint8Array(x.length), wide = new Uint8Array(x.length), mark = (a, b, arr) => { for (let k = Math.max(0, Math.round(a * 8000)); k < Math.min(x.length, Math.round(b * 8000)); k++) arr[k] = 1; };
  for (const sT of s1) { mark(sT - 0.02, sT + 0.10, inBeat); mark(sT + 0.28, sT + 0.38, inBeat); mark(sT - 0.05, sT + 0.45, wide); }      // S1, S2 themselves; gaps = well outside them
  for (let i = 0; i < x.length; i += 256) { const f = x.slice(i, Math.min(i + 256, x.length)); const g = pr.shape(f, 'heart', depth); pr.audio(x.subarray(i, Math.min(i + 256, x.length)), false); out.set(g, i); }
  for (let i = 8000 * 15; i < x.length; i++) { if (inBeat[i]) { eBeat += out[i] * out[i]; iBeat += x[i] * x[i]; nBeat++; } else if (!wide[i]) { eGap += out[i] * out[i]; iGap += x[i] * x[i]; nGap++; } }
  return {beat: 10 * Math.log10(eBeat / iBeat), gap: 10 * Math.log10(eGap / iGap)};
}
for (const hrv of [0, 0.06]) { seed = 31; const {x, s1} = heartAudio(60, 72, 6, 1, {hrv}); const g = gateTest(x, s1, 9, '', hrv);
  check(g.beat > -1.0 && g.gap < -3.0, `gate 9 dB, jitter ${hrv * 50} %: heart parts ${g.beat.toFixed(1)} dB, gaps between ${g.gap.toFixed(1)} dB`); }
{ seed = 33; const x = bandNoise(8000 * 60, 1, 15, 250), g = gateTest(x, [], 9);
  check(g.gap > -0.3, `gate on noise with no pattern: output within ${Math.abs(g.gap).toFixed(2)} dB of the input (nothing is gated without a lock)`); }
{ seed = 34; const {x, s1} = heartAudio(60, 72, 6, 1, {hrv: 0.12}); const g = gateTest(x, s1, 9);
  check(g.beat > -1.5, `gate 9 dB, 12 % jitter: heart parts ${g.beat.toFixed(1)} dB (a weaker rhythm may lose the gate, it must not eat the beats)`); }

// ---- 5) breathing from the lung sound ----------------------------------------------------------------------------------------------------
console.log('--- breath, from the loudness of the lung sound ---');
function lungAudio(secs, perMin, depth, o = {}) {      // broadband breath noise swelling in and out over a steady background (unit rms)
  const N = Math.round(secs * 8000), bg = bandNoise(N, 1, 100, 1500), br = bandNoise(N, 1, 100, 1500), x = new Float32Array(N), P = 60 / perMin;
  for (let i = 0; i < N; i++) { const t = i / 8000, ph = ((t / P) % 1 + (o.drift ? 0.0 : 0)), a = ph < 0.4 ? 0.5 - 0.5 * Math.cos(Math.PI * ph / 0.4) : ph < 0.85 ? 0.7 * (0.5 + 0.5 * Math.cos(Math.PI * (ph - 0.4) / 0.45)) : 0; x[i] = bg[i] + depth * a * br[i]; }
  return x; }
for (const [pm, depth] of [[12, 3], [18, 2], [24, 2], [30, 3]]) { seed = 40 + pm; const x = lungAudio(150, pm, depth); const pr = new VitalsPR(); let ok = 0, upd = 0; const bp = [];
  for (let i = 0; i < x.length; i += 256) { pr.audio(x.subarray(i, Math.min(i + 256, x.length)), false); if (i / 8000 > 50 && (i % 16384) < 256 && pr.lung.updates) { upd++; if (pr.lung.locked || pr.lung.weak) { ok++; bp.push(pr.lung.bpm); } } }
  bp.sort((a, b) => a - b); const med = bp[bp.length >> 1];
  check(ok / upd > 0.8 && Math.abs(med - pm) <= 1.5, `${pm}/min, breath noise ${depth}x the background: reads ${med ? med.toFixed(1) : '-'} /min (shown ${(100 * ok / upd).toFixed(0)}% of the time)`); }
{ seed = 77; const x = bandNoise(8000 * 150, 1, 100, 1500); const pr = new VitalsPR(); let wk = 0, upd = 0;
  for (let i = 0; i < x.length; i += 256) { pr.audio(x.subarray(i, Math.min(i + 256, x.length)), false); if (i / 8000 > 50 && (i % 16384) < 256 && pr.lung.updates) { upd++; if (pr.lung.locked || pr.lung.weak) wk++; } }
  check(wk / upd < 0.1, `steady noise, no breathing: a breath rate is shown ${(100 * wk / upd).toFixed(1)}% of the time`); }

// ---- 6) the chest motion channel (100 Hz) against the old estimators ---------------------------------------------------------------------------
console.log('--- chest motion channel: new tracker vs the old zero-crossing / first-autocorrelation-peak estimators ---');
function legacy(vis, heartBuf, VFS) {   // the estimators that were in the page before (estimateRates)
  const N = heartBuf.length, seg = heartBuf.slice(N - VFS * 5); let mean = 0; for (const v of seg) mean += v; mean /= seg.length; const z = seg.map(v => v - mean); const e0 = z.reduce((a, v) => a + v * v, 0) || 1; let bestLag = 0, prev = -1, cur = -1;
  for (let lag = 33; lag <= 150; lag++) { let s = 0; for (let i = lag; i < z.length; i++) s += z[i] * z[i - lag]; const r = s / e0; if (cur > prev && cur >= r && cur > 0.2) { bestLag = lag - 1; break; } prev = cur; cur = r; }
  const v = vis.slice(-VFS * 8); let zc = 0; for (let i = 1; i < v.length; i++) if ((v[i - 1] < 0) !== (v[i] < 0)) zc++;
  return {bpm: bestLag ? Math.round(60 * VFS / bestLag) : null, br: v.length > VFS * 6 ? Math.round(zc / 2 * 60 / (v.length / VFS)) : null}; }
function chestRun(perMin, bpm, noise, secs = 90) {
  const VFS = 100, N = secs * VFS, fHp = bq('hp', 0.1, 0.7, VFS), fLp = bq('lp', 5, 0.7, VFS), h1 = bq('hp', 0.8, 0.7, VFS), h2 = bq('hp', 0.8, 0.7, VFS), h3 = bq('lp', 3, 0.7, VFS);
  const pr = new VitalsPR(), vis = [], hb = []; let lb = [], lh = [], lbr = [], nL = 0;
  for (let i = 0; i < N; i++) { const t = i / VFS; const breath = Math.sin(2 * Math.PI * perMin / 60 * t + 0.4 * Math.sin(0.05 * t)) + 0.3 * Math.sin(2 * Math.PI * perMin / 30 * t);
    const ph = (t * bpm / 60) % 1, beat = 0.12 * (Math.exp(-((ph - 0.1) ** 2) / 0.002) - 0.6 * Math.exp(-((ph - 0.3) ** 2) / 0.004));
    const v = breath + beat + noise * gauss(); const w = fLp(fHp(v)), hs = h3(h2(h1(v))); vis.push(w); hb.push(hs); if (hb.length > 800) hb.shift(); if (vis.length > 800) vis.shift();
    pr.motion(hs, w, false);
    if (t > 50 && i % 100 === 0) { const L = legacy(vis, hb, VFS); lb.push(L.br); lh.push(L.bpm); if (pr.chest.locked || pr.chest.weak) lbr.push(pr.chest.bpm); nL++; } }
  const med = a => { a = a.filter(v => v != null && !isNaN(v)).sort((p, q) => p - q); return a.length ? a[a.length >> 1] : NaN; };
  const meanErr = (a, t) => { a = a.filter(v => v != null && !isNaN(v)); return a.length ? a.reduce((s, v) => s + Math.abs(v - t), 0) / a.length : NaN; };
  return {oldBr: meanErr(lb, perMin), newBr: meanErr(lbr, perMin), shown: lbr.length / nL, oldBpm: meanErr(lh, bpm), heartV: pr.heartV.weak || pr.heartV.locked ? pr.heartV.bpm : NaN, brNew: med(lbr)}; }
for (const [pm, bpm, noise] of [[14, 72, 0.05], [18, 66, 0.15], [22, 84, 0.3], [12, 90, 0.5]]) { seed = 900 + pm; const r = chestRun(pm, bpm, noise);
  console.log(`      breath ${pm}/min, heart ${bpm}, noise ${noise}: breath error old ${r.oldBr.toFixed(1)} -> new ${isNaN(r.newBr) ? '  - ' : r.newBr.toFixed(1)} /min (new shown ${(100 * r.shown).toFixed(0)}% of the time); heart (motion) old err ${r.oldBpm.toFixed(1)}, new reads ${isNaN(r.heartV) ? '-' : r.heartV.toFixed(1)}`);
  check(r.shown > 0.8 && r.newBr <= 1.0, `breath rate from chest motion at ${pm}/min, noise ${noise}: mean error ${r.newBr.toFixed(2)} /min (old method ${r.oldBr.toFixed(2)})`); }

process.stdout.write(fails ? `\nSOME FAILED (${fails})\n` : '\nALL PASS\n');
process.exit(fails ? 1 : 0);
