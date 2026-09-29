# SIFRA — Bitcoin Forensics & Threat Intelligence

SIFRA investigates a Bitcoin address the way a blockchain-forensics analyst would. It pulls the live
on-chain history, runs laundering-typology detectors, measures exposure to illicit entities, clusters
co-owned addresses, scores behaviour with an explainable ML model, and fuses all of it into one risk
verdict. The verdict comes with the evidence behind it, recommended next steps (for example, which exchange
to send a KYC request to) and a court-ready case report whose integrity can be checked with SHA-256.

Every number SIFRA shows traces back to on-chain data or an observed measurement. It never makes up a
location, an attribution or a score.

---

## What it does

| Capability | How |
|---|---|
| **Live chain sync** | Blockstream Esplora → mempool.space → blockchain.info failover. It pulls the 150 most recent transactions with every input and output, re-syncs after 10 minutes, and runs balance and history requests in parallel. |
| **Typology detectors** | Peel chain (follows the remainder hop by hop, measures the pace between hops and finds the **terminal exchange**), rapid pass-through (greedy value allocation), fan-out / smurfing, fan-in / collection, CoinJoin *participation*, spend bursts, dormant-funds reactivation, round amounts, dust. Each finding carries evidence txids and the FATF-style typology it matches. |
| **Illicit exposure** | Direct (hop 1) and indirect (hop 2) value exposure to darknet, ransomware, hack, scam, sanctioned and mixer entities. Direction matters: sending to an illicit entity counts for more than receiving from one, and dust is ignored. |
| **KYC leads** | Lists the regulated exchanges that funded or received funds from the wallet, so investigators know where to send legal notices. |
| **Clustering** | Common-input-ownership heuristic with CoinJoins excluded, expanded one level through the local DB. Clusters are attributed from their tagged members. |
| **Explainable ML** | Isolation Forest over 10 scale-free behavioural features. The reference population is ~80 live mainnet addresses sampled from recent blocks, plus 400 simulated ordinary wallets. Scoring is **one-sided** (an unusually *benign* wallet is never flagged), and every score lists the features that drove it. |
| **Risk fusion** | Weighted noisy-OR over behaviour, exposure, ML and geo scores. ML alone can never lift a wallet out of LOW. Known illicit attribution sets a floor. Known exchanges and high-volume services (≥5,000 txs) have their volume-driven signals damped, while exposure evidence keeps its full weight. |
| **Relay telemetry (real geo)** | `sensor/relay_sensor.py` speaks the Bitcoin P2P protocol and records the *first peer* that announces each transaction (the first-spy estimator from network-forensics research). IPs are geolocated (ip-api) and checked against the Tor exit list. Each observation carries a confidence value that down-weights "supernode" relays. |
| **Geo-velocity** | Impossible-travel detection, using only observed, high-confidence relay data. Wallets without telemetry are labelled as having none; no location is ever guessed. |
| **Entity attribution** | A curated list (every address passes a checksum check and is cross-checked against WalletExplorer) plus live WalletExplorer lookups. Lookups run in parallel and stop at a time budget. |
| **Investigation graph** | Aggregated value flows, traced peel hops, cluster links and highlighted illicit nodes. Double-click a node to expand it. Click a node to trace the fund flow along the direction money actually moved. Graphs export to PNG. |
| **Case report** | A printable A4 report with verdict, score composition, findings, exposure, recommendations, a graph snapshot, a transaction evidence table, methodology and limitations. It includes a **SHA-256 evidence fingerprint** that `/api/report/verify` can check. |
| **Live monitoring** | Server-sent events alert you when a watched wallet moves. Alerts are saved to the database. |
| **Live mempool ticker** | The blockchain.info unconfirmed-tx firehose plus mempool.space blocks, with **watchlist hits** whenever a known illicit address shows up in the mempool. Click an item to investigate it. |

## Architecture

```
frontend/  React 19 + Vite 8 + Tailwind 4 + Cytoscape + d3-geo + Recharts
  src/pages/Dashboard.jsx        investigation workspace (deep links: #/wallet/<address>)
  src/components/                RiskCard, FindingsPanel, ExposurePanel, TransactionGraph,
                                 WorldGeoMap, TransactionTable, FundFlow, ReportView, LiveFeed ...
backend/   FastAPI + SQLAlchemy (SQLite or Postgres/Supabase) + scikit-learn
  app/services/
    blockchain_sync.py     chain sync, storage (chain_txs / address_txs / edges), wallet tx view
    rule_engine.py         typology detectors
    exposure_engine.py     illicit exposure + KYC leads
    clustering.py          common-input-ownership clustering
    anomaly_engine.py      Isolation Forest, live reference population, attributions
    geo_velocity_engine.py impossible travel on observed telemetry
    risk_engine.py         noisy-OR fusion, dampening, confidence
    explainability.py      evidence narrative (+ optional local LLM), recommendations
    investigation.py       orchestrator, cache, persistence, evidence fingerprint
  sensor/relay_sensor.py   passive Bitcoin P2P first-spy sensor
  seed_data.py             deterministic demo scenarios
  tests/                   pytest suite (offline, 44 tests)
```

