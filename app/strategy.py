from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Signal:
    symbol: str
    action: str  # BUY, SELL, SELL_SHORT, BUY_TO_COVER
    reason: str
    price: float


class MovingAverageCrossStrategy:
    def __init__(self, short_window: int, long_window: int, allow_shorts: bool = False) -> None:
        self.short_window = short_window
        self.long_window = long_window
        self.allow_shorts = allow_shorts

    @staticmethod
    def _sma(values: List[float]) -> float:
        return sum(values) / len(values)

    def evaluate(
        self,
        symbol: str,
        closes: List[float],
        latest_price: float,
        current_qty: float,
    ) -> Optional[Signal]:
        if len(closes) < self.long_window + 1:
            return None

        short_prev = self._sma(closes[-self.short_window - 1:-1])
        long_prev = self._sma(closes[-self.long_window - 1:-1])
        short_now = self._sma(closes[-self.short_window:])
        long_now = self._sma(closes[-self.long_window:])

        crossed_up = short_prev <= long_prev and short_now > long_now
        crossed_down = short_prev >= long_prev and short_now < long_now

        if crossed_up:
            if current_qty < 0:
                return Signal(symbol, "BUY_TO_COVER", "short_ma_cross_up", latest_price)
            if current_qty == 0:
                return Signal(symbol, "BUY", "short_ma_cross_up", latest_price)

        if crossed_down:
            if current_qty > 0:
                return Signal(symbol, "SELL", "short_ma_cross_down", latest_price)
            if current_qty == 0 and self.allow_shorts:
                return Signal(symbol, "SELL_SHORT", "short_ma_cross_down", latest_price)

        return None
