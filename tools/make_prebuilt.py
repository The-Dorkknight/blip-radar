#!/usr/bin/env python3
"""Blip — refresh the bundled firmware in firmware/prebuilt/ from a PlatformIO build.

Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.

    pio run -d firmware                      # builds every env
    python3 tools/make_prebuilt.py           # copies the whole-chip images + writes manifest.json
    python3 tools/make_prebuilt.py --build-dir /some/other/.pio/build

For each env it copies firmware.factory.bin (bootloader + partition table + app,
flashed at 0x0) to firmware/prebuilt/blip-<env>-full.bin and records in
manifest.json: the version, the build time, each image's SHA-256 and size, and a
hash of the source it was built from (tools/flasher.py: source_hash). The Flash
tab checks the image against the manifest before writing it and tells you if the
source in your folder has changed since.

Each run also adds an entry at the top of firmware/prebuilt/BUILD_LOG.md (what
changed, version, time, source hash and every image's SHA-256), so a build stays
identifiable after its binaries have been pruned from the git history.
    python3 tools/make_prebuilt.py --note "Stetho: fewer, bigger packets"
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flasher  # noqa: E402

ENVS = ["c3-supermini", "s3-pico", "c3-supermini-ld2450", "s3-pico-ld2450", "c3-supermini-bench", "s3-pico-bench"]
CHIP = {"c3": "esp32c3", "s3": "esp32s3"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build-dir", default=os.path.join(flasher.FIRMWARE, ".pio", "build"))
    ap.add_argument("--out", default=os.path.join(flasher.FIRMWARE, "prebuilt"))
    ap.add_argument("--note", default="", help="one line for BUILD_LOG.md: what changed in this build")
    a = ap.parse_args()
    cfg = open(os.path.join(flasher.FIRMWARE, "include", "config.h"), encoding="utf-8").read()
    version = re.search(r'#define BLIP_VERSION "([^"]+)"', cfg).group(1)
    os.makedirs(a.out, exist_ok=True)
    images = {}
    for env in ENVS:
        src = os.path.join(a.build_dir, env, "firmware.factory.bin")
        if not os.path.isfile(src):
            print("missing %s — build it first (pio run -d firmware -e %s)" % (src, env))
            return 1
        name = "blip-%s-full.bin" % env
        dst = os.path.join(a.out, name)
        shutil.copyfile(src, dst)
        images[env] = {"file": name, "chip": CHIP[env[:2]], "address": "0x0",
                       "sha256": flasher.sha256_file(dst), "size": os.path.getsize(dst)}
        print("%-22s %8d bytes  %s" % (env, images[env]["size"], images[env]["sha256"][:16]))
    man = {"app": "Blip", "version": version, "built": time.strftime("%Y-%m-%d %H:%M"),
           "source": flasher.source_hash(), "images": images,
           "note": "Whole-chip images: write at 0x0 (esptool --chip <chip> write_flash 0x0 <file>). "
                   "Checked by the Flash tab before flashing. Regenerate with tools/make_prebuilt.py."}
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2)
        f.write("\n")
    print("wrote %s (Blip %s)" % (os.path.join(a.out, "manifest.json"), version))
    log_build(os.path.join(a.out, "BUILD_LOG.md"), man, a.note)
    return 0


LOG_HEAD = """# Bundled firmware build log

`tools/make_prebuilt.py` adds an entry here (newest first) every time it refreshes `firmware/prebuilt/`.
The git history keeps the binaries of the **last 3 builds** only (see PUBLISHING.md); older builds are listed
here so they stay identifiable by version, time and SHA-256.

"""


def log_entry(man, note):
    rows = "\n".join("| `%s` | %s | %d | `%s` |" % (env, im["file"], im["size"], im["sha256"])
                     for env, im in man["images"].items())
    return ("## %s — built %s\n\n%s"
            "Source hash: `%s`\n\n| Build | File | Bytes | SHA-256 |\n|---|---|---|---|\n%s\n\n"
            % (man["version"], man["built"], ("What changed: %s\n\n" % note) if note else "", man["source"], rows))


def log_build(path, man, note):
    old = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
        i = old.find("## ")                      # keep every earlier entry, whatever the header said
        old = old[i:] if i >= 0 else ""
    with open(path, "w", encoding="utf-8") as f:
        f.write(LOG_HEAD + log_entry(man, note) + old)
    print("logged the build in %s" % path)


if __name__ == "__main__":
    sys.exit(main())
