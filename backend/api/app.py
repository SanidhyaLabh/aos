"""
ORIGIN FastAPI Production Server
Serves standard v1 REST APIs, Prometheus telemetry, WebSocket streaming, and legacy terminal bridges.
"""

import os
import json
import time
import asyncio
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from web3 import Web3

from backend.config.settings import settings
from backend.database.session import init_db, ScopedSession
from backend.database.models import ObservationModel, AttestationModel, SentinelEventModel
from backend.collectors.deterministic import DeterministicPriceSource
from backend.normalization.normalizer import DataNormalizer
from backend.oracle.source_registry import SourceRegistry, SourceDefinition
from backend.oracle.engine import OracleEngine
from backend.attestation.builder import AttestationBuilder
from backend.attestation.signer import AttestationSigner
from backend.transactions.manager import TransactionManager
from backend.blockchain.listener import BlockchainListener
from backend.blockchain.processor import EventProcessor
from backend.risk.engine import ProductionRiskEngine
from backend.sentinel.controller import SentinelController
from backend.exposure.monitor import ExposureMonitor
from backend.monitoring.health import health_monitor
from backend.workers.pipeline_worker import PipelineWorker

# Web3 and Contract Initialization
w3 = Web3(Web3.HTTPProvider(settings.RPC_URLS[0]))
deployments = settings.load_deployments()

def get_contract(name: str):
    if not w3 or not w3.is_connected() or not deployments:
        return None
    contracts_meta = deployments.get("contracts", {})
    if name in contracts_meta:
        return w3.eth.contract(
            address=w3.to_checksum_address(contracts_meta[name]["address"]),
            abi=contracts_meta[name]["abi"]
        )
    return None

contracts_map = {
    "ASOAdapter": get_contract("ASOAdapter"),
    "GlobalExposureGuard": get_contract("GlobalExposureGuard"),
    "RiskGroupExposureGuard": get_contract("RiskGroupExposureGuard"),
    "EconomicExposureGuard": get_contract("EconomicExposureGuard"),
    "BorrowGateway": get_contract("BorrowGateway"),
    "SentinelRegistry": get_contract("SentinelRegistry"),
    "ToyLendingMarketASO": get_contract("ToyLendingMarketASO")
}

# Subsystem Wiring
registry = SourceRegistry(
    default_min_sources=settings.MIN_SOURCE_COUNT,
    default_min_independent_groups=settings.MIN_INDEPENDENT_GROUPS,
    default_max_divergence_bps=settings.MAX_DIVERGENCE_BPS
)

# Register default benchmark sources
sources_def = [
    SourceDefinition(source_id="ondo", provider="Ondo Finance", source_group="CUSTODIAN_GROUP", data_domain="RWA_NAV", asset="RWAUSD", weight=35.0),
    SourceDefinition(source_id="coinbase", provider="Coinbase Prime", source_group="EXCHANGE_GROUP", data_domain="SPOT_INDEX", asset="RWAUSD", weight=40.0),
    SourceDefinition(source_id="kraken", provider="Kraken Treasury", source_group="EXCHANGE_GROUP_2", data_domain="ORDERBOOK", asset="RWAUSD", weight=15.0),
    SourceDefinition(source_id="fed", provider="Fed H.15 Yield", source_group="INTERBANK_GROUP", data_domain="BENCHMARK", asset="RWAUSD", weight=10.0),
]
for s in sources_def:
    registry.register_source(s)

sources_adapters = [
    DeterministicPriceSource("ondo", "CUSTODIAN_GROUP", "Ondo Finance", "RWA_NAV", 100.0, 0.02),
    DeterministicPriceSource("coinbase", "EXCHANGE_GROUP", "Coinbase Prime", "SPOT_INDEX", 100.0, 0.03),
    DeterministicPriceSource("kraken", "EXCHANGE_GROUP_2", "Kraken Treasury", "ORDERBOOK", 100.0, -0.02),
    DeterministicPriceSource("fed", "INTERBANK_GROUP", "Fed H.15 Yield", "BENCHMARK", 100.0, 0.01)
]

normalizer = DataNormalizer()
oracle_engine = OracleEngine(registry)

aso_addr = contracts_map["ASOAdapter"].address if contracts_map["ASOAdapter"] else "0x0000000000000000000000000000000000000000"
builder = AttestationBuilder(settings.CHAIN_ID, aso_addr)
signer = AttestationSigner(settings.ATTESTER_PRIVATE_KEY)

