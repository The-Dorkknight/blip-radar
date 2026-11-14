# Radar tracking notes: street test, false contacts, flesh vs steel, range, custom firmware

Written 2026-11-13 after the first outdoor walk with the RD-03D. Sources are linked at the end.
Anything marked **(untested)** is an idea or someone else's result, not something measured on Blip.

## 1. What the street test showed (author, 2026-11-13)

- A **persistent contact at 0.2–0.3 m**, whatever the surroundings.
- Other contacts appearing **semi-randomly** (urban street: cars, lamp posts about 5 m away).
- Build details: wires soldered to the copper pogo pads, folded back over the board, fixed with
  hot glue melted by a small blowtorch.

## 2. Likely causes

**The radar was being carried.** The RD-03D is made to sit still. Its firmware removes things that
do not move and reports what does. Carry it and *everything* moves relative to it, so lamp posts,
cars and walls all qualify as targets and compete for the three slots. Blip's Smart filter has the
same blind spot: its clutter map is fixed to the radar, so it learns nothing useful while walking.

**The 0.2–0.3 m contact** is closer than the module's usable range (listings give about 0.5–8 m).
Candidates, most likely first; none confirmed:

1. The carrier's own hand/arm/body, which moves a little with every step.
2. Wires folded over the antenna side. Metal a few mm from the patch antennas reflects strongly,
   and wires that wobble while walking look like a moving target at near-zero range.
3. Glue over the patches. Hot glue is a dielectric and slightly detunes a patch; char is carbon,
   which is lossy and a little conductive. A thin clean smear costs little; a blob or char *on the
   patches* costs range. Glue and wires on the back or over the chip are harmless.

**Bench check:** put it on a table facing open space, walk away, watch on the phone. Contact still
at 0.2–0.3 m with nobody near = wires/glue/self-leakage. Gone = it was the carrier.

## 3. Ways to cut false contacts

| Idea | What it does | State in Blip |
|---|---|---|
| Minimum range, adjustable 0.1–1.0 m | Drops the persistent near contact outright | **Done (2026-11-13)**, `gate.h`, Settings |
| **Handheld mode** (ego-motion compensation) | When walking at speed v, a fixed object at bearing θ shows radial speed ≈ −v·cos θ. Contacts that fit that pattern are scenery; ones that do not are real movers. | **Done (2026-11-13)**, `gate.h`: needs two agreeing contacts to lock on, holds the estimate 1.5 s; synthetic tests only; trusts the module's speed field **(untested)** |
| Track-correlation ghost test | Multipath ghosts copy the real target's motion; kill a track whose range history correlates with a nearer one (one patent uses > 0.6) | **Done (2026-11-13)** as the opt-in *Strict ghost test*: correlation of 3 s of ranges > 0.9, slope 0.6–1.4, similar Doppler. Correlating 1-frame or 0.25 s range *changes* was tried first and failed: within a few seconds a walker's range changes are nearly constant, so their correlation is just noise |
| Learned background map | Grid remembers where static reflectors keep appearing | Done (16×16, 0.5 m cells); only valid when the radar is fixed |
| Drop extreme bearings | Detections near the edge of the field of view are more often multi-bounce | **Adjustable (2026-11-13)**: ±65° down to ±30° |
| Module-side zones (LD2450 only) | The radar itself ignores up to three rectangles | Not used by Blip |

Hard limit: the sweep is about 240–250 MHz wide, which gives range bins of roughly 0.6 m. Two
things closer together than that cannot be separated by any software on the stock output.

## 4. Flesh vs steel

Published human/vehicle classifiers use **micro-Doppler** (the spread of speeds from swinging arms
and legs) or **radar cross-section** statistics, taken from the range-Doppler map. The stock
RD-03D/LD2450 output is only x, y and one speed per target, so that information is gone before it
reaches the ESP32. With stock firmware only weak hints are possible **(untested)**:

- a walker's reported speed wobbles at step rate; a lamp post seen from a moving radar does not;
- in handheld mode, steel stays where the ego-motion model says; people do not.

Real classification needs raw or range-bin data, i.e. custom firmware (section 6).

## 5. More range

- Stock tracking stops around 8 m by firmware design.
- A **dielectric lens or small horn/reflector** in front of the patches narrows the beam and adds
  gain (general antenna practice; **untested** here). Cost: narrower field of view.
- With custom firmware the range bins reach about 25 m, and more chirps can be averaged for
  sensitivity. Whether a person is detectable that far is unknown.
- Do **not** widen the sweep beyond 24.00–24.25 GHz or raise transmit power: that leaves the
  licence-free band.

## 6. Custom firmware and raw data

