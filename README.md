# Alpaca Paper Trading Bot Starter

This repo is a starter project for Codex to extend.

It:
- streams real-time stock trades from Alpaca
- builds 1-minute candles from trades
- computes a simple moving-average crossover signal
- submits paper market orders to Alpaca paper trading
- keeps the code split into clean modules
- includes stop loss / take profit with capped 1:3 risk-reward
- enforces daily 8% profit target and 8% max daily loss pause
- restricts new entries to weekdays, market hours, and prioritizes core hours
- logs live symbol, price, stop loss, and take profit updates with alerts

## Important
- This is for paper trading only by default.
- Alpaca paper trading uses the paper endpoint.
- Free paper accounts generally receive live IEX stock data.
- You must supply your Alpaca API keys in `.env`.

## Setup

1. Create a virtual environment:
   - Windows:
     `python -m venv .venv`
     `.venv\Scripts\activate`
   - macOS/Linux:
     `python3 -m venv .venv`
     `source .venv/bin/activate`

2. Install dependencies:
   `pip install -r requirements.txt`

3. Copy env file:
   `copy .env.example .env` on Windows
   or
   `cp .env.example .env` on macOS/Linux

4. Fill in your Alpaca keys in `.env`

5. Run:
   `python main.py`

## Risk controls and scheduling defaults
- `STARTING_CASH` now defaults to `100000`.
- `STOP_LOSS_PCT` and `TAKE_PROFIT_RR` enforce SL/TP levels with max risk/reward of 1:3.
- `RISK_PER_TRADE_PCT` caps per-trade risk and cannot exceed 10% of account equity.
- `DAILY_PROFIT_TARGET_PCT=0.08`: once reached, no new entries until next trading day.
- `DAILY_LOSS_LIMIT_PCT=0.08`: once breached, no new entries until next trading day.
- New entries are Monday-Friday during market hours, with entries prioritized during core hours (10:00-15:00 ET).
- Live logs include symbol, price, stop loss, take profit, and TP/SL hit alerts.

## What Codex can add next
- trailing stop logic
- multiple strategies
- dashboard / web UI
- CSV / SQLite logging
- backtesting mode
- Discord / Telegram alerts