tx_manager = TransactionManager(settings.RPC_URLS, settings.ATTESTER_PRIVATE_KEY, settings.CHAIN_ID)
listener = BlockchainListener(w3, contracts_map)
processor = EventProcessor()
risk_engine = ProductionRiskEngine()
sentinel_controller = SentinelController(contracts_map.get("SentinelRegistry"), tx_manager)
exposure_monitor = ExposureMonitor(w3, contracts_map)

worker = PipelineWorker(
    sources=sources_adapters,
    normalizer=normalizer,
    oracle_engine=oracle_engine,
    attestation_builder=builder,
    attestation_signer=signer,
    tx_manager=tx_manager,
    listener=listener,
    processor=processor,
    risk_engine=risk_engine,
    sentinel_controller=sentinel_controller,
    exposure_monitor=exposure_monitor,
    aso_contract=contracts_map.get("ASOAdapter"),
    asset_id="RWAUSD"
)

# Active WebSocket connections
active_connections: List[WebSocket] = []

async def broadcast_ws(event_type: str, data: Any):
    payload = json.dumps({"event": event_type, "data": data, "timestamp": int(time.time())})
    for conn in active_connections:
        try:
            await conn.send_text(payload)
        except Exception:
            pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB and start pipeline background task
    init_db()
    health_monitor.db_healthy = True
    health_monitor.rpc_healthy = w3.is_connected() if w3 else False

    pipeline_task = asyncio.create_task(worker.start(settings.PIPELINE_INTERVAL_SECONDS))
    yield
    # Shutdown
    worker.stop()
    pipeline_task.cancel()

