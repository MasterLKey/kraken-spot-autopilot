# What this bot does (and does not)

## Does

- Automate **your own** Kraken **spot** buys/sells via API keys you control.
- Run **DCA** on a schedule (optional dip filter).
- Run a simple **spot grid** inside a price band on one liquid pair.
- Enforce **risk limits**: max order size, max position notional, max daily loss, kill switch.
- Support **paper mode** (simulated fills against live prices) before risking capital.
- Log every fill to **SQLite** and export **CSV** for tax / track record.
- Optionally notify you on **Telegram**.
- Fee-aware **backtest/replay** on historical OHLCV.

## Does not

- Hold or trade anyone else’s funds (no custody, no “managed accounts”).
- Use leverage, futures, perps, or margin (UK retail-friendly by design).
- Guarantee profits or promise returns.
- Give personalised investment advice.
- Withdraw funds (API keys must be trade-only).

## Who it’s for

Solo UK builders who want a personal autopilot first, then optionally productize the software — not tipster signals.

## Phase 2 monetization (chosen default)

**B — Self-hosted bot (users bring their own Kraken API keys); you sell the software / subscription.**

Why B over A (paid Telegram alerts):

- Stays clearly **product-shaped** (software you run yourself) rather than tipster/alert marketing, which is harder under UK financial promotions rules.
- Matches the codebase you already have (Docker + env + risk controls).
- Users keep custody and keys; you never touch their money.
- Natural upgrade path: open-core or paid image + support + strategy packs.

Phase 2 sketch (later, not in this MVP):

1. Harden config UX + first-run wizard.
2. Landing page + Stripe for license / hosted updates.
3. Clear disclaimer: software tool, not advice; user configures strategy and risk.
4. Optional read-only “paper share” of anonymised performance metrics — not trade tips.

Alerts (option A) can still be an add-on **after** the self-host product exists, with carefully non-advisory marketing copy.
