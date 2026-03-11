from __future__ import annotations

import logging
from typing import Optional

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live.stock import StockDataStream
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest

from app.config import Settings

logger = logging.getLogger(__name__)


def _to_data_feed(feed_name: str) -> DataFeed:
    normalized = feed_name.upper()
    if normalized == "IEX":
        return DataFeed.IEX
    if normalized == "SIP":
        return DataFeed.SIP
    raise ValueError(f"Unsupported DATA_FEED: {feed_name}")


class AlpacaClients:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.feed = _to_data_feed(settings.data_feed)

        self.trading_client = TradingClient(
            api_key=settings.api_key,
            secret_key=settings.api_secret,
            paper=settings.use_paper_trading,
        )

        self.historical_client = StockHistoricalDataClient(
            api_key=settings.api_key,
            secret_key=settings.api_secret,
        )

        self.stream = StockDataStream(
            api_key=settings.api_key,
            secret_key=settings.api_secret,
            feed=self.feed,
        )

    def get_account(self):
        return self.trading_client.get_account()

    def get_position_qty(self, symbol: str) -> float:
        try:
            position = self.trading_client.get_open_position(symbol)
            return float(position.qty)
        except Exception:
            return 0.0

    def submit_market_order(self, symbol: str, side: str, notional_usd: Optional[float] = None, qty: Optional[float] = None):
        if side == "BUY":
            order_side = OrderSide.BUY
        elif side == "SELL":
            order_side = OrderSide.SELL
        elif side == "SELL_SHORT":
            order_side = OrderSide.SELL
        elif side == "BUY_TO_COVER":
            order_side = OrderSide.BUY
        else:
            raise ValueError(f"Unsupported side: {side}")

        request = MarketOrderRequest(
            symbol=symbol,
            side=order_side,
            time_in_force=TimeInForce.DAY,
            notional=notional_usd,
            qty=qty,
        )
        return self.trading_client.submit_order(order_data=request)

    def list_open_orders(self):
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
        return self.trading_client.get_orders(filter=req)

    def get_recent_bars(self, symbols: list[str], limit: int = 100):
        req = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Minute,
            limit=limit,
            feed=self.feed,
        )
        return self.historical_client.get_stock_bars(req)
