# Stetho signal notes: static, chirps, post-bump dropout, pattern recognition

> **Update 2026-11-13:** a different route exists: the custom LD2450 firmware (earlynerd/HLK-LD2450_FW) exposes range-bin phase, and its author shows heartbeats at about 0.8 m with it. See [RADAR_TRACKING_NOTES.md](RADAR_TRACKING_NOTES.md) §7. Not tried with Blip yet.

> **Status: abandoned, kept as an optional install (2026-11-10).** Author's note: *"Needing to build an ultra-low-noise, ultra-high-gain, fast-slew-rate instrumentation amplifier is just too much work for a 'fun' 30-minute project, but I encourage anyone gifted enough with analogue, or mad enough, to carry on my research 😉"*

Written 2026-11-08 for Blip 0.2.2-wip. Everything measured here was measured on a PC with **synthetic** signals. No claim below has been confirmed on a real board.

## What you reported
1. Static that sounds like 5 to 10 heavy breaths a second, now and then with a 2 to 10 kHz chirp.
2. Big movements: latency fine at first. Once a bump is detected there is about half a second of delay and strong attenuation of any signal.

## 2) Post-bump dropout: found, fixed, tested
Cause, from reading and running the old chain:
- The bump gate muted by 30 dB, held 150 ms and released over 120 ms: about 0.3 s of near silence by design.
- Worse, the AGC's level estimate and the noise-floor cap kept learning from the knock (a peak-like estimate with a 1 s decay), so the gain came back 15 to 48 dB too low and took seconds to recover. That is the "massive attenuation".
- The bump detector often did not fire on a body movement, so none of the above was even needed to cause trouble.

Changes (all in `firmware/include/audio_dsp.h`): shallow duck; 2 ms look-ahead limiter before the soft clip; estimators frozen during a bump or detected movement; a level-excursion detector that holds the AGC (3 s cap) and speeds the level decay when the level jumps above 3.5 times its 10 s typical value. Test scenes in `tests/test_dsp_dynamics.cpp` check the recovery in dB per beat after knocks and movements.

Limit: the freeze means a genuinely louder signal that lasts longer than 3 s is only followed after the cap. The test "step +12 dB unfreezes" covers the normal case.

## 1) Static and chirps: what is known and what is a hypothesis
Not known. I have no recording from your hardware. Candidates, with how each would show up in a recording (`tools/analyze_wav.py` reports these):

| Candidate | Why it fits | What the analyzer shows | Remedy to try |
|---|---|---|---|
| Wi-Fi beacon (every 102.4 ms, about 9.8 per second) pulling the 3V3 rail or the ADC | "5 to 10 a second" matches 9.8 | bursts above 1 kHz on a ~102 ms beat | 4x averaging, burst blanker, 100 uF + 10 ohm RC on the MAX4466 supply, antenna away from the radar board |
| Doppler peaks clipping (rail) then aliasing | chirps 2 to 10 kHz while moving | "at the rail" more than 0.5 %, burst timing irregular | lower radar-board gain or the MAX4466 pot; add an input RC low-pass before the ADC |
| ADC and MAX4466 noise | hiss | energy spread above 800 Hz, no rhythm | averaging, a smaller gain, noise suppression |
| Noise suppression artefacts ("musical noise") | static can come from NS | **refuted** on stationary noise in a test | no change |

The ADC runs at 8 kHz with no analogue anti-alias filter in the usual build, so anything above 4 kHz in the radar's IF output folds into the band. An RC low-pass of roughly 1.5 kHz (for example 1 kOhm + 100 nF) between the MAX4466 output and the ADC pin is the standard fix and costs nothing in the heartbeat band. The firmware cannot do that part.

### Added techniques
- **Burst blanker** (noise-blanker style, as in radio receivers): detect the burst in a high-pass copy, gate a delayed copy of the signal for at most 12 ms. Test: removes beacon-like bursts, under 1.5 % false blanking on a plain heart signal, never active in Voice, Wide or Raw.
- **Averaged ADC sampling with a trimmed mean** (`os` 2, 4, 8): removes single-sample spikes. 4x costs about 4x ADC throughput (32 kS/s into DMA), well within the C3.
- **Limiter, freeze and excursion hold:** see above.

### The A/B procedure (about 5 minutes, no reflash)
1. Stetho tab, preset **Raw**, ADC sampling **Normal**, blanker **Off**. Press *Record 10 s*. Hold still for the first half, wave a hand for the second.
2. Same with **4x average**. Then preset **Heart** with the blanker **On** and **Off**.
3. `python3 tools/analyze_wav.py file1.wav file2.wav ...` and send the output (and the files, if you can). The analyzer says whether bursts sit on 102.4 ms.

