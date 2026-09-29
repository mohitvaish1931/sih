"""
SIFRA relay sensor - passive Bitcoin P2P listener.

Connects to public Bitcoin nodes over the native P2P protocol, listens for
transaction announcements (inv messages) and records, for every txid, the
first peer that announced it plus how many peers announced it. That is the
"first-spy" estimator used in blockchain-network forensics research: the
first announcer is the best available guess of where a transaction entered
the network. Observations are posted to the SIFRA API, which geolocates the
peer IP and uses it for geo-velocity / impossible-travel analysis.

Each observation carries a confidence (0..1). First-spy is weak when the
first announcer is a "supernode" that is first for a large share of all
traffic, or when few peers announced the tx; both lower the confidence and
SIFRA ignores observations below 0.35 for scoring.

The sensor only listens; it never relays or creates transactions.

Usage:
    python sensor/relay_sensor.py --api http://127.0.0.1:8000 --peers 16
    python sensor/relay_sensor.py --duration 120          # run for two minutes
"""

import argparse
import asyncio
import hashlib
import json
import os
import random
import socket
import struct
import sys
import time
import urllib.request

MAGIC = bytes.fromhex("f9beb4d9")
PROTOCOL_VERSION = 70016
USER_AGENT = b"/SIFRA-sensor:1.0/"
MSG_TX = 1
MSG_WITNESS_TX = 0x40000001
DNS_SEEDS = [
    "seed.bitcoin.sipa.be", "dnsseed.bluematt.me", "seed.bitcoinstats.com",
    "seed.bitcoin.jonasschnelli.ch", "seed.btc.petertodd.net", "seed.bitcoin.sprovoost.nl",
    "dnsseed.emzy.de", "seed.bitcoin.wiz.biz",
]


