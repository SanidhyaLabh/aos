"""
SQLAlchemy Models for ORIGIN Durable Audit Trail & Telemetry
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, BigInteger
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class SourceModel(Base):
    __tablename__ = "sources"

    id = Column(String(64), primary_key=True)
    provider = Column(String(64), nullable=False)
    source_group = Column(String(64), nullable=False)
    data_domain = Column(String(32), nullable=False) # e.g. CUSTODIAN, EXCHANGE, INTERBANK
    asset = Column(String(32), nullable=False)
    weight = Column(Float, default=1.0)
    max_age_seconds = Column(Integer, default=60)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class ObservationModel(Base):
    __tablename__ = "observations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_id = Column(String(32), nullable=False, index=True)
    source_id = Column(String(64), nullable=False, index=True)
    source_group = Column(String(64), nullable=False)
    price = Column(Float, nullable=False)
    decimals = Column(Integer, default=18)
    quote_currency = Column(String(8), default="USD")
    timestamp = Column(BigInteger, nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow)

class AttestationModel(Base):
    __tablename__ = "attestations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_id = Column(String(32), nullable=False, index=True)
    round_id = Column(BigInteger, nullable=False, index=True)
    aggregate_price = Column(Float, nullable=False)
    source_count = Column(Integer, nullable=False)
    divergence_bps = Column(Float, nullable=False)
    window_start = Column(BigInteger, nullable=False)
    window_end = Column(BigInteger, nullable=False)
    signature = Column(Text, nullable=False)
    tx_hash = Column(String(66), nullable=True)
    status = Column(String(32), default="GENERATED") # GENERATED, SUBMITTED, CONFIRMED, REJECTED
    created_at = Column(DateTime, default=datetime.utcnow)

class SentinelEventModel(Base):
    __tablename__ = "sentinel_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_address = Column(String(42), nullable=False, index=True)
    old_state = Column(String(16), nullable=False)
    new_state = Column(String(16), nullable=False)
    trigger = Column(Text, nullable=False)
    block_number = Column(BigInteger, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

class ExposureSnapshotModel(Base):
    __tablename__ = "exposure_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tier = Column(String(16), nullable=False) # GLOBAL, GROUP, MARKET
    address = Column(String(42), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    available_capacity = Column(Float, nullable=False)
    max_capacity = Column(Float, nullable=False)
    total_issued = Column(Float, nullable=False)
    utilization_pct = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

class TransactionRecordModel(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tx_hash = Column(String(66), unique=True, index=True)
    nonce = Column(BigInteger, nullable=False)
    to_address = Column(String(42), nullable=False)
    function_name = Column(String(64), nullable=False)
    status = Column(String(16), default="PENDING") # PENDING, CONFIRMED, REVERTED
    gas_used = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