If bursts are on the beat: the hardware remedy (supply RC filter) is the real fix; averaging and the blanker are mitigations. If the rail figure is high: it is gain, not Wi-Fi.

## Pattern recognition (page side, `CycleTracker` in `web/index.html`)
1. 10 ms RMS envelope of the sound (heart) or 1 s average (lungs); the chest-motion channel is used directly.
2. Autocorrelation over the last 8 s (heart) or 40 s (breath). Score is r(L) + 0.5 r(2L), so the true period beats its multiples. Then walk down: if a shorter lag has a strong enough peak it wins, so 72 bpm is not read as 36 and 140 bpm not as 70.
3. **Epoch folding:** fold the signal on candidate periods within +-6 % of the estimate, pick the period with the sharpest folded template. That gives a rate good to a fraction of a beat per minute and a beat template.
4. Quality is the geometric mean of the autocorrelation strength and the fold contrast. `locked` at 0.45 or more, `weak` at 0.10 or more (shown with a `?`). Packets flagged as bump or rail are excluded from the statistics; lost packets advance the clock.
5. **Beat lock (gate):** the template says where the cycle is normally quiet; a gate (5 ms open, 25 ms close) turns those parts down by at most 9 dB (heart) or 6 dB (lungs) scaled by the lock quality, and only when locked. Off by default.

Verified (`tests/test_vitals_pr.js`): the rate grid, heart-rate variability of +-6 %, S2 as loud as S1, a bump every 3.1 s, 6 % lost packets, no lock on noise or on irregular knocks, prediction of the next S1 (median miss 14 ms at 3 % jitter), gate effect, breathing from lung sound and from chest motion against the old estimators.

Known limits:
- 48 bpm in weak signal has only about six beats in the 8 s window, so it is shown only about half the time (never wrongly).
- Irregular knocks show a `?` rate about 12 % of the time (never a full lock).
- S1 and S2 cannot be told apart from loudness alone; the tracker reports the beat rate, which is right either way.
- At 170 bpm and a weak signal the rate can be off by several bpm.
- Real chests, real hair, real posture are not in the tests. Treat the numbers as plausible, not validated. This is not a medical device.

## Not done
- Beat thumps still trigger from chest-motion peaks, not from the predicted beat time.
- Oversampling is off by default until the A/B above says it helps.
- Nothing here has run on the board: the firmware compiles for all six environments and the chain is verified on a PC (sanitizers and an RV32 instruction count).

## Bench results (2026-11-09, real hardware, user recordings analysed with tools/analyze_wav.py)
1. **Static and chirps: not Wi-Fi, not clipping.** Raw recording with the radar disconnected: steady broadband noise (about -37 dBFS rms, 20 to 800 Hz), no 102.4 ms burst train, nothing at the rail, no mains lines. A loose supply capacitor had come adrift; with a 100 uF cap on the MAX4466 and on the radar the static went away (bursts above 1 kHz 17.7/s down to 1.4/s). The beacon theory above was not confirmed. I did not prove the cap alone was the fix, because the two recordings used different presets.
2. **Moving hand, 10 s Heart preset:** still about -47 dBFS, hand about -15 dBFS (30 dB up), energy in 60 to 150 Hz, no dropout after the movement starts (the post-bump fix behaves).
3. **Chest at 2 cm, Heart preset:** no repeating pattern (best repeat strength 0.29 against 0.4 for a clear pattern), noise at the same level as the heartbeat, mostly 35 to 49 Hz. Turning the MAX4466 gain up raised signal and noise together.
4. **Why (hypothesis, not measured):** a single-channel CW Doppler module sees heartbeat as a tiny phase change (about 0.2 mm, roughly 0.2 rad at 24 GHz, 20 to 30 dB below breathing) and has nulls where it is blind. Fixing it properly means a quadrature (I/Q) module and a custom ultra-low-noise, high-gain, fast-slew instrumentation amplifier. That is a different project.
5. **Ideas parked:** I/Q 24 GHz modules (RFbeam K-LC series, Innosent IPS-265, Fujitsu FWM7RAZ01 were found in a web search; prices not checked); a "Thing"-style passive cavity microphone at 24 GHz (needs a resonator at millimetre scale and a sensitive phase point; a speaker-cone tone test was proposed, not run). Breathing and heart *rate* at range are the realistic goals; heart *sounds* are not.
