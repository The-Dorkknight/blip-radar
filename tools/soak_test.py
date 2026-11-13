#!/usr/bin/env python3
"""Blip soak test: find out WHICH part of the node makes Stetho freeze, with one flash.

Join the node's Wi-Fi hotspot (Blip-Radar), then run:

    python3 tools/soak_test.py                    # quick plan, 60 s per trial, ~9 minutes
    python3 tools/soak_test.py --secs 30          # shorter trials
    python3 tools/soak_test.py --plan full        # more trials (priorities, combinations)
    python3 tools/soak_test.py --host 127.0.0.1 --port 8080   # against tools/sim_radar.py

For every trial it (1) sets the node's Lab switches (firmware/include/lab.h, over
/api/lab), (2) restarts Stetho, (3) opens a WebSocket exactly like the phone page does,
and (4) listens for --secs seconds, counting audio packets, sequence gaps and
arrival gaps. If the node stops talking it waits for it to come back, reads the boot
counter and the node's own log (which survives a crash) and records the trial as a
CRASH or STALL. The result is a table: the row that survives while the baseline
crashes names the culprit. A reboot puts every switch back to its default, so a
crashing combination can never leave the node stuck.

Python 3.8+, standard library only. Writes soak_report_<time>.md next to where you run it.
Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""
import argparse
import base64
import json
import os
import select
import socket
import struct
import sys
import time
import urllib.error
import urllib.request

__version__ = "0.1.0"

# ---------------------------------------------------------------------------
# Plans: (name, lab switches, what the trial isolates)
# ---------------------------------------------------------------------------
PLANS = {
    "quick": [
        ("baseline", {}, "the node exactly as shipped"),
        ("pace=1", {"pace": 1}, "loop() sleeps 1 ms per pass (the bench test does; the app does not)"),
        ("dsp=2", {"dsp": 2}, "audio chain off (silence): is it the DSP?"),
        ("send=1", {"send": 1}, "audio drained, nothing sent: is it the WebSocket send?"),
        ("src=1", {"src": 1}, "synthetic samples, ADC driver never opened: is it the ADC?"),
        ("text=3", {"text": 3}, "no target/status pushes: is it the text traffic?"),
        ("quiet=1", {"quiet": 1}, "no Serial output: is it the USB log?"),
        ("skip=7", {"skip": 7}, "radar UART, OLED and DNS skipped: is it another part of loop()?"),
    ],
    "full": [
        ("baseline", {}, "the node exactly as shipped"),
        ("pace=1", {"pace": 1}, "loop() sleeps 1 ms per pass"),
        ("pace=2", {"pace": 2}, "loop() sleeps 10 ms per pass"),
        ("dsp=1", {"dsp": 1}, "audio chain bypassed"),
        ("dsp=2", {"dsp": 2}, "audio chain off (silence)"),
        ("send=1", {"send": 1}, "audio drained, nothing sent"),
        ("send=2", {"send": 2}, "unguarded binaryAll() on every packet"),
        ("src=1", {"src": 1}, "synthetic samples, no ADC driver"),
        ("text=3", {"text": 3}, "no text pushes"),
        ("quiet=1", {"quiet": 1}, "no Serial output"),
        ("skip=1", {"skip": 1}, "radar UART skipped"),
        ("skip=2", {"skip": 2}, "OLED skipped"),
        ("skip=4", {"skip": 4}, "DNS server skipped"),
        ("prio=2", {"prio": 2}, "audio task priority 2"),
        ("prio=8", {"prio": 8}, "audio task priority 8"),
        ("prio=12", {"prio": 12}, "audio task priority 12 (above async_tcp)"),
        ("pace=1+src=1", {"pace": 1, "src": 1}, "combination"),
        ("pace=1+send=1", {"pace": 1, "send": 1}, "combination"),
        ("everything off", {"pace": 1, "dsp": 2, "send": 1, "src": 1, "text": 3, "quiet": 1, "skip": 7}, "all switches at once: should be the quietest node there is"),
    ],
    "baseline": [("baseline", {}, "the node exactly as shipped")],
    # used by tests/test_soak.py against the simulator
    "selftest": [
        ("baseline", {}, "selftest"),
        ("send=1", {"send": 1}, "selftest: no audio expected"),
    ],
}


# ---------------------------------------------------------------------------
# Minimal WebSocket client (RFC 6455), enough for the node's /ws
# ---------------------------------------------------------------------------
class WSClosed(Exception):
    pass


class WS:
    def __init__(self, host, port, path="/ws", timeout=5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, host, port, key))
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise WSClosed("closed during handshake")
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n")[0] + b" ":
            raise WSClosed("handshake refused: " + head.split(b"\r\n")[0].decode(errors="replace"))
        self.buf = rest
        self.frag = b""
        self.frag_op = 0

    def _need(self, n, deadline):
        while len(self.buf) < n:
            left = deadline - time.monotonic()
            if left <= 0:
                return False
            r, _, _ = select.select([self.sock], [], [], left)
            if not r:
                return False
            chunk = self.sock.recv(65536)
            if not chunk:
                raise WSClosed("connection closed by the node")
            self.buf += chunk
        return True

    def recv(self, timeout):
        """Next complete message as (opcode, payload), or None if nothing arrived in time."""
        deadline = time.monotonic() + timeout
        while True:
            if not self._need(2, deadline):
                return None
            b0, b1 = self.buf[0], self.buf[1]
            n = b1 & 0x7F
            off = 2
            if n == 126:
                if not self._need(4, deadline):
                    return None
                n = struct.unpack(">H", self.buf[2:4])[0]
                off = 4
            elif n == 127:
                if not self._need(10, deadline):
                    return None
                n = struct.unpack(">Q", self.buf[2:10])[0]
                off = 10
            if not self._need(off + n, deadline):
                return None
            payload = self.buf[off:off + n]
            self.buf = self.buf[off + n:]
            op = b0 & 0x0F
            fin = b0 & 0x80
            if op == 8:
                raise WSClosed("node closed the WebSocket")
            if op == 9:                       # ping: answer with a masked pong
                mask = os.urandom(4)
                masked = bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
                try:
                    self.sock.sendall(bytes([0x8A, 0x80 | len(payload)]) + mask + masked)
                except OSError:
                    pass
                continue
            if op == 10:
                continue
            if op in (1, 2):
                self.frag, self.frag_op = payload, op
            elif op == 0:
                self.frag += payload
            if fin:
                msg, self.frag = self.frag, b""
                return self.frag_op, msg

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
class Node:
    def __init__(self, host, port):
        self.host, self.port = host, port
        self.base = "http://%s:%d" % (host, port)

    def get(self, path, timeout=4.0):
        with urllib.request.urlopen(self.base + path, timeout=timeout) as r:
            return r.read()

    def json(self, path, timeout=4.0):
        return json.loads(self.get(path, timeout).decode())

    def try_json(self, path, timeout=3.0):
        try:
            return self.json(path, timeout)
        except (OSError, ValueError, urllib.error.URLError):
            return None

    def wait_up(self, secs):
        """Poll /api/status until the node answers (a crashed node takes ~5-15 s)."""
        end = time.monotonic() + secs
        while time.monotonic() < end:
            st = self.try_json("/api/status", 2.0)
            if st and "node" in st:
                return st
            time.sleep(1.0)
        return None

    def log_tail(self, lines=10):
        try:
            txt = self.get("/api/log", 4.0).decode(errors="replace")
        except (OSError, urllib.error.URLError):
            return []
        return [l for l in txt.splitlines() if l.strip()][-lines:]


def lab_query(sw, extra=""):
    q = "reset=1&clear=1" + extra
    for k, v in sw.items():
        q += "&%s=%d" % (k, v)
    return "/api/lab?" + q


# ---------------------------------------------------------------------------
# One trial
# ---------------------------------------------------------------------------
def percentile(vals, p):
    if not vals:
        return 0.0
    v = sorted(vals)
    return v[min(len(v) - 1, int(len(v) * p))]


def run_trial(node, name, sw, secs, a, log):
    res = {"name": name, "sw": sw, "result": "?", "t": 0.0, "u": 0, "ups": 0.0, "lost": 0, "gap_max": 0.0, "gap_p99": 0.0,
           "big_gaps": 0, "heap_min": None, "loop_ms": None, "blk_avg": None, "blk_max": None, "node_gap": None,
           "rd_to": None, "boots": None, "reset": "", "note": "", "log": [], "bad_json": 0}
    # 1. Stetho off, switches set, Stetho on: a fresh start with a client about to join, like the phone page
    st0 = node.wait_up(30)
    if not st0:
        res["result"] = "NO NODE"
        res["note"] = "the node did not answer before the trial"
        return res
    boots0 = st0["node"]["boots"]
    try:
        node.json("/api/config?stetho=0")
        time.sleep(0.6)
        extra = "&simcrash=%s" % a.sim_crash_in if a.sim_crash_in else ""
        lab = node.try_json(lab_query(sw, extra))
        if lab is None or "lab" not in lab:
            res["result"] = "NO LAB"
            res["note"] = "this firmware has no /api/lab (flash the Lab build first)"
            return res
        time.sleep(0.4)
        node.json("/api/config?stetho=1")
    except (OSError, ValueError, urllib.error.URLError) as e:
        res["result"] = "NO NODE"
        res["note"] = "lost the node while setting up: %s" % e
        return res
    t_start = time.monotonic()               # "held" counts from the moment Stetho was switched on, like the node log's clock
    time.sleep(1.2)                          # let the audio task come up

    # 2. listen
    last_u = None
    last_seq = None
    gaps = []
    lastmsg = t_start
    failure = None
    try:
        ws = WS(node.host, node.port)
    except (OSError, WSClosed) as e:
        res["result"] = "NO WS"
        res["note"] = str(e)
        return res
    t_ws = time.monotonic()                  # audio rates are counted from here, "held" from t_start
    try:
        while True:
            now = time.monotonic()
            if now - t_start >= secs:
                break
            m = ws.recv(0.5)
            now = time.monotonic()
            if m is None:
                if now - lastmsg > a.stall:
                    failure = ("STALL", now - t_start, "no data for %.0f s while the connection stayed open" % (now - lastmsg))
                    break
                continue
            lastmsg = now
            op, payload = m
            if op == 2 and payload[:1] == b"U" and len(payload) >= 6:
                seq = payload[2] | (payload[3] << 8)
                if last_seq is not None:
                    d = (seq - last_seq) & 0xFFFF
                    if d > 1:
                        res["lost"] += d - 1
                last_seq = seq
                if last_u is not None:
                    gaps.append((now - last_u) * 1000.0)
                last_u = now
                res["u"] += 1
            elif op == 1:
                try:
                    j = json.loads(payload.decode())
                except ValueError:
                    res["bad_json"] += 1       # a truncated status line would land here
                    continue
                if "node" in j:
                    nd = j["node"]
                    res["heap_min"] = min(nd["heapMin"], res["heap_min"]) if res["heap_min"] is not None else nd["heapMin"]
                    res["loop_ms"] = max(nd["loopMs"], res["loop_ms"] or 0)
                    res["boots"] = nd["boots"]
                    res["reset"] = nd["reset"]
                    s2 = j.get("stetho2")
                    if s2:
                        res["blk_avg"] = s2["dspUs"]
                        res["blk_max"] = max(s2["dspUsMax"], res["blk_max"] or 0)
                        res["node_gap"] = max(s2["gapMaxMs"], res["node_gap"] or 0)
                        res["rd_to"] = s2["rdTimeouts"]
    except WSClosed as e:
        failure = ("DROPPED", time.monotonic() - t_start, str(e))
    except OSError as e:
        failure = ("DROPPED", time.monotonic() - t_start, "socket error: %s" % e)
    finally:
        ws.close()

    t_end = time.monotonic()
    res["t"] = t_end - t_start
    if gaps:
        res["gap_max"] = max(gaps)
        res["gap_p99"] = percentile(gaps, 0.99)
        res["big_gaps"] = sum(1 for g in gaps if g > 100.0)
    res["ups"] = res["u"] / (t_end - t_ws) if t_end - t_ws > 0.5 else 0.0

    # 3. verdict
    if failure:
        kind, at, why = failure
        st = node.wait_up(a.wait_back)
        if st:
            res["boots"] = st["node"]["boots"]
            res["reset"] = st["node"]["reset"]
            res["log"] = node.log_tail(14)
            if st["node"]["boots"] != boots0:
                res["result"] = "CRASH"
                res["note"] = "reset at ~%.1f s: %s (boot #%d); %s" % (at, st["node"]["reset"], st["node"]["boots"], why)
            else:
                res["result"] = kind
                res["note"] = "at ~%.1f s: %s (the node answered again without rebooting)" % (at, why)
        else:
            res["result"] = kind
            res["note"] = "at ~%.1f s: %s; the node did not come back within %d s" % (at, why, a.wait_back)
        res["t"] = at
    else:
        expect_audio = sw.get("send", 0) != 1
        if expect_audio and res["u"] == 0:
            res["result"] = "NO AUDIO"
            res["note"] = "the node stayed up but sent no audio packets (is Stetho enabled and the ADC pin wired?)"
        else:
            res["result"] = "OK"
            res["log"] = node.log_tail(6) if a.verbose else []
        st = node.try_json("/api/status")
        if st and st["node"]["boots"] != boots0 and res["result"] == "OK":
            res["result"] = "CRASH"
            res["note"] = "rebooted after the data stopped being collected"
    return res


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def fmt(v, spec="%s", dash="-"):
    return dash if v is None else spec % v


def report(results, plan_name, secs, host):
    L = []
    L.append("# Blip soak test")
    L.append("")
    L.append("Node `%s`, plan `%s`, %d s per trial, soak_test.py %s, %s." % (host, plan_name, secs, __version__, time.strftime("%Y-%m-%d %H:%M")))
    L.append("")
    L.append("| Trial | Result | Held | Audio pkt/s | Lost | Gaps >100 ms | Max gap ms | Block avg/max us | Node gap max ms | Heap min KB | Notes |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        blk = "-" if r["blk_avg"] is None else "%d/%d" % (r["blk_avg"], r["blk_max"] or 0)
        heap = "-" if r["heap_min"] is None else "%d" % (r["heap_min"] // 1024)
        L.append("| %s | **%s** | %.0f s | %.1f | %d | %d | %.0f | %s | %s | %s | %s |" % (
            r["name"], r["result"], r["t"], r["ups"], r["lost"], r["big_gaps"], r["gap_max"], blk, fmt(r["node_gap"]), heap, r["note"].replace("|", "/")))
    L.append("")
    base = next((r for r in results if r["name"].startswith("baseline")), None)
    L.append("## Reading it")
    L.append("")
    bad = lambda r: r["result"] in ("CRASH", "STALL", "DROPPED")
    if base is None:
        L.append("No baseline trial in this plan, so there is nothing to compare against.")
    elif not bad(base):
        L.append("The baseline did **not** fail in %d s. Either the freeze needs longer (run again with `--secs 180`), or it needs something this "
                 "setup lacks (a phone instead of this computer, the real radar and OLED attached). Expected audio is 31.25 packets/s." % secs)
    else:
        good = [r for r in results if r is not base and r["result"] == "OK" and r["sw"]]
        badr = [r for r in results if r is not base and bad(r)]
        L.append("The baseline **%s** after about %.0f s." % (base["result"], base["t"]))
        if good:
            L.append("")
            L.append("These variants held for the full time while the baseline failed, which points at the part each one switches off:")
            for r in good:
                L.append("- `%s`: %s" % (r["name"], next((n for (nm, _, n) in PLANS.get("full", []) if nm == r["name"]), "")))
        if badr:
            L.append("")
            L.append("Still failing: " + ", ".join("`%s`" % r["name"] for r in badr) + ".")
        if not good:
            L.append("Nothing that was switched off made the difference on its own. Try `--plan full` (combinations, task priorities), and also run the same "
                     "firmware on a second board: if a different C3 or the S3-Pico survives, it is the board or the radio environment, not the code.")
    L.append("")
    crashes = [r for r in results if r["log"] and bad(r)]
    for r in crashes:
        L.append("### Node log after `%s`" % r["name"])
        L.append("")
        L.append("```")
        L.extend(r["log"])
        L.append("```")
        L.append("")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Blip soak test: which part of the node makes Stetho freeze? (one flash, many trials)")
    ap.add_argument("--host", default="192.168.4.1", help="the node's address (default: its hotspot address)")
    ap.add_argument("--port", type=int, default=80)
    ap.add_argument("--secs", type=int, default=60, help="seconds to listen per trial (default 60; the freeze has shown up within 4-9 s)")
    ap.add_argument("--plan", default="quick", help="quick | full | baseline | a custom list like 'pace=1,dsp=2;send=1'")
    ap.add_argument("--repeat", type=int, default=1, help="run the whole plan this many times")
    ap.add_argument("--stall", type=float, default=4.0, help="seconds without data that count as a stall")
    ap.add_argument("--wait-back", type=int, default=60, help="seconds to wait for a crashed node to answer again")
    ap.add_argument("--out", default=None, help="report file (default soak_report_<time>.md)")
    ap.add_argument("--sim-crash-in", type=float, default=0, help="(simulator only) pretend to crash this many seconds into each trial")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--version", action="version", version="soak_test " + __version__)
    a = ap.parse_args(argv)

    if a.plan in PLANS:
        plan, plan_name = PLANS[a.plan], a.plan
    else:
        plan, plan_name = [], "custom"
        for i, part in enumerate(a.plan.split(";")):
            sw = {}
            for kv in part.split(","):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    sw[k.strip()] = int(v)
            plan.append((part.replace(",", "+") or "baseline", sw, "custom"))
    node = Node(a.host, a.port)
    print("Blip soak test %s: node %s:%d, plan %s (%d trials x %d s%s)" % (__version__, a.host, a.port, plan_name, len(plan), a.secs,
                                                                          ", x%d" % a.repeat if a.repeat > 1 else ""))
    st = node.wait_up(15)
    if not st:
        print("The node does not answer. Join its Wi-Fi hotspot (Blip-Radar) first, or pass --host.")
        return 2
    print("Node: %s %s on %s, boot #%d, last reset: %s" % (st.get("app", "?"), st.get("version", "?"), st.get("board", "?"), st["node"]["boots"], st["node"]["reset"]))
    results = []
    try:
        for rep in range(a.repeat):
            for (name, sw, why) in plan:
                label = name if a.repeat == 1 else "%s #%d" % (name, rep + 1)
                print("  %-22s ..." % label, end="", flush=True)
                r = run_trial(node, label, sw, a.secs, a, None)
                results.append(r)
                print(" %-8s %5.1f pkt/s, %d lost, %d gaps>100ms%s" % (r["result"], r["ups"], r["lost"], r["big_gaps"], ("  " + r["note"]) if r["note"] else ""))
                if r["result"] in ("NO LAB", "NO NODE"):
                    raise KeyboardInterrupt
    except KeyboardInterrupt:
        print("stopped early")
    finally:
        node.try_json("/api/lab?reset=1")          # always leave the node as shipped
    out = a.out or time.strftime("soak_report_%Y%m%d_%H%M%S.md")
    text = report(results, plan_name, a.secs, a.host)
    with open(out, "w") as f:
        f.write(text)
    print("\nReport written to %s\n" % out)
    print(text)
    return 0 if all(r["result"] == "OK" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
