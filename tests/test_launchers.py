#!/usr/bin/env python3
"""Blip — checks the double-click launchers exist, are executable and have the right line endings."""
import os, stat, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0
for name in ("Blip-Linux.sh", "Blip-Mac.command"):
    p = os.path.join(ROOT, name)
    ok = os.path.exists(p) and os.stat(p).st_mode & stat.S_IXUSR and b"\r\n" not in open(p, "rb").read()
    print(("PASS  " if ok else "FAIL  ") + name + " exists, executable, LF"); fails += not ok
for name in ("Blip-Windows.bat",):
    p = os.path.join(ROOT, name)
    data = open(p, "rb").read() if os.path.exists(p) else b""
    ok = bool(data) and data.count(b"\r\n") == data.count(b"\n")
    print(("PASS  " if ok else "FAIL  ") + name + " exists, CRLF"); fails += not ok
print("\nRESULT:", "FAIL" if fails else "PASS", f"({fails} failures)")
sys.exit(1 if fails else 0)
