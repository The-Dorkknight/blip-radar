# Blip bench test

A separate, standalone firmware for checking an ESP32-C3 Super Mini or
Waveshare ESP32-S3-Pico board **before** you wire it up — in case a cheap
batch has a bad unit in it. It is not part of the Blip app and doesn't touch
the radar, OLED or settings; it just runs a set of pass/fail checks and
prints the result to Serial.

## Flashing it

Easiest: in the Blip flasher open the **Diagnostics** tab, pick your board and
press *Flash the bench test*. The results print in the log below (the serial
output is always shown there). Switch to the **Flash Blip** tab and flash
Blip again when you're done.

With PlatformIO (`pio` on your PATH, from the `firmware/` folder):

```
pio run -e c3-supermini-bench -t upload   # ESP32-C3 Super Mini
pio run -e s3-pico-bench -t upload        # Waveshare ESP32-S3-Pico
```

Without PlatformIO, flash the merged image directly with esptool (the same
`esptool` the Quick-flash tool installs into its own venv works fine here):

```
esptool.py --chip esp32c3 --port <PORT> write_flash 0x0 firmware/prebuilt/blip-c3-supermini-bench-full.bin
esptool.py --chip esp32s3 --port <PORT> write_flash 0x0 firmware/prebuilt/blip-s3-pico-bench-full.bin
```

Then open a serial monitor at 115200 baud (`pio device monitor`, the
flasher's own 🔌 USB log button pointed at this firmware, or any terminal
program) and reset the board to see it start.

## What it checks

**Stage 1** (automatic, ~15 s, nothing extra needed): chip identity and
flash size, a RAM march test over the largest free block of on-chip SRAM,
a PSRAM size + address-pattern walk (S3-Pico only), a **fake-flash check**
(read-only: a chip that claims more capacity than it has usually wraps
round, so reading a high address gives back the bootloader; also compares
the chip's own ID with the size Blip expects), a flash/NVS
scratch write, a Wi-Fi scan (proves the radio can receive) plus bringing up
an AP (proves it can transmit), a sanity read on the Stetho ADC pin, an I2C
bus scan (OLED is optional — not found is reported, not failed), and a UART
loopback check on the radar RX/TX pins (SKIPped rather than failed if you
haven't jumpered them together).

**Stage 2** (needs a phone or laptop; runs 2 minutes): starts the real
`Stetho` sampler and the real Wi-Fi AP + web server together, the combination
that has been resetting some boards. Join the hotspot it prints
(`Blip-Bench-xxxx`, password `blipblip`), then **open `http://192.168.4.1/` in a
browser** (turn mobile data off if it won't load). The page holds a WebSocket
and counts the Stetho audio the board streams to it, like the real app. The
timer starts when the page connects, and each second's line shows pages open
and packets sent/skipped. If the board survives 2 minutes it prints
`Stage 2: PASS`. If it resets instead, the *next* boot reads an RTC marker left
just before the crash and reports `Stage 2: FAILED - reset after Ns`, with the
reset reason.

A bare Wi-Fi join without the page open sends no audio, so it does not test
the path that crashes; a first bench run that did only that passed 2 minutes
twice on a board that crashes in the app.

Run stage 2 on a few different physical boards: if some sail through while
others reset at roughly the same point every time, that's a real difference
between those specific chips — evidence this is (at least partly) a
board-quality problem, not only a firmware one. If every board fails the
same way, that points back at the firmware.

## Can "fake" RAM cause the crash?

Very unlikely. The C3's 400 KB of SRAM and the S3-Pico's 2 MB PSRAM are
inside the chip package, so a seller can't fit a smaller part, and Espressif
doesn't sell speed- or memory-binned grades of these chips. Bad RAM gives
random bit-flips and crashes in random places; the Stetho crash happens in
the same task, a few seconds in, every time, which points at software.
A buffer overflow is a code bug whatever the RAM. The part that *is* sometimes
faked or relabelled is a separate **flash** chip (the S3-Pico has one; many
C3 Super Minis use the C3FH4, with 4 MB flash inside the package), which is
why the fake-flash check is there. Other real board-to-board differences:
the antenna, the 3.3 V regulator (brown-outs) and the crystal.

## Limits

This is a bench tool, not a factory test jig: stage 1's GPIO/UART checks
need you to jumper the relevant pins to be meaningful (they report SKIP, not
FAIL, when nothing's jumpered), and nothing here is a substitute for the
real app running on real hardware for a real session.
