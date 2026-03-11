from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Candle:
    symbol: str
    start: datetime
    end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: int

    def update(self, price: float, size: float) -> None:
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += size
        self.trade_count += 1
