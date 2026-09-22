"""
System Health, Diagnostics, and Telemetry Metrics
"""

import time
from typing import Dict, Any

class SystemHealthMonitor:
    def __init__(self):
        self.start_time = time.time()
        self.last_pipeline_run = 0.0
        self.pipeline_cycles = 0
        self.failed_attestations = 0
        self.successful_attestations = 0
        self.failed_transactions = 0
        self.confirmed_transactions = 0
        self.active_sources = 0
        self.rpc_healthy = False
        self.db_healthy = False

    def record_pipeline_cycle(self, success: bool):
        self.pipeline_cycles += 1
        self.last_pipeline_run = time.time()
        if success:
            self.successful_attestations += 1
        else:
            self.failed_attestations += 1

    def get_live_status(self) -> Dict[str, Any]:
        """Kubernetes / Docker liveness probe."""
        uptime = time.time() - self.start_time
        return {
            "status": "UP",
            "uptime_seconds": round(uptime, 1),
            "timestamp": int(time.time())
        }

    def get_ready_status(self) -> Dict[str, Any]:
        """Readiness probe checking RPC and database connectivity."""
        is_ready = self.rpc_healthy and self.db_healthy
        return {
            "ready": is_ready,
            "rpc_healthy": self.rpc_healthy,
            "database_healthy": self.db_healthy,
            "cycles_completed": self.pipeline_cycles,
            "active_sources": self.active_sources
        }

    def get_metrics_prometheus(self) -> str:
        """Prometheus text-format metrics."""
        lines = [
            f"# HELP origin_uptime_seconds Total runtime of the ORIGIN daemon in seconds",
            f"# TYPE origin_uptime_seconds gauge",
            f"origin_uptime_seconds {time.time() - self.start_time:.1f}",
            f"# HELP origin_pipeline_cycles_total Total number of evaluation pipeline iterations",
            f"# TYPE origin_pipeline_cycles_total counter",
            f"origin_pipeline_cycles_total {self.pipeline_cycles}",
            f"# HELP origin_successful_attestations_total Total accepted attestations",
            f"# TYPE origin_successful_attestations_total counter",
            f"origin_successful_attestations_total {self.successful_attestations}",
            f"# HELP origin_failed_attestations_total Total rejected or failed attestations",
            f"# TYPE origin_failed_attestations_total counter",
            f"origin_failed_attestations_total {self.failed_attestations}"
        ]
        return "\n".join(lines) + "\n"

health_monitor = SystemHealthMonitor()
