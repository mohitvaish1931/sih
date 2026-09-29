"""
Seed SIFRA with deterministic demo investigation scenarios.

Only demo rows are replaced (txids starting with "demo", demo addresses), so it
is safe to re-run. Seeding a non-SQLite database requires --force.

    python seed_data.py            # local SQLite
    python seed_data.py --force    # also allowed against Postgres/Supabase
"""

import hashlib
import random
import sys
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal, IS_SQLITE, init_db_schema
from app.demo_scenarios import SCENARIOS
from app.models import (AddressTx, Alert, AnalysisResult, ChainTx, RelayObservation, Transaction, Wallet,
                        AddressSync)
from app.services.blockchain_sync import store_transactions

random.seed(1907)
NOW = datetime.now(timezone.utc).replace(microsecond=0)
_counter = [0]

EXCHANGES = ["Exchange_Binance_0", "Exchange_Binance_1", "Exchange_Binance_2"]
DARKNET = ["Darknet_Market_Alpha", "Darknet_Market_Hydra"]

RELAYS = {
    "tokyo": {"ip": "139.162.112.41", "city": "Tokyo", "country": "Japan", "lat": 35.6762, "lon": 139.6503,
              "isp": "Linode JP", "vpn": False},
    "frankfurt_tor": {"ip": "185.220.101.5", "city": "Frankfurt", "country": "Germany", "lat": 50.1109,
                      "lon": 8.6821, "isp": "Tor Exit Node DE", "vpn": True},
    "new_york": {"ip": "104.244.76.13", "city": "New York", "country": "United States", "lat": 40.7128,
                 "lon": -74.0060, "isp": "DigitalOcean US", "vpn": False},
    "reykjavik_vpn": {"ip": "185.195.233.72", "city": "Reykjavik", "country": "Iceland", "lat": 64.1466,
                      "lon": -21.9426, "isp": "Flokinet Offshore", "vpn": True},
    "mumbai": {"ip": "103.21.58.11", "city": "Mumbai", "country": "India", "lat": 19.0760, "lon": 72.8777,
               "isp": "Tata Communications", "vpn": False},
}


def txid() -> str:
    _counter[0] += 1
    return "demo" + hashlib.sha256(f"sifra-demo-{_counter[0]}".encode()).hexdigest()[:60]


