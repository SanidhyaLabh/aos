"""
ORIGIN Configuration Module
Centralized, environment-aware configuration using Pydantic settings.
"""

from typing import List, Optional
from pydantic import BaseModel, Field
import os
import json

class Settings(BaseModel):
    # Service identity
    ENV: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")
    API_PORT: int = Field(default=5001)
    API_HOST: str = Field(default="0.0.0.0")

    # Blockchain EVM
    RPC_URLS: List[str] = Field(
        default=["http://127.0.0.1:8545", "http://localhost:8545"]
    )
    CHAIN_ID: int = Field(default=31337)
    
    # Attester private key (Local development key #1 on Anvil)
    # In production, KMS or HSM abstraction is loaded
    ATTESTER_PRIVATE_KEY: str = Field(
        default="0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
    )
    
    # Storage
    DATABASE_URL: str = Field(default="sqlite:///./data/origin_audit.db")
    REDIS_URL: Optional[str] = Field(default=None) # Optional Redis with memory fallback

    # Oracle & Quorum Policies
    DEFAULT_ASSET: str = Field(default="RWAUSD")
    MIN_SOURCE_COUNT: int = Field(default=3)
    MIN_INDEPENDENT_GROUPS: int = Field(default=2)
    MAX_DIVERGENCE_BPS: int = Field(default=50) # 0.50%
    MAX_STALENESS_SECONDS: int = Field(default=60)
    MAX_WINDOW_SECONDS: int = Field(default=60)
    PIPELINE_INTERVAL_SECONDS: float = Field(default=5.0)

    # Deployments file path
    DEPLOYMENTS_PATH: str = Field(
        default=os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "src",
            "deployments.json"
        )
    )

    def load_deployments(self) -> dict:
        if os.path.exists(self.DEPLOYMENTS_PATH):
            try:
                with open(self.DEPLOYMENTS_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

settings = Settings()
