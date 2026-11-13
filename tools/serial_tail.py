#!/usr/bin/env python3
"""Blip — print a board's serial output until stopped (used by the Flash tab; no terminal needed).

Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.

    python3 tools/serial_tail.py /dev/ttyACM0 115200

Needs pyserial, which PlatformIO installs into ./.venv. DTR and RTS are held low
so that opening the port does not reset the board. After a flash the C3 re-appears
on its USB port a moment later, so opening is retried for a few seconds.
"""
import sys
import time

try:
    import serial
except ImportError:
    print("pyserial is not installed for this Python. Flash once from the Flash tab (it installs PlatformIO, which brings pyserial).")
    sys.exit(2)


def main():
    if len(sys.argv) < 2:
        print("usage: serial_tail.py PORT [BAUD]")
        return 2
    port = sys.argv[1]
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 115200
    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout = port, baud, 0.2
    ser.dtr = False
    ser.rts = False
    last_err = None
    for _ in range(25):
        try:
            ser.open()
            break
        except (serial.SerialException, OSError) as e:
            last_err = e
            time.sleep(0.3)
    else:
        print("Could not open %s: %s" % (port, last_err))
        return 1
    print("--- %s open at %d baud ---" % (port, baud), flush=True)
    buf = b""
    try:
        while True:
            try:
                data = ser.read(256)
            except (serial.SerialException, OSError):
                print("--- %s went away (unplugged or reset into the bootloader) ---" % port, flush=True)
                return 1
            if not data:
                continue
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                print(line.decode("utf-8", "replace").rstrip("\r"), flush=True)
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            ser.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
