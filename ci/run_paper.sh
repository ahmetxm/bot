#!/usr/bin/env bash
# One paper-test run on a CI runner (called by .github/workflows/paper.yml). No real orders, no keys.
# Env: MINUTES (default 320), SETTLE (max settlement wait, default 15), RECORD (true/false, default true), GITHUB_RUN_ID (tag).
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="gha_${GITHUB_RUN_ID:-local}"
MINUTES="${MINUTES:-320}"
export PYTHONUNBUFFERED=1

pip install -q -r requirements.txt
python tests/test_strategy_replica.py

echo "--- network check (which feeds are reachable from this runner)"
for u in "https://data-api.binance.vision/api/v3/ping" "https://api.binance.com/api/v3/ping" \
         "https://api.exchange.coinbase.com/products/BTC-USD/ticker" \
         "https://gamma-api.polymarket.com/markets?limit=1" "https://clob.polymarket.com/time"; do
  echo "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$u" || true) $u"
done

REC=""
if [ "${RECORD:-true}" = "true" ]; then REC="--record"; fi
python live_paper.py --minutes "$MINUTES" --settle-wait "${SETTLE:-15}" --variants variants/gha.json \
  --tick 0.25 --interim-report 30 --tag "$TAG" $REC