# ---------------------------------------------------------------------------
# Wire format helpers
# ---------------------------------------------------------------------------
def sha256d(b: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


def message(command: str, payload: bytes = b"") -> bytes:
    cmd = command.encode().ljust(12, b"\x00")
    return MAGIC + cmd + struct.pack("<I", len(payload)) + sha256d(payload)[:4] + payload


def var_int(n: int) -> bytes:
    if n < 0xFD:
        return struct.pack("<B", n)
    if n <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", n)
    if n <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", n)
    return b"\xff" + struct.pack("<Q", n)


def read_var_int(b: bytes, off: int):
    first = b[off]
    if first < 0xFD:
        return first, off + 1
    if first == 0xFD:
        return struct.unpack_from("<H", b, off + 1)[0], off + 3
    if first == 0xFE:
        return struct.unpack_from("<I", b, off + 1)[0], off + 5
    return struct.unpack_from("<Q", b, off + 1)[0], off + 9


def net_addr(ip: str, port: int) -> bytes:
    try:
        packed = b"\x00" * 10 + b"\xff\xff" + socket.inet_aton(ip)
    except OSError:
        packed = socket.inet_pton(socket.AF_INET6, ip)
    return struct.pack("<Q", 0) + packed + struct.pack(">H", port)


def version_payload(ip: str, port: int) -> bytes:
    return (struct.pack("<iQq", PROTOCOL_VERSION, 0, int(time.time()))
            + net_addr(ip, port) + net_addr("0.0.0.0", 0)
            + struct.pack("<Q", random.getrandbits(64))
            + var_int(len(USER_AGENT)) + USER_AGENT
            + struct.pack("<i", 0) + b"\x01")          # start_height=0, relay=true


def parse_addr(payload: bytes):
    count, off = read_var_int(payload, 0)
    out = []
    for _ in range(min(count, 1000)):
        if off + 30 > len(payload):
            break
        raw_ip = payload[off + 12:off + 28]
        port = struct.unpack_from(">H", payload, off + 28)[0]
        off += 30
        if raw_ip[:12] == b"\x00" * 10 + b"\xff\xff":
            out.append((socket.inet_ntoa(raw_ip[12:]), port))
    return out


# ---------------------------------------------------------------------------
# Sensor
# ---------------------------------------------------------------------------
class RelaySensor:
    def __init__(self, api: str, max_peers: int, token: str, sensor_id: str, settle: float):
        self.api = api.rstrip("/")
        self.max_peers = max_peers
        self.token = token
        self.sensor_id = sensor_id
        self.settle = settle                  # seconds to count announcers before posting
        self.first_seen = {}                  # txid -> [ts, peer_ip, announcers]
        self.posted = set()
        self.candidates = []
        self.connected = {}
        self.failed = set()
        self.stats = {"inv_tx": 0, "unique_tx": 0, "posted": 0, "handshakes": 0}
        self.first_counts = {}                # peer ip -> txs it announced first

    # ----- discovery -----
    def discover(self):
        found = set()
        for seed in DNS_SEEDS:
            try:
                for info in socket.getaddrinfo(seed, 8333, socket.AF_INET, socket.SOCK_STREAM):
                    found.add((info[4][0], 8333))
            except OSError:
                continue
        self.candidates = list(found)
        random.shuffle(self.candidates)
        print(f"[sensor] discovered {len(self.candidates)} candidate peers from DNS seeds", flush=True)

    # ----- peer session -----
    async def peer(self, ip: str, port: int):
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=6)
        except (OSError, asyncio.TimeoutError):
            self.failed.add(ip)
            return
        self.connected[ip] = time.time()
        try:
            writer.write(message("version", version_payload(ip, port)))
            await writer.drain()
            while True:
                header = await asyncio.wait_for(reader.readexactly(24), timeout=180)
                if header[:4] != MAGIC:
                    break
                command = header[4:16].rstrip(b"\x00").decode(errors="ignore")
                length = struct.unpack_from("<I", header, 16)[0]
                if length > 4_000_000:
                    break
                payload = await asyncio.wait_for(reader.readexactly(length), timeout=60)
                try:
                    await self.handle(ip, command, payload, writer)
                except (IndexError, struct.error):
                    continue   # malformed / empty message from peer - ignore it
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, OSError, ConnectionError):
            pass
        finally:
            self.connected.pop(ip, None)
            try:
                writer.close()
            except Exception:
                pass

    async def handle(self, ip, command, payload, writer):
        if command == "version":
            writer.write(message("verack"))
            await writer.drain()
        elif command == "verack":
            self.stats["handshakes"] += 1
            writer.write(message("getaddr"))
            await writer.drain()
        elif command == "ping":
            writer.write(message("pong", payload[:8]))
            await writer.drain()
        elif command == "addr":
            for cand in parse_addr(payload):
                if cand[0] not in self.failed and cand not in self.candidates:
                    self.candidates.append(cand)
        elif command == "inv":
            now = time.time()
            count, off = read_var_int(payload, 0)
            for _ in range(min(count, 50_000)):
                if off + 36 > len(payload):
                    break
                inv_type = struct.unpack_from("<I", payload, off)[0]
                h = payload[off + 4:off + 36]
                off += 36
                if inv_type not in (MSG_TX, MSG_WITNESS_TX):
                    continue
                self.stats["inv_tx"] += 1
                txid = h[::-1].hex()
                rec = self.first_seen.get(txid)
                if rec is None:
                    self.first_seen[txid] = [now, ip, 1]
                    self.first_counts[ip] = self.first_counts.get(ip, 0) + 1
                    self.stats["unique_tx"] += 1
                else:
                    rec[2] += 1

    # ----- reporting -----
    def confidence(self, rec) -> float:
        """Down-weight supernodes (first for a large share of txs) and thinly-announced txs."""
        total = sum(self.first_counts.values()) or 1
        share = self.first_counts.get(rec[1], 0) / total
        dominance = max(0.0, 1.0 - max(0.0, share - 0.1) * 2.5)     # 10% share -> 1.0, 50% -> 0.0
        corroboration = min(1.0, 0.4 + 0.2 * (rec[2] - 1))           # announced by >=4 peers -> 1.0
        return round(max(0.0, min(1.0, dominance * corroboration)), 3)

    def batch(self, items):
        return [{"txid": t, "peer_ip": rec[1], "first_seen": rec[0], "peers_announcing": rec[2],
                 "confidence": self.confidence(rec)} for t, rec in items]

    def post(self, batch):
        body = json.dumps({"sensor_id": self.sensor_id, "observations": batch}).encode()
        req = urllib.request.Request(f"{self.api}/api/telemetry/observations", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-Sifra-Token": self.token})
        with urllib.request.urlopen(req, timeout=20) as res:
            return json.loads(res.read())

    async def reporter(self, interval: float):
        while True:
            await asyncio.sleep(interval)
            cutoff = time.time() - self.settle
            ready = [(t, rec) for t, rec in self.first_seen.items() if rec[0] <= cutoff and t not in self.posted]
            if ready:
                batch = self.batch(ready[:2000])
                try:
                    res = await asyncio.to_thread(self.post, batch)
                    self.stats["posted"] += res.get("stored", 0)
                    self.posted.update(o["txid"] for o in batch)
                except Exception as exc:
                    print(f"[sensor] post failed: {exc}", flush=True)
            # forget old entries to bound memory
            old = time.time() - 3600
            for t in [t for t, rec in self.first_seen.items() if rec[0] < old]:
                self.first_seen.pop(t, None)
                self.posted.discard(t)
            print(f"[sensor] peers={len(self.connected)} handshakes={self.stats['handshakes']} "
                  f"tx_invs={self.stats['inv_tx']} unique_txs={self.stats['unique_tx']} "
                  f"posted={self.stats['posted']}", flush=True)

    async def maintain(self):
        tasks = set()
        while True:
            while len(self.connected) + len(tasks) < self.max_peers and self.candidates:
                ip, port = self.candidates.pop(0)
                if ip in self.connected or ip in self.failed:
                    continue
                task = asyncio.create_task(self.peer(ip, port))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
            if not self.candidates and len(self.connected) < self.max_peers // 2:
                await asyncio.to_thread(self.discover)
            await asyncio.sleep(2)

    async def run(self, duration: float, interval: float):
        loop = asyncio.get_running_loop()
        # Remote peers drop connections all the time; don't print tracebacks for that.
        loop.set_exception_handler(lambda l, ctx: None if isinstance(ctx.get("exception"), (ConnectionError, OSError))
                                   else l.default_exception_handler(ctx))
        await asyncio.to_thread(self.discover)
        jobs = [asyncio.create_task(self.maintain()), asyncio.create_task(self.reporter(interval))]
        try:
            if duration > 0:
                await asyncio.sleep(duration)
            else:
                await asyncio.gather(*jobs)
        finally:
            for j in jobs:
                j.cancel()
            # final flush of everything observed so far
            batch = self.batch([(t, rec) for t, rec in self.first_seen.items() if t not in self.posted][:2000])
            if batch:
                try:
                    res = await asyncio.to_thread(self.post, batch)
                    self.stats["posted"] += res.get("stored", 0)
                except Exception as exc:
                    print(f"[sensor] final post failed: {exc}", flush=True)
            print(f"[sensor] done: {self.stats}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="SIFRA passive Bitcoin relay sensor")
    ap.add_argument("--api", default=os.getenv("SIFRA_API", "http://127.0.0.1:8000"))
    ap.add_argument("--peers", type=int, default=16, help="number of simultaneous peer connections")
    ap.add_argument("--duration", type=float, default=0, help="seconds to run (0 = forever)")
    ap.add_argument("--interval", type=float, default=15, help="seconds between API flushes")
    ap.add_argument("--settle", type=float, default=20, help="seconds to count announcers before posting")
    ap.add_argument("--token", default=os.getenv("TELEMETRY_TOKEN", ""))
    ap.add_argument("--sensor-id", default=os.getenv("SENSOR_ID", f"sifra-{socket.gethostname()}"))
    args = ap.parse_args()
    sensor = RelaySensor(args.api, args.peers, args.token, args.sensor_id, args.settle)
    try:
        asyncio.run(sensor.run(args.duration, args.interval))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
