"""Blip — Python port of firmware/include/rd03d.h (RD-03D frame parser).

Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.

Used by the simulator and by tests/test_parser_py.py, which checks that the
Python and C++ parsers agree on the same byte streams.
"""
HDR = bytes([0xAA, 0xFF, 0x03, 0x00])
TAIL = bytes([0x55, 0xCC])
FRAME_LEN = 30
CMD_SINGLE_TARGET = bytes([0xFD, 0xFC, 0xFB, 0xFA, 0x02, 0x00, 0x80, 0x00, 0x04, 0x03, 0x02, 0x01])
CMD_MULTI_TARGET = bytes([0xFD, 0xFC, 0xFB, 0xFA, 0x02, 0x00, 0x90, 0x00, 0x04, 0x03, 0x02, 0x01])


class Target:
    __slots__ = ("present", "x_mm", "y_mm", "v_cms", "res_mm")

    def __init__(self):
        self.present = False
        self.x_mm = self.y_mm = self.v_cms = self.res_mm = 0


class Frame:
    def __init__(self):
        self.t = [Target(), Target(), Target()]
        self.count = 0
        self.alive = False


def decode_signed(lo, hi):
    raw = lo | (hi << 8)
    mag = raw & 0x7FFF
    return mag if raw & 0x8000 else -mag


def decode(f):
    fr = Frame()
    for i in range(3):
        p = f[4 + i * 8: 12 + i * 8]
        t = fr.t[i]
        t.x_mm = decode_signed(p[0], p[1])
        t.y_mm = decode_signed(p[2], p[3])
        t.v_cms = decode_signed(p[4], p[5])
        t.res_mm = p[6] | (p[7] << 8)
        t.present = any(p)
        if t.present:
            fr.count += 1
    return fr


class Parser:
    def __init__(self):
        self.buf = bytearray()
        self.frames = 0
        self.bad = 0

    def feed(self, b):
        self.buf.append(b)
        if len(self.buf) <= 4:
            if self.buf != HDR[:len(self.buf)]:
                self._resync()
            return None
        if len(self.buf) < FRAME_LEN:
            return None
        if self.buf[-2:] == TAIL:
            fr = decode(bytes(self.buf))
            self.frames += 1
            self.buf.clear()
            return fr
        self.bad += 1
        self._resync()
        return None

    def _resync(self):
        while self.buf:
            del self.buf[0]
            k = min(4, len(self.buf))
            if self.buf[:k] == HDR[:k]:
                return
