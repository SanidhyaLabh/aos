"""
Chainlink Price Source Adapter
Connects directly to an EVM AggregatorV3Interface feed to fetch on-chain valuations.
"""

import time
from typing import Optional
from web3 import Web3
from backend.collectors.base import PriceSource, PriceObservation

AGGREGATOR_V3_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"internalType": "uint80", "name": "roundId", "type": "uint80"},
            {"internalType": "int256", "name": "answer", "type": "int256"},
            {"internalType": "uint256", "name": "startedAt", "type": "uint256"},
            {"internalType": "uint256", "name": "updatedAt", "type": "uint256"},
            {"internalType": "uint80", "name": "answeredInRound", "type": "uint80"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function"
    }
]

class ChainlinkSource(PriceSource):
    def __init__(
        self,
        source_id: str,
        feed_address: str,
        w3: Optional[Web3] = None,
        source_group: str = "CHAINLINK_DON",
        provider: str = "Chainlink",
        data_domain: str = "ON_CHAIN_DON"
    ):
        super().__init__(source_id, source_group, provider, data_domain)
        self.feed_address = feed_address
        self.w3 = w3
        self._decimals = 8

    async def get_price(self, asset: str) -> Optional[PriceObservation]:
        if not self.w3 or not self.feed_address:
            return None

        try:
            contract = self.w3.eth.contract(
                address=self.w3.to_checksum_address(self.feed_address),
                abi=AGGREGATOR_V3_ABI
            )
            round_id, answer, _, updated_at, _ = contract.functions.latestRoundData().call()
            decimals = contract.functions.decimals().call()

            if answer <= 0:
                return None

            price = float(answer) / (10 ** decimals)

            return PriceObservation(
                asset_id=asset,
                source_id=self.source_id,
                source_group=self.source_group,
                price=price,
                timestamp=int(updated_at),
                decimals=18,
                quote_currency="USD",
                metadata={"round_id": round_id, "native_decimals": decimals}
            )
        except Exception:
            return None