def tx(when: datetime, inputs, outputs, fee: float = 0.0001) -> dict:
    """Build a normalized tx (same shape bitcoin_api produces)."""
    return {
        "txid": txid(),
        "timestamp": int(when.timestamp()),
        "block_height": 850_000 + int((when - (NOW - timedelta(days=500))).total_seconds() // 600),
        "confirmed": True,
        "fee_btc": fee,
        "inputs": [{"address": a, "value": round(v, 8)} for a, v in inputs],
        "outputs": [{"address": a, "value": round(v, 8), "n": n} for n, (a, v) in enumerate(outputs)],
    }


class Seeder:
    def __init__(self, db):
        self.db = db
        self.txs = []          # (focus, tx)
        self.relay = []        # (txid, relay key, when)

    def add(self, focus: str, t: dict, relay: str = None):
        self.txs.append((focus, t))
        if relay:
            self.relay.append((t["txid"], relay, datetime.fromtimestamp(t["timestamp"], timezone.utc)))
        return t

    def flush(self):
        for focus, t in self.txs:
            store_transactions(self.db, focus, [t], source="demo")
        for tid, key, when in self.relay:
            r = RELAYS[key]
            self.db.add(RelayObservation(
                txid=tid, peer_ip=r["ip"], first_seen=when + timedelta(seconds=random.randint(1, 9)),
                peers_announcing=random.randint(3, 9), country=r["country"], city=r["city"], latitude=r["lat"],
                longitude=r["lon"], isp=r["isp"], is_vpn_tor=r["vpn"], confidence=0.9, sensor_id="demo-sensor"))
        self.db.query(ChainTx).filter(ChainTx.txid.like("demo%")).update({ChainTx.source: "demo"},
                                                                         synchronize_session=False)
        self.db.commit()


def clear_demo(db):
    demo_addrs = [s["address"] for s in SCENARIOS]
    db.query(RelayObservation).filter(RelayObservation.txid.like("demo%")).delete(synchronize_session=False)
    db.query(AddressTx).filter(AddressTx.txid.like("demo%")).delete(synchronize_session=False)
    db.query(ChainTx).filter(ChainTx.txid.like("demo%")).delete(synchronize_session=False)
    db.query(Transaction).filter(
        Transaction.txid.like("demo%")
        | Transaction.from_address.like("bc1\\_%", escape="\\")
        | Transaction.to_address.like("bc1\\_%", escape="\\")
        | Transaction.from_address.like("Exchange\\_%", escape="\\")
        | Transaction.from_address.like("Darknet\\_%", escape="\\")
    ).delete(synchronize_session=False)
    for model, col in ((AnalysisResult, AnalysisResult.wallet_address), (Alert, Alert.wallet_address),
                       (Wallet, Wallet.address), (AddressSync, AddressSync.address)):
        db.query(model).filter(col.like("bc1\\_%", escape="\\") | col.in_(demo_addrs)).delete(synchronize_session=False)
    db.commit()


def seed_database():
    init_db_schema()
    db = SessionLocal()
    print("Clearing previous demo data (real chain data is untouched)...")
    clear_demo(db)
    s = Seeder(db)

    # 1. Ordinary retail wallets ------------------------------------------------
    normal = [f"bc1_normal_{i}" for i in range(40)]
    t0 = NOW - timedelta(days=60)
    for i, w in enumerate(normal):
        start = t0 + timedelta(hours=random.randint(0, 900))
        amt = round(random.uniform(0.05, 1.5), 4)
        ex = random.choice(EXCHANGES)
        s.add(w, tx(start, [(ex, amt + 3)], [(w, amt), (ex, 3 - 0.0002)]))
        pay = round(amt * random.uniform(0.1, 0.4), 4)
        s.add(w, tx(start + timedelta(days=random.randint(3, 20)), [(w, amt)],
                    [(random.choice(normal), pay), (w, amt - pay - 0.0001)]))
        if i % 3 == 0:
            s.add(w, tx(start + timedelta(days=random.randint(25, 40)), [(w, amt - pay - 0.0001)],
                        [(random.choice(EXCHANGES), round(amt * 0.3, 4)), (w, amt - pay - round(amt * 0.3, 4) - 0.0002)]))

    # 2. Peel chain -----------------------------------------------------------
    t = NOW - timedelta(days=9)
    root = "bc1_sus_peel_root"
    nodes = [f"bc1_peel_node_{i}" for i in range(10)]
    s.add(root, tx(t, [("Exchange_Binance_0", 60)], [(root, 50.0), ("Exchange_Binance_0", 9.9998)]))
    t += timedelta(minutes=45)
    balance, current = 50.0, root
    for nxt in nodes:
        peel = round(random.uniform(0.2, 1.2), 4)
        remainder = round(balance - peel - 0.0001, 6)
        s.add(current, tx(t, [(current, balance)], [(random.choice(DARKNET), peel), (nxt, remainder)]))
        balance, current = remainder, nxt
        t += timedelta(minutes=random.randint(8, 35))
    s.add(current, tx(t, [(current, balance)], [("Exchange_Binance_2", round(balance - 0.0001, 6))]))

    # 3. Burst / smurfing ------------------------------------------------------
    burst = "bc1_sus_burst"
    t = NOW - timedelta(days=6, hours=3)
    s.add(burst, tx(t, [("Exchange_Binance_1", 101)], [(burst, 100.0), ("Exchange_Binance_1", 0.9998)]))
    t += timedelta(minutes=4)
    remaining = 100.0
    for i in range(25):
        amt = round(3.96 + random.uniform(-0.02, 0.02), 4)
        s.add(burst, tx(t, [(burst, remaining)], [(f"bc1_burst_target_{i}", amt), (burst, round(remaining - amt - 0.0001, 6))]))
        remaining = round(remaining - amt - 0.0001, 6)
        t += timedelta(seconds=random.randint(40, 150))

    # 4. Collector hub with CoinJoin -------------------------------------------
    mixer = "bc1_sus_mixer"
    t = NOW - timedelta(days=4)
    collected = 0.0
    for i in range(30):
        amt = round(random.uniform(0.5, 2.0), 4)
        collected += amt
        sender = f"bc1_random_sender_{i}"
        s.add(sender, tx(t, [(sender, amt + 0.001)], [(mixer, amt)]))
        t += timedelta(minutes=random.randint(3, 25))
    peers = [f"bc1_cj_peer_{i}" for i in range(6)]
    cj_inputs = [(mixer, 3.6)] + [(p, round(random.uniform(0.55, 0.9), 4)) for p in peers]
    cj_outputs = [(f"bc1_cj_out_{i}", 0.5) for i in range(7)] + [(mixer, 0.1)] + \
                 [(p, round(v - 0.5 - 0.0002, 6)) for p, v in cj_inputs[1:]]
    s.add(mixer, tx(t, cj_inputs, cj_outputs, fee=0.0014))
    t += timedelta(minutes=30)
    left = collected - 3.6
    for i in range(30):
        amt = round(min(left / (30 - i), random.uniform(0.4, 1.9)), 4)
        s.add(mixer, tx(t, [(mixer, left + 0.1)], [(f"bc1_random_receiver_{i}", amt), (mixer, round(left + 0.1 - amt - 0.0001, 6))]))
        left -= amt
        t += timedelta(minutes=random.randint(1, 6))

    # 5. Impossible travel via Tor / VPN ---------------------------------------
    geo = "bc1_sus_geohop"
    t = NOW - timedelta(days=2, hours=5)
    s.add(geo, tx(t, [("Exchange_Binance_0", 46)], [(geo, 45.0), ("Exchange_Binance_0", 0.9998)]), relay="tokyo")
    t += timedelta(minutes=18)
    s.add(geo, tx(t, [(geo, 45.0)], [("bc1_geo_target_de", 12.5), (geo, 32.4998)]), relay="frankfurt_tor")
    t += timedelta(minutes=19)
    s.add(geo, tx(t, [(geo, 32.4998)], [("bc1_geo_target_us", 18.0), (geo, 14.4997)]), relay="new_york")
    t += timedelta(minutes=22)
    s.add(geo, tx(t, [(geo, 14.4997)], [("Darknet_Market_Hydra", 14.4996)]), relay="reykjavik_vpn")

    # 6. Ransomware cash-out after dormancy -------------------------------------
    ops = "bc1_demo_ransom_ops"
    cash = "bc1_sus_ransom_cashout"
    t = NOW - timedelta(days=470)
    victims_total = 0.0
    for i in range(12):
        amt = round(random.uniform(0.4, 2.2), 4)
        victims_total += amt
        victim = f"bc1_victim_{i}"
        s.add(victim, tx(t, [(victim, amt + 0.002)], [(ops, amt), (victim, 0.0019)]), relay="mumbai" if i == 0 else None)
        t += timedelta(hours=random.randint(3, 11))
    s.add(ops, tx(t, [(ops, round(victims_total, 6))], [(cash, round(victims_total - 0.0005, 6))]))
    t += timedelta(days=425)
    held = round(victims_total - 0.0005, 6)
    to_ex = round(held * 0.72, 4)
    s.add(cash, tx(t, [(cash, held)], [("Exchange_Binance_1", to_ex), ("bc1_cashout_hop_1", round(held - to_ex - 0.0002, 6))]))

    print(f"Writing {len(s.txs)} demo transactions ...")
    s.flush()
    db.close()

    print("\nDemo scenarios ready - search these ids in the dashboard:")
    for sc in SCENARIOS:
        print(f"  - {sc['address']:<24} {sc['title']}")


if __name__ == "__main__":
    if not IS_SQLITE and "--force" not in sys.argv:
        sys.exit("Refusing to seed a non-SQLite database without --force (only demo rows are touched).")
    seed_database()
