from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app.models import Candle


class TradeCandleBuilder:
    """
    Builds 1-minute candles from live trade ticks.
    """

    def __init__(self) -> None:
        self.current: Dict[str, Candle] = {}
        self.closed: Dict[str, List[Candle]] = {}

    @staticmethod
    def _minute_start(ts: datetime) -> datetime:
        ts_utc = ts.astimezone(timezone.utc)
        return ts_utc.replace(second=0, microsecond=0)

    def update_trade(
        self,
        symbol: str,
        trade_timestamp: datetime,
        trade_price: float,
        trade_size: float,
    ) -> Optional[Candle]:
        bucket_start = self._minute_start(trade_timestamp)
        bucket_end = bucket_start + timedelta(minutes=1)

        candle = self.current.get(symbol)

        if candle is None:
            self.current[symbol] = Candle(
                symbol=symbol,
                start=bucket_start,
                end=bucket_end,
                open=trade_price,
                high=trade_price,
                low=trade_price,
                close=trade_price,
                volume=trade_size,
                trade_count=1,
            )
            return None

        if candle.start == bucket_start:
            candle.update(trade_price, trade_size)
            return None

        closed_candle = candle
        self.closed.setdefault(symbol, []).append(closed_candle)

        self.current[symbol] = Candle(
            symbol=symbol,
            start=bucket_start,
            end=bucket_end,
            open=trade_price,
            high=trade_price,
            low=trade_price,
            close=trade_price,
            volume=trade_size,
            trade_count=1,
        )
        return closed_candle

    def get_closed_candles(self, symbol: str) -> List[Candle]:
        return self.closed.get(symbol, [])

    def get_latest_closes(self, symbol: str) -> List[float]:
        return [c.close for c in self.closed.get(symbol, [])]
