"""Demo investigation scenarios created by seed_data.py (ids can never collide with mainnet)."""

SCENARIOS = [
    {"address": "bc1_sus_peel_root", "label": "PEEL_CHAIN", "icon": "🧅",
     "title": "Peel chain into darknet market",
     "story": "50 BTC from an exchange is peeled through 10 fresh addresses, each hop paying a darknet market."},
    {"address": "bc1_sus_burst", "label": "SMURFING", "icon": "💥",
     "title": "Rapid pass-through + fan-out",
     "story": "100 BTC arrives and is split to 25 wallets within minutes."},
    {"address": "bc1_sus_mixer", "label": "COLLECTOR", "icon": "🌀",
     "title": "Fan-in / fan-out hub with CoinJoin",
     "story": "30 senders aggregate funds, which are mixed in a CoinJoin and dispersed."},
    {"address": "bc1_sus_geohop", "label": "GEO_HOP", "icon": "✈️",
     "title": "Impossible travel via Tor/VPN relays",
     "story": "Spends broadcast from Frankfurt (Tor), New York and Reykjavik (VPN) within an hour."},
    {"address": "bc1_sus_ransom_cashout", "label": "RANSOM_CASHOUT", "icon": "🦠",
     "title": "Ransomware proceeds cashed out",
     "story": "Victim payments consolidate, go dormant for 14 months, then reach an exchange."},
    {"address": "bc1_normal_0", "label": "NORMAL", "icon": "✅",
     "title": "Ordinary retail wallet",
     "story": "Occasional exchange withdrawals and small payments - should score LOW."},
]
