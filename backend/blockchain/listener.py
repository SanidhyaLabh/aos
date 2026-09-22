"""
Blockchain Event Listener and Ingestion Service
Polls and filters on-chain event logs for ASO, Sentinel, EEG, and Lending Markets.
"""

import time
import logging
from typing import List, Dict, Any, Callable
from web3 import Web3

logger = logging.getLogger("origin.blockchain")

class BlockchainListener:
    def __init__(self, w3: Web3, contracts_dict: Dict[str, Any], start_block: int = 0):
        self.w3 = w3
        self.contracts = contracts_dict
        self.last_scanned_block = start_block
        self.handlers: List[Callable[[Dict[str, Any]], None]] = []

    def register_handler(self, handler: Callable[[Dict[str, Any]], None]):
        self.handlers.append(handler)

    def scan_new_blocks(self) -> List[Dict[str, Any]]:
        """Scans newly mined blocks for relevant events across deployed contracts."""
        if not self.w3 or not self.w3.is_connected():
            return []

        try:
            current_block = self.w3.eth.block_number
            if current_block < self.last_scanned_block:
                # Reorg detected
                logger.warning(f"Reorg detected! current_block={current_block} < last_scanned={self.last_scanned_block}")
                self.last_scanned_block = current_block

            if current_block == self.last_scanned_block:
                return []

            from_block = self.last_scanned_block + 1
            to_block = current_block
            all_events = []

            for name, contract in self.contracts.items():
                if not contract:
                    continue
                try:
                    # Scan all events emitted by this contract
                    logs = self.w3.eth.get_logs({
                        "fromBlock": from_block,
                        "toBlock": to_block,
                        "address": contract.address
                    })
                    for log in logs:
                        parsed_event = {
                            "contract": name,
                            "address": log["address"],
                            "block_number": log["blockNumber"],
                            "tx_hash": log["transactionHash"].hex(),
                            "topics": [t.hex() for t in log.get("topics", [])],
                            "data": log.get("data", "0x"),
                            "timestamp": int(time.time())
                        }
                        all_events.append(parsed_event)
                        for handler in self.handlers:
                            handler(parsed_event)
                except Exception as e:
                    logger.debug(f"Error reading logs for {name}: {e}")

            self.last_scanned_block = to_block
            return all_events
        except Exception as e:
            logger.warning(f"Block scanning error: {e}")
            return []