## Run it

**Backend** (Python 3.11+):

```bash
cd backend
python -m venv venv && venv\Scripts\activate        # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                               # optional - works without any database setup
uvicorn main:app --reload
```

**Frontend**:

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173, proxies /api to 127.0.0.1:8000
```

**Relay sensor** (optional; this is what makes the geo-velocity real):

```bash
cd backend
python sensor/relay_sensor.py --peers 16
```

**Tests**:

```bash
cd backend
python -m pytest
```

Optional: install [Ollama](https://ollama.com) and `ollama pull qwen3:14b` to have the local LLM rewrite
the evidence narrative. Without it, SIFRA uses the deterministic evidence template, and the header shows
`LLM: TEMPLATE`.

## Deploy (Vercel + Render, no database needed)

Vercel hosts the static frontend. The API needs a long-running Python server (SSE monitoring, background ML
warm-up, 8-12 s investigations), so it runs on Render. Storage is a built-in SQLite file - there is no
database to create. Demo cases are seeded automatically on startup.

**1. Backend on Render**
- New -> **Blueprint** -> select this repo (uses `render.yaml`), or New -> Web Service with
  root `backend`, build `pip install -r requirements.txt`, start `uvicorn main:app --host 0.0.0.0 --port $PORT`.
- Environment: `CORS_ORIGINS` = your Vercel URL and `LLM_ENABLED=false`. Nothing else is required;
  see `backend/.env.example` for every option.
- Check `https://<service>.onrender.com/api/health`.

**2. Frontend on Vercel**
- Import the repo and keep the **Root Directory empty** (repo root). The root `vercel.json` installs and
  builds `frontend/` and serves `frontend/dist`. (Setting Root Directory to `frontend` also works.)
- Environment variable `VITE_API_BASE` = `https://<service>.onrender.com` (the `/api` suffix is optional), then redeploy.
- `GET /api/diagnostics` on the API shows which blockchain providers are reachable from the host.
- Routing is hash-based (`#/wallet/<address>`), so no rewrites are needed.

**3. Relay sensor (optional)** runs on any always-on machine:
`TELEMETRY_TOKEN=<same as Render> python sensor/relay_sensor.py --api https://<service>.onrender.com`

Render's free tier sleeps after ~15 min idle and its disk is temporary: after a restart the SQLite file starts
fresh (demo cases are re-seeded automatically; past investigations and alerts are gone). Open `/api/health`
once before a demo. For permanent storage later, set `DATABASE_URL` to any Postgres.

## Demo script (5 minutes)

1. **Landing page.** Show the live BTC price, mempool, latest blocks, whale transactions and recent alerts, and the ticker at the bottom (click any item to investigate it).
2. **Demo case → PEEL_CHAIN.** The wallet scores CRITICAL. In the graph, click *Demo Exchange C*: the fund-flow trace follows all 10 peel hops to the exchange. The recommendations name that exchange for a KYC request.
3. **Demo case → GEO_HOP.** The Threat Map opens automatically: Frankfurt (Tor) → New York → Reykjavik (VPN) in under an hour, which is impossible travel.
4. **Demo case → RANSOM_CASHOUT.** It shows ransomware exposure, 425 days of dormancy and then a cash-out to an exchange.
5. **Known threat → WANNACRY** (real mainnet). Point out the fan-in of victim payments (57 distinct senders within 24 h), the attribution floor and the ML explanation.
6. **Known threat → GENESIS.** It scores LOW: the only signals are tribute dust and inbound fan-in. This is where false-positive control shows.
7. **Case report.** Generate it, fill in the FIR reference, click **Verify integrity**, then print or save as PDF.
8. Run the **relay sensor** live: within a minute it stores hundreds of real first-relay observations (the header chip changes to `RELAY SENSOR LIVE`).

## API

`GET /api/wallet/{address}/analyze` · `/graph` · `/graph/expand?root=` · `/transactions` · `/report` ·
`POST /api/report/verify` · `GET /api/alerts` · `POST /api/alerts/{id}/ack` ·
`POST /api/telemetry/observations` · `GET /api/telemetry/stats|recent` · `GET /api/live/mempool|blocks|price|whale-alerts` ·
`GET /api/live/monitor/{address}` (SSE) · `GET /api/health` · `GET /api/stats` · `GET /api/demo/scenarios` ·
`GET /api/entities/watchlist` — interactive docs at `/docs`.

## Honest limitations

- Attribution labels are intelligence leads, not proof of ownership. Curated labels carry a confidence level.
- For very active addresses only the most recent 150 transactions are analysed. The UI and the report say so, and the confidence level reflects it.
- Relay IPs identify the first peer that announced a transaction to SIFRA's node. They are probabilistic origin estimates, not subscriber identities.
- Common-input-ownership can be defeated by CoinJoin and PayJoin. CoinJoins are detected and excluded from clustering.
