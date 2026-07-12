# Kraken Spot Autopilot

Personal UK-friendly **spot** trading bot for Kraken: DCA + optional range/grid, paper mode, risk limits, Telegram alerts, SQLite trade journal, fee-aware backtests.

> Not financial advice. Trade only capital you can lose. Spot only — no leverage/derivatives.

## Quick start (paper)

```powershell
cd c:\projects\crypto
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env: BOT_MODE=paper, STRATEGY=dca, DCA_INTERVAL_SECONDS=60 for a fast demo
python -m bot ticker
python -m bot run
```

In another terminal:

```powershell
python -m bot status
python -m bot export
python -m bot halt --reason "pause"
python -m bot halt --clear
```

## Live checklist (Week 2+)

1. Open Kraken (UK), deposit GBP.
2. Create an API key with **Create & modify orders** only — **disable Withdrawal**.
3. Set in `.env`:
   - `BOT_MODE=live`
   - `KRAKEN_API_KEY` / `KRAKEN_API_SECRET`
   - tiny `DCA_QUOTE_AMOUNT` (e.g. 15)
   - risk caps you are comfortable with
4. Optional Telegram: create a bot via @BotFather, get chat id, set `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`.
5. Run paper for 48h first, then live.

## Grid

```env
STRATEGY=both
GRID_ENABLED=true
GRID_LOWER_PRICE=90000
GRID_UPPER_PRICE=110000
GRID_LEVELS=8
GRID_QUOTE_PER_LEVEL=20
```

Backtest (public market data, no keys needed):

```powershell
python -m bot backtest --strategy grid --timeframe 1h --limit 500 --band-pct 10 --capital 1000
python -m bot backtest --strategy dca --every 24
```

## Docker

```powershell
.\start.ps1
# or
docker compose up -d --build
```

Data persists in the `bot_data` volume (`journal.sqlite3`, kill switch file, CSV exports under `/app/data`).

## Home lab (Proxmox)

Secrets stay in a **local `.env` on the LXC** for now (not Infisical).

```powershell
cd terraform
terraform init
terraform apply
# Find CT IP in Proxmox UI, then:
scp -i $env:USERPROFILE\.ssh\octo_scrape_deploy scripts\provision.sh root@<IP>:/root/provision.sh
ssh -i $env:USERPROFILE\.ssh\octo_scrape_deploy root@<IP> "bash /root/provision.sh"
scp -i $env:USERPROFILE\.ssh\octo_scrape_deploy .env root@<IP>:/opt/kraken-spot-autopilot/.env
ssh -i $env:USERPROFILE\.ssh\octo_scrape_deploy root@<IP> "chmod 600 /opt/kraken-spot-autopilot/.env; bash /opt/kraken-spot-autopilot/start.sh"
```

## CLI

| Command | Purpose |
|---------|---------|
| `python -m bot run` | Main loop |
| `python -m bot status` | Fills / PnL / kill switch |
| `python -m bot export` | CSV trade journal |
| `python -m bot halt` / `--clear` | Kill switch |
| `python -m bot ticker` | Public price check |
| `python -m bot backtest` | Fee-aware replay |

## Project layout

```
bot/
  config.py          # env settings
  exchange/kraken.py # ccxt + retries
  engines/dca.py     # DCA
  engines/grid.py    # spot grid
  risk.py            # caps + kill switch
  paper.py           # simulated fills
  journal.py         # SQLite + CSV
  backtest.py        # OHLCV replay
  notify.py          # Telegram
  main.py            # CLI + loop
```

See [WHAT_IT_DOES.md](WHAT_IT_DOES.md) for product boundaries and Phase 2 monetization choice.
