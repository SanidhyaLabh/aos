"""
Exchange and Institutional Spot Source Adapters
"""

import time
import httpx
from typing import Optional
from backend.collectors.base import PriceSource, PriceObservation

class ExchangeSource(PriceSource):
    def __init__(
        self,
        source_id: str,
        source_group: str,
        provider: str,
        ticker_symbol: str = "ETH-USD",
        api_url: Optional[str] = None
    ):
        super().__init__(source_id, source_group, provider, "EXCHANGE_SPOT")
        self.ticker_symbol = ticker_symbol
        self.api_url = api_url or "https://api.coinbase.com/v2/prices/{pair}/spot"

    async def get_price(self, asset: str) -> Optional[PriceObservation]:
        try:
            url = self.api_url.format(pair=self.ticker_symbol)
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    raw_amount = float(data["data"]["amount"])
                    return PriceObservation(
                        asset_id=asset,
                        source_id=self.source_id,
                        source_group=self.source_group,
                        price=raw_amount,
                        timestamp=int(time.time()),
                        decimals=18,
                        quote_currency="USD",
                        metadata={"endpoint": url}
                    )
        except Exception:
            pass
        return None

class RWANAVSource(PriceSource):
    def __init__(
        self,
        source_id: str,
        source_group: str,
        provider: str,
        custodian_name: str,
        nav_api_url: Optional[str] = None
    ):
        super().__init__(source_id, source_group, provider, "RWA_CUSTODIAN_NAV")
        self.custodian_name = custodian_name
        self.nav_api_url = nav_api_url

    async def get_price(self, asset: str) -> Optional[PriceObservation]:
        if not self.nav_api_url:
            return None
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(self.nav_api_url)
                if resp.status_code == 200:
                    data = resp.json()
                    nav_price = float(data.get("nav", data.get("price", 100.0)))
                    ts = int(data.get("timestamp", time.time()))
                    return PriceObservation(
                        asset_id=asset,
                        source_id=self.source_id,
                        source_group=self.source_group,
                        price=nav_price,
                        timestamp=ts,
                        decimals=18,
                        quote_currency="USD",
                        metadata={"custodian": self.custodian_name}
                    )
        except Exception:
            pass
        return None
