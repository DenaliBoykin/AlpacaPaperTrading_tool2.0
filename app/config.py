from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _get_list(name: str, default: str) -> List[str]:
    raw = os.getenv(name, default)
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    api_key: str = os.getenv("APCA_API_KEY_ID", "")
    api_secret: str = os.getenv("APCA_API_SECRET_KEY", "")
    symbols: List[str] = None  # type: ignore
    timeframe_minutes: int = int(os.getenv("TIMEFRAME_MINUTES", "1"))
    starting_cash: float = float(os.getenv("STARTING_CASH", "100000"))
    trade_notional_usd: float = float(os.getenv("TRADE_NOTIONAL_USD", "1000"))
    short_ma: int = int(os.getenv("SHORT_MA", "5"))
    long_ma: int = int(os.getenv("LONG_MA", "12"))
    use_paper_trading: bool = _get_bool("USE_PAPER_TRADING", True)
    data_feed: str = os.getenv("DATA_FEED", "IEX").upper()
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    allow_shorts: bool = _get_bool("ALLOW_SHORTS", False)
    max_position_notional_usd: float = float(os.getenv("MAX_POSITION_NOTIONAL_USD", "3000"))
    dry_run: bool = _get_bool("DRY_RUN", False)
    risk_per_trade_pct: float = float(os.getenv("RISK_PER_TRADE_PCT", "0.02"))
    stop_loss_pct: float = float(os.getenv("STOP_LOSS_PCT", "0.01"))
    take_profit_rr: float = float(os.getenv("TAKE_PROFIT_RR", "3.0"))
    daily_profit_target_pct: float = float(os.getenv("DAILY_PROFIT_TARGET_PCT", "0.08"))
    daily_loss_limit_pct: float = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "0.08"))

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", _get_list("SYMBOLS", "AAPL"))

        if not self.api_key or not self.api_secret:
            raise ValueError("Missing APCA_API_KEY_ID or APCA_API_SECRET_KEY in environment.")

        if self.short_ma >= self.long_ma:
            raise ValueError("SHORT_MA must be less than LONG_MA.")

        if self.timeframe_minutes != 1:
            raise ValueError("This starter currently supports only 1-minute trade aggregation.")

        if self.risk_per_trade_pct <= 0 or self.risk_per_trade_pct > 0.10:
            raise ValueError("RISK_PER_TRADE_PCT must be > 0 and <= 0.10 (10%).")

        if self.stop_loss_pct <= 0:
            raise ValueError("STOP_LOSS_PCT must be greater than 0.")

        if self.take_profit_rr <= 0 or self.take_profit_rr > 3.0:
            raise ValueError("TAKE_PROFIT_RR must be > 0 and <= 3.0 (max 1:3 risk/reward).")

        if self.daily_profit_target_pct <= 0:
            raise ValueError("DAILY_PROFIT_TARGET_PCT must be greater than 0.")

        if self.daily_loss_limit_pct <= 0:
            raise ValueError("DAILY_LOSS_LIMIT_PCT must be greater than 0.")
