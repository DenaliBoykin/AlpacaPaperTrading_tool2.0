# Alpaca Paper Trading Bot Starter

This repo is a starter project for Codex to extend.

It:
- streams real-time stock trades from Alpaca
- builds 1-minute candles from trades
- computes a simple moving-average crossover signal
- submits paper market orders to Alpaca paper trading
- keeps the code split into clean modules

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

## What Codex can add next
- stop loss / take profit
- trailing stop logic
- multiple strategies
- dashboard / web UI
- CSV / SQLite logging
- backtesting mode
- market-hours filter
- risk checks
- Discord / Telegram alerts
