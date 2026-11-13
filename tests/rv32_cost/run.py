#!/usr/bin/env python3
"""tests/rv32_cost/run.py — CPU cost of the Stetho audio path on the ESP32-C3 core, no board needed.

    python3 tests/rv32_cost/run.py            # prints the table; exit 1 if over budget
    pip install unicorn                        # the one extra thing needed (an emulator, ~10 MB)

It needs the RISC-V compiler PlatformIO installs for the C3 (run `pio run -e c3-supermini` once, or set
RV32_TOOLCHAIN to the folder that contains bin/riscv32-esp-elf-g++). The audio chain is compiled for
RV32IMC exactly as the firmware is (-Os), executed in Unicorn and every instruction is counted.
Instructions are not cycles: the C3 core is close to one instruction per cycle on this kind of code,
but flash-cache misses (while Wi-Fi code evicts the DSP from the cache) cost extra. So the table shows
the load at 1.0 and at 1.5 cycles per instruction. The budget is deliberately generous.
"""
import bisect, collections, glob, os, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
INC = os.path.join(os.path.dirname(os.path.dirname(HERE)), "firmware", "include")
CPU_HZ = 160e6          # Arduino-ESP32 default for the C3
FS = 8000
BUDGET_PCT = 25.0       # of the core at 1.5 cycles per instruction; fail above this


def find_toolchain():
    cands = [os.environ.get("RV32_TOOLCHAIN", "")]
    for base in (os.path.expanduser("~/.platformio"), os.environ.get("PLATFORMIO_CORE_DIR", "")):
        if base:
            cands += glob.glob(os.path.join(base, "tools", "toolchain-riscv32-esp"))
            cands += glob.glob(os.path.join(base, "packages", "toolchain-riscv32-esp"))
    for c in cands:
        if c and os.path.exists(os.path.join(c, "bin", "riscv32-esp-elf-g++")):
            return os.path.join(c, "bin", "riscv32-esp-elf-")
    return None


def build(tc, opt, out):
    arch = "-march=rv32imc_zicsr_zifencei -mabi=ilp32"
    cf = f"{arch} -mno-relax -fno-exceptions -fno-rtti -ffunction-sections -fno-use-cxa-atexit -std=gnu++2b -I{INC}"
    o, st, elf = (os.path.join(out, n) for n in (f"b_{opt}.o", "start.o", f"b_{opt}.elf"))
    cmds = [f"{tc}g++ {cf} -{opt} -c {HERE}/bench.cpp -o {o}",
            f"{tc}gcc {arch} -c {HERE}/start.S -o {st}",
            f"{tc}g++ {arch} -nostartfiles --specs=nosys.specs -T {HERE}/link.ld {st} {o} -o {elf} -lm",
            f"{tc}objcopy -O binary {elf} {elf[:-4]}.bin"]
    for c in cmds:
        r = subprocess.run(c, shell=True, capture_output=True, text=True)
        if r.returncode:
            sys.exit("build failed:\n" + c + "\n" + r.stderr[-1500:])
    syms = []
    for l in subprocess.check_output(f"{tc}nm -n {elf}", shell=True, text=True).splitlines():
        p = l.split()
        if len(p) == 3 and p[1] in "tTwW":
            syms.append((int(p[0], 16), p[2]))
    return elf[:-4] + ".bin", syms


def run(binpath, syms, preset, ns, bump, agc, n):
    from unicorn import Uc, UC_ARCH_RISCV, UC_MODE_RISCV32, UC_HOOK_CODE
    d = {name: a for a, name in syms}
    mu = Uc(UC_ARCH_RISCV, UC_MODE_RISCV32)
    mu.mem_map(0x80000000, 0x400000)
    mu.mem_write(0x80000000, open(binpath, "rb").read())
    mu.mem_write(0x80300000, struct.pack("<5I", preset, ns, bump, agc, n))
    addrs, names = [a for a, _ in syms], [nm for _, nm in syms]
    cnt, total = collections.Counter(), [0]

    def hook(uc, addr, size, ud):
        total[0] += 1
        cnt[names[bisect.bisect_right(addrs, addr) - 1]] += 1
    mu.emu_start(0x80000000, d["mark_begin"])           # constructors, configure(), warm-up: not counted
    mu.hook_add(UC_HOOK_CODE, hook)
    mu.ctl_flush_tb()                                    # blocks translated before the hook have no hook compiled in
    mu.emu_start(d["mark_begin"], d["mark_end"])
    return total[0], cnt


def main():
    try:
        import unicorn  # noqa: F401
    except ImportError:
        print("SKIP: the Unicorn emulator is not installed (pip install unicorn)")
        return 0
    tc = find_toolchain()
    if not tc:
        print("SKIP: no RISC-V toolchain found. Run `pio run -e c3-supermini` once (it installs one), or set RV32_TOOLCHAIN.")
        return 0
    n = int(os.environ.get("RV32_SAMPLES", "1200"))
    out = os.environ.get("RV32_OUT", "/tmp/blip_rv32_cost")
    os.makedirs(out, exist_ok=True)
    worst = 0.0
    print(f"Stetho audio path on the ESP32-C3 core ({CPU_HZ/1e6:.0f} MHz, RV32IMC), {n} samples counted per row\n")
    print(f"{'build':5s} {'preset':18s} {'instr/sample':>12s} {'M instr/s':>10s} {'load @1.0 CPI':>14s} {'@1.5 CPI':>9s}")
    for opt in ("Os", "O2"):
        binpath, syms = build(tc, opt, out)
        for name, (pr, ns, bp, agc) in {"heart": (0, 60, 50, 1), "lungs": (1, 60, 50, 1), "voice": (2, 60, 50, 1), "wide": (3, 60, 50, 1),
                                        "raw": (4, 0, 0, 1)}.items():
            tot, cnt = run(binpath, syms, pr, ns, bp, agc, n)
            per = tot / n
            l1 = per * FS / CPU_HZ * 100
            print(f"-{opt:4s} {name:18s} {per:12.0f} {per*FS/1e6:10.2f} {l1:13.1f}% {l1*1.5:8.1f}%")
            if opt == "Os":                      # the Arduino build uses -Os
                worst = max(worst, l1 * 1.5)
    print(f"\nWorst preset at -Os, 1.5 cycles/instruction: {worst:.1f}% of the core (budget {BUDGET_PCT:.0f}%).")
    if worst > BUDGET_PCT:
        print("FAIL: over budget. The single-core C3 also runs Wi-Fi, lwIP and the web server.")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
