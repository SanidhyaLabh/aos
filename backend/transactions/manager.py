"""
Transaction Manager & RPC Failover Module
Single source of truth for EVM blockchain writes, nonces, retries, and RPC provider failover.
"""

import time
import logging
from typing import List, Optional, Any, Dict
from web3 import Web3
from eth_account import Account

logger = logging.getLogger("origin.transactions")

class TransactionManager:
    def __init__(
        self,
        rpc_urls: List[str],
        private_key_hex: str,
        chain_id: int = 31337,
        max_retries: int = 3
    ):
        self.rpc_urls = rpc_urls
        self.current_rpc_index = 0
        self.chain_id = chain_id
        self.max_retries = max_retries
        self.account = Account.from_key(private_key_hex)
        self.address = self.account.address

        self.w3: Optional[Web3] = None
        self._nonce: Optional[int] = None
        self._connect_rpc()

    def _connect_rpc(self):
        """Attempts connection to RPC providers in priority order."""
        for i in range(len(self.rpc_urls)):
            idx = (self.current_rpc_index + i) % len(self.rpc_urls)
            url = self.rpc_urls[idx]
            try:
                provider = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 5.0}))
                if provider.is_connected():
                    self.w3 = provider
                    self.current_rpc_index = idx
                    logger.info(f"Connected to RPC provider: {url}")
                    return
            except Exception as e:
                logger.warning(f"Failed to connect to RPC {url}: {e}")

        logger.error("All configured RPC endpoints are unreachable.")

    def failover_rpc(self):
        """Switches to the next healthy RPC provider."""
        self.current_rpc_index = (self.current_rpc_index + 1) % len(self.rpc_urls)
        logger.warning(f"Failing over to next RPC: {self.rpc_urls[self.current_rpc_index]}")
        self._connect_rpc()

    def get_nonce(self) -> int:
        """Retrieves and manages synchronized account nonce."""
        if not self.w3:
            self._connect_rpc()
        
        on_chain_nonce = self.w3.eth.get_transaction_count(self.address, "pending")
        if self._nonce is None or on_chain_nonce > self._nonce:
            self._nonce = on_chain_nonce
        else:
            self._nonce += 1
        return self._nonce

    def reset_nonce(self):
        """Refreshes nonce directly from node upon failure or reorg."""
        if self.w3:
            self._nonce = self.w3.eth.get_transaction_count(self.address, "latest")

    def send_transaction(
        self,
        contract_fn: Any,
        gas_limit: Optional[int] = None,
        value: int = 0
    ) -> Dict[str, Any]:
        """
        Executes a contract write with nonce tracking, gas estimation, failover, and receipt confirmation.
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                if not self.w3 or not self.w3.is_connected():
                    self._connect_rpc()

                nonce = self.get_nonce()
                gas_price = self.w3.eth.gas_price

                # Estimate gas if not provided
                if not gas_limit:
                    try:
                        estimated = contract_fn.estimate_gas({"from": self.address, "value": value})
                        gas_limit = int(estimated * 1.25)
                    except Exception:
                        gas_limit = 500_000

                tx = contract_fn.build_transaction({
                    "from": self.address,
                    "nonce": nonce,
                    "gas": gas_limit,
                    "gasPrice": gas_price,
                    "chainId": self.chain_id,
                    "value": value
                })

                signed_tx = self.w3.eth.account.sign_transaction(tx, self.account.key)
                tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                hex_hash = tx_hash.hex()
                logger.info(f"Transaction broadcast: {hex_hash} (nonce={nonce}, attempt={attempt})")

                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=15)
                success = receipt.status == 1

                return {
                    "success": success,
                    "tx_hash": hex_hash,
                    "nonce": nonce,
                    "block_number": receipt.blockNumber,
                    "gas_used": receipt.gasUsed,
                    "status": "CONFIRMED" if success else "REVERTED"
                }

            except Exception as err:
                logger.warning(f"Transaction attempt {attempt} failed: {err}")
                self.reset_nonce()
                if attempt == self.max_retries:
                    self.failover_rpc()
                    return {
                        "success": False,
                        "error": str(err),
                        "status": "FAILED"
                    }
                time.sleep(1.0)

        return {"success": False, "status": "EXHAUSTED"}