- Both modules use ICLEGEND's **S5KM312CL** radar chip; the LD2450's controller is a **JieLi
  BR23/AC695N**, and Ai-Thinker's RD-03D upgrade tool is also a JieLi downloader.
- **earlynerd/HLK-LD2450_FW** (Oct 2026) is a working experimental replacement firmware for the
  LD2450: flashed over the 4-pin UART, it runs each chirp through the chip's hardware FFT and
  streams range bins (64 chirps/frame, about 11 frames/s) over **USB** to a browser viewer that
  does Doppler, detection, angle and tracking. It includes a 3-second boot recovery window.
  Angle, range scale and velocity sign are not calibrated yet. The README says restoring stock was
  bench-verified; the pull request lists it as unverified. The RD-03D is named but not tested.
- **Analog out: no.** Mixer and ADC are inside the chip; there is no IF pin. What is possible is
  *digital* raw/range-bin data, which is better anyway.
- This corrects DESIGN_NOTES §4, which said raw access was "probably not at all" possible.
- Risk: experimental, could leave a module needing recovery. Try it on a spare LD2450, not the
  only working radar.
- Possible follow-up **(speculative)**: range-bin phase over time is chest motion, so this is also
  a second route to the parked Stetho idea, without the analog amplifier.

## 7. Flashing the LD2450 custom firmware (from its README and UART_UPDATE.md, read 2026-11-13)

- **Bluetooth is only a prerequisite.** The uploader enters update mode with a command (0xB2) that stock **V2.14** has and older stock (e.g. V2.04) lacks, so first update the module to V2.14 with Hi-Link's HLKRadarTool phone app over Bluetooth, and set its UART to 256000 baud there (V2.14 can come up at 9600).
- **The firmware itself goes over the 4-pin plug** (5V, GND, TX, RX) through a USB-serial adapter at 256000 baud: `uart_upload.py <image> --port <port> --entry stock-b2`. Later updates use `--entry custom`; every custom image keeps the updater and a 3-second boot recovery window (power-cycle the radar while the uploader waits).
- **Restore:** `restore_stock.py --port <port>` writes Hi-Link V2.14 back (the vendor loader inside gets two small instruction fixes so it can receive at 256000). Afterwards stock runs at 9600 baud.
- **Data out:** the range-bin stream (64 chirps × bins −40…40, about 11 frames/s, 540 kB/s) uses the radar MCU's **own USB** (AC6956C pins 23/24, D−/D+), which the board brings out to test pads, not the 4-pin plug. The author solders a USB cable (D+, D−, GND) to those pads; it enumerates as VID:PID 4C4A:4155.
- **Heartbeat:** its README shows breathing (~3 mm per breath) and, during a breath hold, 24 heartbeats (~50 µm each, ~3° of phase) from a person sitting at about 0.8 m. That is the signal the parked Stetho channel never got out of the CDM324. A second route to the Stetho idea, digital, no analogue amplifier.
- **In Blip:** the flasher's ☢ tab wraps exactly these commands (pinned commit `92d0ed11cc34`, image SHA-256 checked, typed BRICK for writes). Not yet run on a real radar.
- Ideas for later **(speculative)**: an ESP32-S3 as USB host could read that stream and bring range-Doppler and vital signs into Blip's phone page.

## Sources

- Ai-Thinker RD-03D docs: https://docs.ai-thinker.com/en/Rd-03D_V1/
- RD-03D user manual (JieLi upgrade tool): https://aithinker-static.oss-cn-shenzhen.aliyuncs.com/docs/_media_old/rd-03d_multi-target_trajectory_tracking_user_manual.pdf
- espboards RD-03D page (0.5–8 m): https://www.espboards.dev/sensors/rd03/
- Custom firmware: https://github.com/earlynerd/HLK-LD2450_FW and https://github.com/earlynerd/HLK-LD2450_FW/pull/1
- Track-correlation ghost removal (patent US 11327167): https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11327167
- LD2450 security firmware with learned noise map: https://github.com/PeterkoCZ91/HLK-LD2450-security
- Threshold filtering incl. extreme angles: https://arxiv.org/pdf/2601.13364
- Human/vehicle classification, 24 GHz FMCW: https://pmc.ncbi.nlm.nih.gov/articles/PMC7180962 and https://arpi.unipi.it/bitstream/11568/1166560/4/Sensors-39983-2021.R1.Final.Manuscript%5b1%5d.pdf
- HA forum, LD2450 ghosting reports: https://community.home-assistant.io/t/affordable-and-simple-indoor-positioning-system-using-multiple-ld2450-mmwave-radar-sensors/659634/9
