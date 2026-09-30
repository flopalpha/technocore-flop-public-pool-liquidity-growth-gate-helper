# FLOP Public Pool Liquidity-Growth Gate Helper

Observational screening helper for public FLOP pool lists.
It shows why earliest-first 15-minute bucketing can mislead on dust pools
and checks whether liquidity grows with price.

This tool is read-only and local. It handles only user-supplied public
snapshots. It performs no signing, no network posting, and no trading.
Output is screening assistance only, not financial advice.
Accuracy depends on input data quality and local threshold tuning.

## What it does

- Imports public CSV or JSON pool snapshots with timestamp, liquidity, price
- Compares earliest-first ranking versus liquidity-weighted ranking
- Flags dust or flat pools with minimum liquidity and delta thresholds
- Scores liquidity-growth versus price-trend correlation
- Exports auditable JSON and Markdown reports with checksum and params

## Install

No third-party packages. Python 3.9+ with standard library only.

Copy this folder and run:

```
python -m unittest test_gate -v
python cli.py --help
```

## Input format

CSV header (case insensitive):

```
pool_id,timestamp,liquidity,price
ALPHA,1700000000,5000,1.02
ALPHA,1700000900,6500,1.10
BETA,1700000000,20,0.50
```

- pool_id: string id
- timestamp: unix seconds, integer
- liquidity: float, zero or more
- price: float, zero or more

JSON is a list of objects with the same fields:

```
[
  {"pool_id": "ALPHA", "timestamp": 1700000000, "liquidity": 5000, "price": 1.02},
  {"pool_id": "ALPHA", "timestamp": 1700000900, "liquidity": 6500, "price": 1.10}
]
```

A JSON object with a snapshots list is also accepted.
Bad rows are skipped. Negative liquidity or price rows are skipped.

## Usage

```
python cli.py samples.csv --json-out report.json --md-out report.md
python cli.py samples.json --window 15 --min-liquidity 1000 --min-delta 100
python cli.py samples.csv --pass-score 60 --review-score 40 --top-n 5
```

Options:

- --window: bucket size in minutes, default 15
- --min-liquidity: dust size threshold, default 1000
- --min-delta: dust growth threshold, default 100, use 0 to disable delta check
- --pass-score: PASS threshold 0 to 100, default 60
- --review-score: REVIEW threshold 0 to 100, default 40
- --top-n: comparison depth, default 5

## How scoring works

For each pool, sorted by time:

- liq_change_pct = (last - first) / first * 100
- price_change_pct = (last - first) / first * 100
- correlation = Pearson(liquidities, prices), 0 if flat or short
- liq_c = clamp(liq_pct / 100, -1, 1)
- price_c = clamp(price_pct / 100, -1, 1)
- score = (liq_c + price_c + corr) / 3 mapped to 0..100

Gate:

- FAIL if dust flagged
- PASS if score >= pass-score and liq_change > 0 and corr > 0.2
- REVIEW if score >= review-score and liq_change > 0
- else FAIL

Bucket comparison lists earliest-seen top-N versus max-liquidity top-N
and counts low-liquidity entries in the earliest list.

## Reports

JSON report holds checksum, params, snapshot count, pool count,
bucket comparison, and ranked pools with reasons.

Markdown report holds the same as readable tables.
Checksum is sha256 of canonical sorted snapshot JSON.

## Tuning

Start with min-liquidity near your dust line, for example 500 to 2000.
Set min-delta to a small growth amount, or 0 to check size only.
Raise pass-score to be stricter, lower it to explore.

## Limits

Public data only. No verification of chain truth. No price prediction.
Small samples give weak correlation. Tune locally and keep inputs.
