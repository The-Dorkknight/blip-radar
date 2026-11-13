#!/usr/bin/env python3
"""Stand-in for PlatformIO *and* esptool, used by tests/test_flasher.py
(BLIP_PIO / BLIP_ESPTOOL="python3 tests/fake_pio.py"; esptool calls are recognised by write_flash).

Prints what the real `pio run` and esptool print (including esptool's carriage-return
progress lines) and exits 0, or fails the way the common problems fail:

    FAKE_PIO_MODE=ok | builderror | perm | boot | net | slow | slowup (slow upload, for screenshots)
    FAKE_PIO_LOG=<file>     append the argv of every call here
    FAKE_PIO_PID=<file>     write this process's pid here (to check that Cancel kills it)
"""
import os
import signal
import sys
import time

args = sys.argv[1:]
mode = os.environ.get("FAKE_PIO_MODE", "ok")
for var, text in (("FAKE_PIO_LOG", " ".join(args) + "\n"), ("FAKE_PIO_PID", str(os.getpid()))):
    if os.environ.get(var):
        with open(os.environ[var], "a" if var == "FAKE_PIO_LOG" else "w") as f:
            f.write(text)

env = args[args.index("-e") + 1] if "-e" in args else "?"
esptool = "write_flash" in args
upload = "upload" in args or esptool
out = sys.stdout


def say(s, end="\n", pause=0.0):
    out.write(s + end)
    out.flush()
    if pause:
        time.sleep(pause)


if mode == "net" and not upload:
    say("Error: HTTPSConnectionPool(host='dl.registry.platformio.org', port=443): Max retries exceeded")
    sys.exit(1)

if not upload:
    say("Processing %s (platform: espressif32; board: esp32-c3-devkitm-1; framework: arduino)" % env)
    say("------------------------------------------------------------------------")
    for n in range(8):
        say("Compiling .pio/build/%s/src/file%d.cpp.o" % (env, n), pause=0.6 if mode == "slow" else 0.01)
    if mode == "builderror":
        say("src/main.cpp:12:3: error: 'nope' was not declared in this scope")
        say("*** [.pio/build/%s/src/main.cpp.o] Error 1" % env)
        sys.exit(1)
    say("Linking .pio/build/%s/firmware.elf" % env)
    say("Building .pio/build/%s/firmware.bin" % env)
    say("RAM:   [=         ]  13.6% (used 44504 bytes from 327680 bytes)")
    say("Flash: [====      ]  38.0% (used 1193827 bytes from 3145728 bytes)")
    say("========================= [SUCCESS] Took 1.20 seconds =========================")
    sys.exit(0)

if esptool:
    say("esptool.py v4.8.1")
    say("Serial port " + (args[args.index("--port") + 1] if "--port" in args else "/dev/ttyACM0"))
    say("Connecting...")
    say("Chip is %s" % ("ESP32-S3 (QFN56) (revision v0.2)" if "esp32s3" in args else "ESP32-C3 (QFN32) (revision v0.4)"))
else:
    say("Looking for upload port...")
    if "--upload-port" in args:
        say("Using manually specified: " + args[args.index("--upload-port") + 1])
    else:
        say("Auto-detected: /dev/ttyACM0")
    say("Uploading .pio/build/%s/firmware.bin" % env)
    say("esptool.py v4.8.1")
if mode == "perm":
    say("A fatal error occurred: Could not open /dev/ttyACM0, the port is busy or doesn't exist.")
    say("([Errno 13] could not open port /dev/ttyACM0: [Errno 13] Permission denied: '/dev/ttyACM0')")
    sys.exit(1)
if mode == "boot":
    say("A fatal error occurred: Failed to connect to ESP32-C3: No serial data received.")
    sys.exit(1)
segs = ((0x0, os.path.getsize(args[-1]) if esptool and os.path.isfile(args[-1]) else 1304160),) if esptool else \
    ((0x0, 15056), (0x8000, 3072), (0xE000, 8192), (0x10000, 1193827))
for seg, size in segs:
    say("Compressed %d bytes to %d..." % (size, size * 2 // 3))
    steps = 40 if size > 200_000 else 2
    for i in range(1, steps + 1):
        say("Writing at 0x%08x... (%d %%)" % (seg + i * 1000, i * 100 // steps), end="\r", pause=(0.15 if mode == "slowup" else 0.03) if size > 200_000 else 0)
    say("Wrote %d bytes (%d compressed) at 0x%08x in 1.0 seconds" % (size, size * 2 // 3, seg))
    say("Hash of data verified.")
say("Leaving...")
say("Hard resetting via RTS pin...")
say("========================= [SUCCESS] Took 3.50 seconds =========================")
