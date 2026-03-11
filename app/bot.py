from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from app.alpaca_clients import AlpacaClients
from app.candle_builder import TradeCandleBuilder
from app.config import Settings
from app.logger import setup_logger
from app.strategy import MovingAverageCrossStrategy

logger = logging.getLogger(__name__)

MARKET_TZ = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
CORE_OPEN = time(10, 0)
CORE_CLOSE = time(15, 0)


@dataclass
class PositionRisk:
    symbol: str
    side: str  # LONG or SHORT
    entry_price: float
    qty: float
    stop_loss: float
    take_profit: float


class AlpacaPaperTradingBot:
    def __init__(self) -> None:
        self.settings = Settings()
        setup_logger(self.settings)

        self.clients = AlpacaClients(self.settings)
        self.candle_builder = TradeCandleBuilder()
        self.strategy = MovingAverageCrossStrategy(
            short_window=self.settings.short_ma,
            long_window=self.settings.long_ma,
            allow_shorts=self.settings.allow_shorts,
        )

        self.latest_trade_price: Dict[str, float] = {}
        self.last_signal_minute: Dict[str, str] = {}
        self.position_risk: Dict[str, PositionRisk] = {}
        self.current_day: Optional[date] = None
        self.day_start_equity: float = self.settings.starting_cash
        self.daily_pause_reason: Optional[str] = None

    @staticmethod
    def _to_market_dt(ts: datetime) -> datetime:
        if ts.tzinfo is None:
            return ts.replace(tzinfo=MARKET_TZ)
        return ts.astimezone(MARKET_TZ)

    def _reset_daily_state(self, now_market: datetime) -> None:
        if self.current_day == now_market.date():
            return
        self.current_day = now_market.date()
        account = self.clients.get_account()
        self.day_start_equity = float(account.equity)
        self.daily_pause_reason = None
        logger.info("New trading day %s day_start_equity=%.2f", self.current_day.isoformat(), self.day_start_equity)

    def _is_trading_day(self, now_market: datetime) -> bool:
        return now_market.weekday() < 5

    def _is_market_open(self, now_market: datetime) -> bool:
        now_t = now_market.time()
        return MARKET_OPEN <= now_t <= MARKET_CLOSE

    def _is_core_hours(self, now_market: datetime) -> bool:
        now_t = now_market.time()
        return CORE_OPEN <= now_t <= CORE_CLOSE

    def _current_daily_pnl_pct(self) -> float:
        if self.day_start_equity <= 0:
            return 0.0
        account = self.clients.get_account()
        equity = float(account.equity)
        return (equity - self.day_start_equity) / self.day_start_equity

    def _risk_based_notional(self, price: float, buying_power: float) -> float:
        account = self.clients.get_account()
        equity = float(account.equity)
        max_risk_dollars = min(equity * self.settings.risk_per_trade_pct, equity * 0.10)
        qty_from_risk = max_risk_dollars / (price * self.settings.stop_loss_pct)
        notional_from_risk = qty_from_risk * price
        return min(
            self.settings.trade_notional_usd,
            self.settings.max_position_notional_usd,
            buying_power,
            notional_from_risk,
        )

    def seed_history(self) -> None:
        """
        Pull recent 1-minute bars so the moving averages have warm-up data
        before the live trade stream starts.
        """
        bars = self.clients.get_recent_bars(
            symbols=self.settings.symbols,
            limit=max(self.settings.long_ma + 5, 30),
        )

        df = bars.df
        if df.empty:
            logger.warning("No historical bars returned for seed history.")
            return

        for symbol in self.settings.symbols:
            try:
                symbol_df = df.xs(symbol, level=0)
            except Exception:
                continue

            for ts, row in symbol_df.iterrows():
                closed = self.candle_builder.closed.setdefault(symbol, [])
                closed.append(
                    __import__("app.models", fromlist=["Candle"]).Candle(
                        symbol=symbol,
                        start=ts.to_pydatetime(),
                        end=ts.to_pydatetime(),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                        trade_count=int(row.get("trade_count", 0) or 0),
                    )
                )
                self.latest_trade_price[symbol] = float(row["close"])

        logger.info("Seeded history for symbols: %s", ", ".join(self.settings.symbols))

    async def on_trade(self, trade) -> None:
        """
        Alpaca trade object fields commonly include:
        - symbol
        - price
        - size
        - timestamp
        """
        symbol = trade.symbol
        price = float(trade.price)
        size = float(trade.size)
        timestamp = self._to_market_dt(trade.timestamp)

        self.latest_trade_price[symbol] = price
        self._reset_daily_state(timestamp)

        await self.check_position_risk_exit(symbol, price)

        risk_state = self.position_risk.get(symbol)
        logger.info(
            "LIVE symbol=%s price=%.2f take_profit=%s stop_loss=%s",
            symbol,
            price,
            f"{risk_state.take_profit:.2f}" if risk_state else "N/A",
            f"{risk_state.stop_loss:.2f}" if risk_state else "N/A",
        )

        closed_candle = self.candle_builder.update_trade(
            symbol=symbol,
            trade_timestamp=timestamp,
            trade_price=price,
            trade_size=size,
        )

        if closed_candle is not None:
            logger.info(
                "CANDLE %s %s O=%.2f H=%.2f L=%.2f C=%.2f V=%.0f trades=%d",
                closed_candle.symbol,
                closed_candle.start.isoformat(),
                closed_candle.open,
                closed_candle.high,
                closed_candle.low,
                closed_candle.close,
                closed_candle.volume,
                closed_candle.trade_count,
            )
            await self.evaluate_symbol(symbol, timestamp)

    async def check_position_risk_exit(self, symbol: str, price: float) -> None:
        risk_state = self.position_risk.get(symbol)
        if risk_state is None:
            return

        if risk_state.side == "LONG":
            if price <= risk_state.stop_loss:
                logger.warning("ALERT STOP LOSS HIT symbol=%s price=%.2f stop_loss=%.2f", symbol, price, risk_state.stop_loss)
                await self.place_signal_order(symbol, "SELL", risk_state.qty)
                self.position_risk.pop(symbol, None)
            elif price >= risk_state.take_profit:
                logger.info("ALERT TAKE PROFIT HIT symbol=%s price=%.2f take_profit=%.2f", symbol, price, risk_state.take_profit)
                await self.place_signal_order(symbol, "SELL", risk_state.qty)
                self.position_risk.pop(symbol, None)
        else:
            if price >= risk_state.stop_loss:
                logger.warning("ALERT STOP LOSS HIT symbol=%s price=%.2f stop_loss=%.2f", symbol, price, risk_state.stop_loss)
                await self.place_signal_order(symbol, "BUY_TO_COVER", -risk_state.qty)
                self.position_risk.pop(symbol, None)
            elif price <= risk_state.take_profit:
                logger.info("ALERT TAKE PROFIT HIT symbol=%s price=%.2f take_profit=%.2f", symbol, price, risk_state.take_profit)
                await self.place_signal_order(symbol, "BUY_TO_COVER", -risk_state.qty)
                self.position_risk.pop(symbol, None)

    async def evaluate_symbol(self, symbol: str, now_market: datetime) -> None:
        closes: List[float] = self.candle_builder.get_latest_closes(symbol)
        latest_price = self.latest_trade_price.get(symbol)

        if latest_price is None:
            return

        if not self._is_trading_day(now_market) or not self._is_market_open(now_market):
            return

        daily_pnl_pct = self._current_daily_pnl_pct()
        if daily_pnl_pct >= self.settings.daily_profit_target_pct:
            self.daily_pause_reason = "profit_target"
            logger.info("Daily profit target hit: pnl=%.2f%%, pausing new entries until next day.", daily_pnl_pct * 100)
        elif daily_pnl_pct <= -self.settings.daily_loss_limit_pct:
            self.daily_pause_reason = "loss_limit"
            logger.warning("Daily loss limit hit: pnl=%.2f%%, pausing new entries until next day.", daily_pnl_pct * 100)

        current_qty = self.clients.get_position_qty(symbol)

        signal = self.strategy.evaluate(
            symbol=symbol,
            closes=closes,
            latest_price=latest_price,
            current_qty=current_qty,
        )
        if signal is None:
            return

        signal_key = f"{signal.action}:{closes[-1]}"
        if self.last_signal_minute.get(symbol) == signal_key:
            return
        self.last_signal_minute[symbol] = signal_key

        logger.info(
            "SIGNAL %s action=%s price=%.2f reason=%s current_qty=%.4f daily_pnl=%.2f%%",
            symbol,
            signal.action,
            signal.price,
            signal.reason,
            current_qty,
            daily_pnl_pct * 100,
        )

        if self.settings.dry_run:
            logger.info("DRY_RUN=true, skipping order placement.")
            return

        if self.daily_pause_reason and signal.action in {"BUY", "SELL_SHORT"}:
            logger.info("Entry skipped for %s due to daily pause reason=%s", symbol, self.daily_pause_reason)
            return

        if signal.action in {"BUY", "SELL_SHORT"} and not self._is_core_hours(now_market):
            logger.info("Entry skipped for %s outside core hours; core=10:00-15:00 ET", symbol)
            return

        await self.place_signal_order(symbol, signal.action, current_qty)

    async def place_signal_order(self, symbol: str, action: str, current_qty: float) -> None:
        account = self.clients.get_account()
        buying_power = float(account.buying_power)
        last_price = self.latest_trade_price.get(symbol)

        if action == "BUY":
            if last_price is None:
                logger.warning("BUY skipped for %s: missing latest price.", symbol)
                return
            notional = self._risk_based_notional(last_price, buying_power)
            if notional <= 0:
                logger.warning("BUY skipped for %s: no buying power/risk budget.", symbol)
                return

            order = self.clients.submit_market_order(
                symbol=symbol,
                side="BUY",
                notional_usd=notional,
            )
            qty = notional / last_price
            stop_loss = last_price * (1 - self.settings.stop_loss_pct)
            take_profit = last_price * (1 + (self.settings.stop_loss_pct * self.settings.take_profit_rr))
            self.position_risk[symbol] = PositionRisk(symbol, "LONG", last_price, qty, stop_loss, take_profit)
            logger.info(
                "ORDER SUBMITTED BUY %s notional=%.2f id=%s entry=%.2f stop_loss=%.2f take_profit=%.2f",
                symbol,
                notional,
                order.id,
                last_price,
                stop_loss,
                take_profit,
            )

        elif action == "SELL":
            if current_qty <= 0:
                logger.warning("SELL skipped for %s: no long position.", symbol)
                return

            order = self.clients.submit_market_order(
                symbol=symbol,
                side="SELL",
                qty=abs(current_qty),
            )
            self.position_risk.pop(symbol, None)
            logger.info("ORDER SUBMITTED SELL %s qty=%.4f id=%s", symbol, abs(current_qty), order.id)

        elif action == "SELL_SHORT":
            if not self.settings.allow_shorts:
                logger.warning("SELL_SHORT skipped for %s: shorts disabled.", symbol)
                return

            if last_price is None:
                logger.warning("SELL_SHORT skipped for %s: missing latest price.", symbol)
                return

            notional = self._risk_based_notional(last_price, buying_power)
            if notional <= 0:
                logger.warning("SELL_SHORT skipped for %s: no risk budget.", symbol)
                return

            order = self.clients.submit_market_order(
                symbol=symbol,
                side="SELL_SHORT",
                notional_usd=notional,
            )
            qty = notional / last_price
            stop_loss = last_price * (1 + self.settings.stop_loss_pct)
            take_profit = last_price * (1 - (self.settings.stop_loss_pct * self.settings.take_profit_rr))
            self.position_risk[symbol] = PositionRisk(symbol, "SHORT", last_price, qty, stop_loss, take_profit)
            logger.info(
                "ORDER SUBMITTED SELL_SHORT %s notional=%.2f id=%s entry=%.2f stop_loss=%.2f take_profit=%.2f",
                symbol,
                notional,
                order.id,
                last_price,
                stop_loss,
                take_profit,
            )

        elif action == "BUY_TO_COVER":
            if current_qty >= 0:
                logger.warning("BUY_TO_COVER skipped for %s: no short position.", symbol)
                return

            order = self.clients.submit_market_order(
                symbol=symbol,
                side="BUY_TO_COVER",
                qty=abs(current_qty),
            )
            self.position_risk.pop(symbol, None)
            logger.info("ORDER SUBMITTED BUY_TO_COVER %s qty=%.4f id=%s", symbol, abs(current_qty), order.id)

    def wire_subscriptions(self) -> None:
        for symbol in self.settings.symbols:
            self.clients.stream.subscribe_trades(self.on_trade, symbol)
            logger.info("Subscribed to live trades for %s", symbol)

    def run(self) -> None:
        logger.info("Starting Alpaca paper trading bot.")
        logger.info("Symbols: %s", ", ".join(self.settings.symbols))
        logger.info("Data feed: %s", self.settings.data_feed)
        logger.info("Paper trading: %s", self.settings.use_paper_trading)
        logger.info("Dry run: %s", self.settings.dry_run)

        account = self.clients.get_account()
        logger.info(
            "Account status=%s cash=%s buying_power=%s equity=%s",
            account.status,
            account.cash,
            account.buying_power,
            account.equity,
        )

        self.seed_history()
        self.wire_subscriptions()
        self.clients.stream.run()
