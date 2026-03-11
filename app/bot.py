from __future__ import annotations

import asyncio
import logging
from typing import Dict, List

from app.alpaca_clients import AlpacaClients
from app.candle_builder import TradeCandleBuilder
from app.config import Settings
from app.logger import setup_logger
from app.strategy import MovingAverageCrossStrategy

logger = logging.getLogger(__name__)


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
        timestamp = trade.timestamp

        self.latest_trade_price[symbol] = price

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
            await self.evaluate_symbol(symbol)

    async def evaluate_symbol(self, symbol: str) -> None:
        closes: List[float] = self.candle_builder.get_latest_closes(symbol)
        latest_price = self.latest_trade_price.get(symbol)

        if latest_price is None:
            return

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
            "SIGNAL %s action=%s price=%.2f reason=%s current_qty=%.4f",
            symbol,
            signal.action,
            signal.price,
            signal.reason,
            current_qty,
        )

        if self.settings.dry_run:
            logger.info("DRY_RUN=true, skipping order placement.")
            return

        await self.place_signal_order(symbol, signal.action, current_qty)

    async def place_signal_order(self, symbol: str, action: str, current_qty: float) -> None:
        account = self.clients.get_account()
        buying_power = float(account.buying_power)

        if action == "BUY":
            notional = min(
                self.settings.trade_notional_usd,
                self.settings.max_position_notional_usd,
                buying_power,
            )
            if notional <= 0:
                logger.warning("BUY skipped for %s: no buying power.", symbol)
                return

            order = self.clients.submit_market_order(
                symbol=symbol,
                side="BUY",
                notional_usd=notional,
            )
            logger.info("ORDER SUBMITTED BUY %s notional=%.2f id=%s", symbol, notional, order.id)

        elif action == "SELL":
            if current_qty <= 0:
                logger.warning("SELL skipped for %s: no long position.", symbol)
                return

            order = self.clients.submit_market_order(
                symbol=symbol,
                side="SELL",
                qty=abs(current_qty),
            )
            logger.info("ORDER SUBMITTED SELL %s qty=%.4f id=%s", symbol, abs(current_qty), order.id)

        elif action == "SELL_SHORT":
            if not self.settings.allow_shorts:
                logger.warning("SELL_SHORT skipped for %s: shorts disabled.", symbol)
                return

            notional = min(
                self.settings.trade_notional_usd,
                self.settings.max_position_notional_usd,
            )
            order = self.clients.submit_market_order(
                symbol=symbol,
                side="SELL_SHORT",
                notional_usd=notional,
            )
            logger.info("ORDER SUBMITTED SELL_SHORT %s notional=%.2f id=%s", symbol, notional, order.id)

        elif action == "BUY_TO_COVER":
            if current_qty >= 0:
                logger.warning("BUY_TO_COVER skipped for %s: no short position.", symbol)
                return

            order = self.clients.submit_market_order(
                symbol=symbol,
                side="BUY_TO_COVER",
                qty=abs(current_qty),
            )
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
            "Account status=%s cash=%s buying_power=%s",
            account.status,
            account.cash,
            account.buying_power,
        )

        self.seed_history()
        self.wire_subscriptions()
        self.clients.stream.run()
