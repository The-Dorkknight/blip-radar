# Sound out of the node (no phone needed)

The cleaned-up Stetho audio can play straight from the ESP32. Choose **one** output at a time in the Stetho tab under *Sound out of the node itself*. Both work with no phone connected. The last setting is remembered.

**Status:** firmware compiles; not yet tried on hardware.

## 1. 3.5 mm earphones: delta-sigma on one pin
The ESP32's I2S peripheral, in PDM mode, puts out a 1-bit delta-sigma (pulse-density) stream of about 2 MHz on a single pin. This is the "pseudo-PWM" audio you asked for. An RC low-pass turns it back into audio. The peripheral is DMA-clocked, so there is no timer jitter, unlike bit-banging a GPIO.

```
GPIO (PDM) ──[ 470 Ω ]──┬──||──────► 3.5 mm tip + ring (both ears, mono)
                        │ 220 µF (+ on the left)
                      100 nF
                        │
GND ────────────────────┴──────────► 3.5 mm sleeve
```

| Board | PDM pin | (PDM clock, leave unconnected) |
|---|---|---|
| ESP32-C3 Super Mini | GPIO10 | GPIO3 |
| Waveshare ESP32-S3-Pico | GPIO16 | GPIO13 |

- 470 Ω + 100 nF form a ≈3.4 kHz low-pass, just under the 4 kHz audio band at 8 kHz sampling.
- The 220 µF blocks the 1.65 V average. With 32 Ω earphones it keeps bass down to ≈23 Hz, and heart sounds live at 20–150 Hz. A smaller cap thins the sound.
- The volume is modest and plenty for earbuds. **Start with Node volume low.** If you plug it into a powered speaker's AUX input instead, keep the cap.
- Wired earbuds with an in-line mic (TRRS) work too: tip and ring are the ears.

## 2. I2S amplifier board (MAX98357A and friends)
A ~£3 MAX98357A board takes digital I2S and drives a 4–8 Ω speaker at up to ~3 W.

| Amp pin | C3 Super Mini | S3-Pico |
|---|---|---|
| VIN | 5V | VBUS |
| GND | GND | GND |
| BCLK | GPIO3 | GPIO13 |
| LRC | GPIO4 | GPIO14 |
| DIN | GPIO5 | GPIO15 |
| GAIN, SD | leave open | leave open |

The firmware sends the same sample to left and right, so the board's default "(L+R)/2" mode and its "left only" mode both play it at full level.

"I2C amp": cheap amp boards are usually I2S (three wires: BCLK, LRC, DIN), not I2C. If yours is an analogue class-D board (PAM8403 and the like, with L/R/GND audio inputs), feed it from the earphone circuit above instead.

**Feedback warning:** a speaker near the radar module will be heard by the radar (the cone moves!). That's a loop. Point the speaker away, keep the volume down, or use earphones.

## Pins come from one place
All pins are build flags in `firmware/platformio.ini`; the diagrams in `docs/images/` are drawn from them by `tools/draw_illustrations.py`. The S3-Pico's GP2–GP5 = GPIO13–16 mapping follows Waveshare's numbering pattern. Check it against Waveshare's pinout before soldering.
