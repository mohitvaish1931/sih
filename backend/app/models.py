from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, UniqueConstraint
from sqlalchemy.sql import func
from app.database import Base


class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, index=True)
    address = Column(String, unique=True, index=True)
    risk_score = Column(Float, default=0.0)
    risk_level = Column(String, default="LOW")
    cluster_id = Column(String, nullable=True)
    first_seen = Column(DateTime(timezone=True), nullable=True)
    last_seen = Column(DateTime(timezone=True), nullable=True)


class Transaction(Base):
    """
    Value-flow edge (sender -> receiver) derived from an on-chain transaction.
    One Bitcoin transaction produces one edge per relevant output. This table
    powers the investigation graph; the full transaction lives in ChainTx.
    """
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    tx_hash = Column(String, unique=True, index=True)   # "<txid>_<vout>" edge key
    txid = Column(String, index=True, nullable=True)
    vout = Column(Integer, nullable=True)
    from_address = Column(String, index=True)
    to_address = Column(String, index=True)
    amount = Column(Float)
    timestamp = Column(DateTime(timezone=True))
    block_height = Column(Integer)
    ip_address = Column(String, nullable=True)
    country = Column(String, nullable=True)
    city = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    isp = Column(String, nullable=True)
    is_vpn_tor = Column(Boolean, default=False)


class ChainTx(Base):
    """Full normalized transaction (all inputs and outputs) as seen on-chain."""
    __tablename__ = "chain_txs"

    id = Column(Integer, primary_key=True)
    txid = Column(String, unique=True, index=True, nullable=False)
    block_height = Column(Integer, nullable=True)
    block_time = Column(DateTime(timezone=True), nullable=True)
    fee_btc = Column(Float, default=0.0)
    input_count = Column(Integer, default=0)
    output_count = Column(Integer, default=0)
    inputs_json = Column(Text)    # [{"address": str|null, "value": float}]
    outputs_json = Column(Text)   # [{"address": str|null, "value": float, "n": int}]
    source = Column(String, default="esplora")


class AddressTx(Base):
    """Address -> transaction index (which txs touch an address and in which role)."""
    __tablename__ = "address_txs"
    __table_args__ = (UniqueConstraint("address", "txid", name="uq_address_txid"),)

    id = Column(Integer, primary_key=True)
    address = Column(String, index=True, nullable=False)
    txid = Column(String, index=True, nullable=False)
    is_input = Column(Boolean, default=False)
    is_output = Column(Boolean, default=False)


class AddressSync(Base):
    """Tracks when an address history was last pulled from the blockchain."""
    __tablename__ = "address_sync"

    address = Column(String, primary_key=True)
    last_synced = Column(DateTime(timezone=True))
    tx_count_fetched = Column(Integer, default=0)
    tx_count_onchain = Column(Integer, default=0)
    source = Column(String, nullable=True)


class RelayObservation(Base):
    """
    First-relay observation of a transaction on the Bitcoin P2P network
    (written by sensor/relay_sensor.py). The peer that announced a tx first is
    the best available estimate of its broadcast origin (first-spy estimator).
    """
    __tablename__ = "relay_observations"

    id = Column(Integer, primary_key=True)
    txid = Column(String, index=True, nullable=False)
    peer_ip = Column(String, nullable=False)
    first_seen = Column(DateTime(timezone=True), nullable=False)
    peers_announcing = Column(Integer, default=1)
    country = Column(String, nullable=True)
    city = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    isp = Column(String, nullable=True)
    is_vpn_tor = Column(Boolean, default=False)
    confidence = Column(Float, default=1.0)   # first-spy reliability (0..1), see relay_sensor.py
    sensor_id = Column(String, default="sifra-sensor")


class MlReference(Base):
    """Behavioural features of randomly sampled live mainnet addresses (ML reference population)."""
    __tablename__ = "ml_reference"

    address = Column(String, primary_key=True)
    features_json = Column(Text, nullable=False)
    tx_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    wallet_address = Column(String, index=True)
    alert_type = Column(String)
    severity = Column(String)
    score = Column(Float)
    reason = Column(String)
    details = Column(Text, nullable=True)
    acknowledged = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Cluster(Base):
    __tablename__ = "clusters"

    id = Column(Integer, primary_key=True, index=True)
    cluster_id = Column(String, unique=True, index=True)
    wallet_count = Column(Integer, default=0)
    risk_score = Column(Float, default=0.0)
    description = Column(String)


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, index=True)
    wallet_address = Column(String, unique=True, index=True)
    rule_score = Column(Float, default=0.0)
    anomaly_score = Column(Float, default=0.0)
    graph_score = Column(Float, default=0.0)
    exposure_score = Column(Float, default=0.0)
    geo_score = Column(Float, default=0.0)
    final_score = Column(Float, default=0.0)
    risk_level = Column(String)
    reasons = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)
