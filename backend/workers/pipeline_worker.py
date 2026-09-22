"""
ORIGIN Production Continuous Pipeline Worker
Executes the core loop:
COLLECT -> NORMALIZE -> VALIDATE -> ATTEST -> PUBLISH -> OBSERVE BLOCKCHAIN -> CALCULATE RISK -> UPDATE POLICY -> MONITOR EXPOSURE -> REPEAT
"""

import asyncio
import logging
import time
from typing import List, Dict, Any, Optional
from web3 import Web3

from backend.config.settings import settings
from backend.collectors.base import PriceSource, PriceObservation
from backend.normalization.normalizer import DataNormalizer
from backend.oracle.source_registry import SourceRegistry
from backend.oracle.engine import OracleEngine, ConsensusResult
from backend.attestation.builder import AttestationBuilder
from backend.attestation.signer import AttestationSigner
from backend.transactions.manager import TransactionManager
from backend.blockchain.listener import BlockchainListener
from backend.blockchain.processor import EventProcessor
from backend.risk.engine import ProductionRiskEngine, RiskScoreSnapshot
from backend.sentinel.controller import SentinelController
from backend.exposure.monitor import ExposureMonitor
from backend.monitoring.health import health_monitor
from backend.database.session import ScopedSession
from backend.database.models import ObservationModel, AttestationModel

logger = logging.getLogger("origin.pipeline")

class PipelineWorker:
    def __init__(
        self,
        sources: List[PriceSource],
        normalizer: DataNormalizer,
        oracle_engine: OracleEngine,
        attestation_builder: AttestationBuilder,
        attestation_signer: AttestationSigner,
        tx_manager: TransactionManager,
        listener: BlockchainListener,
        processor: EventProcessor,
        risk_engine: ProductionRiskEngine,
        sentinel_controller: SentinelController,
        exposure_monitor: ExposureMonitor,
        aso_contract: Optional[Any] = None,
        asset_id: str = "RWAUSD"
    ):
        self.sources = sources
        self.normalizer = normalizer
        self.oracle_engine = oracle_engine
        self.builder = attestation_builder
        self.signer = attestation_signer
        self.tx_manager = tx_manager
        self.listener = listener
        self.processor = processor
        self.risk_engine = risk_engine
        self.sentinel_controller = sentinel_controller
        self.exposure_monitor = exposure_monitor
        self.aso_contract = aso_contract
        self.asset_id = asset_id

        self.round_id = 1
        self.is_running = False
        self.last_consensus: Optional[ConsensusResult] = None
        self.last_risk_snapshot: Optional[RiskScoreSnapshot] = None
        self.last_exposure_telemetry: Dict[str, Any] = {}
        self.latest_observations: List[PriceObservation] = []

    async def execute_cycle(self):
        """Executes one continuous pipeline evaluation cycle."""
        logger.info(f"=== Starting Pipeline Evaluation Cycle (Round {self.round_id}) ===")

        # 1. COLLECT: Gather live observations from registered sources
        raw_observations: List[PriceObservation] = []
        for src in self.sources:
            try:
                obs = await src.get_price(self.asset_id)
                if obs:
                    raw_observations.append(obs)
            except Exception as e:
                logger.warning(f"Error collecting from {src.source_id}: {e}")

        # 2. NORMALIZE: Cleanse and validate formatting
        valid_observations = self.normalizer.filter_valid(raw_observations)
        self.latest_observations = valid_observations
        health_monitor.active_sources = len(valid_observations)

        # Persist observations to DB
        db = ScopedSession()
        try:
            for obs in valid_observations:
                db.add(ObservationModel(
                    asset_id=obs.asset_id,
                    source_id=obs.source_id,
                    source_group=obs.source_group,
                    price=obs.price,
                    timestamp=obs.timestamp
                ))
            db.commit()
        except Exception as e:
            db.rollback()
            logger.debug(f"DB log error: {e}")
        finally:
            db.close()

        # 3. VALIDATE & AGGREGATE (Oracle Engine)
        consensus = self.oracle_engine.evaluate_consensus(valid_observations)
        self.last_consensus = consensus

        # 4. ATTEST & PUBLISH: If consensus satisfies security policy, build EIP-712 and submit on-chain
        if consensus.success and self.aso_contract and self.tx_manager:
            try:
                typed_data = self.builder.build_typed_data(
                    consensus=consensus,
                    round_id=self.round_id,
                    validity_duration_seconds=3600
                )
                sig_hex = self.signer.sign_typed_data(typed_data)
                args_tuple = self.signer.format_contract_args(typed_data, sig_hex)

                fn = self.aso_contract.functions.submitAttestation(args_tuple)
                tx_res = self.tx_manager.send_transaction(fn)

                if tx_res.get("success"):
                    logger.info(f"Attestation submitted successfully on-chain! Tx: {tx_res.get('tx_hash')}")
                    health_monitor.record_pipeline_cycle(True)
                    self.round_id += 1
                else:
                    logger.warning(f"Attestation submission failed or reverted: {tx_res.get('error')}")
                    health_monitor.record_pipeline_cycle(False)

            except Exception as e:
                logger.error(f"Error publishing attestation: {e}")
                health_monitor.record_pipeline_cycle(False)
        else:
            if not consensus.success:
                logger.warning(f"Consensus rejected: {consensus.rejection_reason}")
            health_monitor.record_pipeline_cycle(False)

        # 5. OBSERVE BLOCKCHAIN: Scan new blocks for events
        events = self.listener.scan_new_blocks()

        # 6. MONITOR EXPOSURE: Query on-chain Hierarchical EEG buckets
        exposure_telemetry = self.exposure_monitor.get_full_hierarchical_exposure()
        self.last_exposure_telemetry = exposure_telemetry

        # 7. CALCULATE RISK & UPDATE POLICY (Sentinel State Machine)
        rwa_market_cap = exposure_telemetry.get("markets", {}).get("RWAUSD", {})
        avail_cap = rwa_market_cap.get("available", 100_000.0)
        max_cap = rwa_market_cap.get("max", 100_000.0)

        risk_snapshot = self.risk_engine.evaluate_risk(
            asset_id=self.asset_id,
            oracle_freshness_seconds=time.time() - (consensus.window_end if consensus else 0),
            source_count=consensus.source_count if consensus else 0,
            divergence_bps=consensus.divergence_bps if consensus else 0.0,
            available_capacity=avail_cap,
            max_capacity=max_cap,
            borrowed_in_last_hour=0.0,
            is_oracle_paused=False
        )
        self.last_risk_snapshot = risk_snapshot

        # 8. UPDATE SENTINEL POLICY
        self.sentinel_controller.update_from_risk_snapshot(risk_snapshot)

    async def start(self, interval_seconds: float = 5.0):
        """Starts continuous non-blocking evaluation loop."""
        self.is_running = True
        logger.info(f"Starting ORIGIN Continuous Pipeline Daemon (Interval: {interval_seconds}s)")
        while self.is_running:
            try:
                await self.execute_cycle()
            except Exception as e:
                logger.error(f"Unexpected pipeline cycle error: {e}")
            await asyncio.sleep(interval_seconds)

    def stop(self):
        self.is_running = False
