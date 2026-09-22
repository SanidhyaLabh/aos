"""
EIP-712 Attestation Package Builder
Constructs cryptographically typed data packages conforming to contracts/ASOAdapter.sol.
"""

from typing import Dict, Any, List
from web3 import Web3
from backend.oracle.engine import ConsensusResult

class AttestationBuilder:
    def __init__(self, chain_id: int, verifying_contract: str):
        self.chain_id = chain_id
        self.verifying_contract = Web3.to_checksum_address(verifying_contract)

    def get_domain(self) -> Dict[str, Any]:
        return {
            "name": "ORIGIN ASO",
            "version": "1",
            "chainId": self.chain_id,
            "verifyingContract": self.verifying_contract
        }

    def get_types(self) -> Dict[str, List[Dict[str, str]]]:
        return {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"}
            ],
            "Observation": [
                {"name": "sourceId", "type": "bytes32"},
                {"name": "sourceGroup", "type": "bytes32"},
                {"name": "price", "type": "uint256"},
                {"name": "timestamp", "type": "uint256"}
            ],
            "Attestation": [
                {"name": "assetId", "type": "bytes32"},
                {"name": "aggregatePrice", "type": "uint256"},
                {"name": "observations", "type": "Observation[]"},
                {"name": "windowStart", "type": "uint256"},
                {"name": "windowEnd", "type": "uint256"},
                {"name": "roundId", "type": "uint256"},
                {"name": "validUntil", "type": "uint256"}
            ]
        }

    def build_message(
        self,
        consensus: ConsensusResult,
        round_id: int,
        validity_duration_seconds: int = 3600
    ) -> Dict[str, Any]:
        """
        Builds message matching the EIP-712 Attestation struct.
        """
        # Asset ID as 0x-prefixed bytes32 hex
        if consensus.asset_id.startswith("0x") and len(consensus.asset_id) == 66:
            asset_bytes32 = consensus.asset_id
        else:
            raw_hash = Web3.keccak(text=consensus.asset_id).hex().replace("0x", "")
            asset_bytes32 = "0x" + raw_hash

        observations_payload = []
        for obs in consensus.observations:
            source_hex = Web3.keccak(text=obs.source_id).hex().replace("0x", "")
            group_hex = Web3.keccak(text=obs.source_group).hex().replace("0x", "")
            observations_payload.append({
                "sourceId": "0x" + source_hex,
                "sourceGroup": "0x" + group_hex,
                "price": int(obs.price * 10**18),
                "timestamp": int(obs.timestamp)
            })

        valid_until = consensus.window_end + validity_duration_seconds

        message = {
            "assetId": asset_bytes32,
            "aggregatePrice": int(consensus.aggregate_price * 10**18),
            "observations": observations_payload,
            "windowStart": int(consensus.window_start),
            "windowEnd": int(consensus.window_end),
            "roundId": int(round_id),
            "validUntil": int(valid_until)
        }

        return message

    def build_typed_data(
        self,
        consensus: ConsensusResult,
        round_id: int,
        validity_duration_seconds: int = 3600
    ) -> Dict[str, Any]:
        return {
            "types": self.get_types(),
            "primaryType": "Attestation",
            "domain": self.get_domain(),
            "message": self.build_message(consensus, round_id, validity_duration_seconds)
        }