app = FastAPI(
    title="ORIGIN // Oracle & Economic Risk Infrastructure API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Standard v1 Production APIs
# =============================================================================

@app.get("/api/v1/health")
def get_health():
    return health_monitor.get_ready_status()

@app.get("/health/live")
def get_live():
    return health_monitor.get_live_status()

@app.get("/health/ready")
def get_ready():
    return health_monitor.get_ready_status()

@app.get("/api/v1/metrics", response_class=PlainTextResponse)
def get_metrics():
    return health_monitor.get_metrics_prometheus()

@app.get("/api/v1/markets")
def list_markets():
    return {
        "markets": [
            {
                "id": "RWAUSD",
                "name": "RWA Yield Backed Senior Credit",
                "collateralAsset": "RWAUSD",
                "debtAsset": "USD",
                "marketAddress": contracts_map["ToyLendingMarketASO"].address if contracts_map["ToyLendingMarketASO"] else None,
                "gatewayAddress": contracts_map["BorrowGateway"].address if contracts_map["BorrowGateway"] else None,
                "status": "ACTIVE"
            }
        ]
    }

@app.get("/api/v1/markets/{market_id}")
def get_market_detail(market_id: str):
    exposure = worker.last_exposure_telemetry.get("markets", {}).get(market_id, {})
    return {
        "market_id": market_id,
        "oracle_price": worker.last_consensus.aggregate_price if worker.last_consensus else 100.0,
        "sentinel_state": worker.sentinel_controller.current_state,
        "exposure": exposure
    }

@app.get("/api/v1/oracle/{asset_id}")
def get_oracle_data(asset_id: str):
    consensus = worker.last_consensus
    if not consensus:
        raise HTTPException(status_code=503, detail="Oracle telemetry not yet available")
    return {
        "asset_id": consensus.asset_id,
        "status": consensus.status,
        "price": consensus.aggregate_price,
        "min_price": consensus.min_price,
        "max_price": consensus.max_price,
        "divergence_bps": consensus.divergence_bps,
        "source_count": consensus.source_count,
        "independent_groups": consensus.independent_group_count,
        "window_start": consensus.window_start,
        "window_end": consensus.window_end,
        "evaluated_at": consensus.evaluated_at
    }

@app.get("/api/v1/attestations/{asset_id}")
def get_latest_attestation(asset_id: str):
    consensus = worker.last_consensus
    if not consensus or not consensus.success:
        return {"status": "NO_VALID_ATTESTATION", "reason": consensus.rejection_reason if consensus else "Uninitialized"}
    return {
        "asset_id": asset_id,
        "round_id": worker.round_id,
        "aggregate_price": consensus.aggregate_price,
        "observations_count": len(consensus.observations),
        "divergence_bps": consensus.divergence_bps,
        "window_start": consensus.window_start,
        "window_end": consensus.window_end
    }

@app.get("/api/v1/exposure")
@app.get("/api/v1/exposure/{market_id}")
def get_exposure(market_id: Optional[str] = None):
    return worker.last_exposure_telemetry

@app.get("/api/v1/risk")
@app.get("/api/v1/risk/{market_id}")
def get_risk(market_id: Optional[str] = None):
    snapshot = worker.last_risk_snapshot
    if not snapshot:
        raise HTTPException(status_code=503, detail="Risk scoring not yet computed")
    return snapshot

@app.get("/api/v1/sentinel")
@app.get("/api/v1/sentinel/{market_id}")
def get_sentinel(market_id: Optional[str] = None):
    return {
        "currentState": worker.sentinel_controller.current_state,
        "lastTrigger": worker.last_risk_snapshot.rationale if worker.last_risk_snapshot else "Healthy consensus",
        "recommendedState": worker.last_risk_snapshot.recommended_state if worker.last_risk_snapshot else "NORMAL"
    }

@app.get("/api/v1/events")
def get_events(limit: int = 50):
    db = ScopedSession()
    try:
        events = db.query(SentinelEventModel).order_by(SentinelEventModel.id.desc()).limit(limit).all()
        return [
            {
                "id": e.id,
                "market": e.market_address,
                "old_state": e.old_state,
                "new_state": e.new_state,
                "trigger": e.trigger,
                "timestamp": e.timestamp.isoformat()
            }
            for e in events
        ]
    finally:
        db.close()

# WebSocket Real-Time Event Stream
@app.websocket("/api/v1/stream")
async def websocket_stream(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        # Send initial state snapshot immediately upon connection
        await websocket.send_text(json.dumps({
            "event": "INITIAL_STATE",
            "sentinelState": worker.sentinel_controller.current_state,
            "oraclePrice": worker.last_consensus.aggregate_price if worker.last_consensus else 100.0,
            "exposure": worker.last_exposure_telemetry
        }))
        while True:
            # Keep-alive ping
            await asyncio.sleep(10)
            await websocket.send_text(json.dumps({"event": "PING", "timestamp": int(time.time())}))
    except WebSocketDisconnect:
        active_connections.remove(websocket)
    except Exception:
        if websocket in active_connections:
            active_connections.remove(websocket)

# =============================================================================
# Legacy & Console Bridge APIs (Ensures UI and scripts run seamlessly)
# =============================================================================

@app.get("/api/status")
@app.get("/status")
def get_legacy_status():
    consensus = worker.last_consensus
    exposure = worker.last_exposure_telemetry.get("markets", {}).get("RWAUSD", {})
    return {
        "sentinelState": worker.sentinel_controller.current_state,
        "sentinelCeiling": 500_000.0,
        "recoveryStreak": 0,
        "sentinelTrigger": worker.last_risk_snapshot.rationale if worker.last_risk_snapshot else "Healthy consensus",
        "totalDebt": 0.0,
        "borrowedThisEpoch": 0.0,
        "currentEpoch": 1,
        "epochDurationSec": 300,
        "collateralAmount": 1000.0,
        "basePrice": consensus.aggregate_price if consensus else 100.0,
        "simpleMean": consensus.aggregate_price if consensus else 100.0,
        "weightedMedian": consensus.aggregate_price if consensus else 100.0,
        "twap": consensus.aggregate_price if consensus else 100.0,
        "effectivePrice": consensus.aggregate_price if consensus else 100.0,
        "activeScenario": "baseline",
        "lastTxResult": "Continuous Pipeline Active",
        "lastTxStatus": "confirmed",
        "cycleCount": worker.round_id,
        "eeg": {
            "currentCapacity": exposure.get("available", 100_000.0),
            "maxCapacity": exposure.get("max", 100_000.0),
            "refillRatePerSec": 27.78,
            "utilizationPct": exposure.get("utilization_pct", 0.0)
        }
    }

@app.get("/api/eeg/state")
@app.get("/eeg/state")
def get_eeg_state():
    telemetry = worker.last_exposure_telemetry
    rwa_market = telemetry.get("markets", {}).get("RWAUSD", {})
    global_eeg = telemetry.get("global", {})
    return {
        "currentCapacity": rwa_market.get("available", 100_000.0),
        "maxCapacity": rwa_market.get("max", 100_000.0),
        "refillRatePerSec": 27.78,
        "totalIssued": rwa_market.get("total_issued", 0.0),
        "utilizationPct": rwa_market.get("utilization_pct", 0.0),
        "global": global_eeg
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.api.app:app", host=settings.API_HOST, port=settings.API_PORT, reload=False)
