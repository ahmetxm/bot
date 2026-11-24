#!/usr/bin/env bash
# Copy this run's reports / fills / log into out/runs/<utc date>_<run id>/ and the recording into out/recordings/.
set -uo pipefail
cd "$(dirname "$0")/.."
TAG="gha_${GITHUB_RUN_ID:-local}"
RUN_DIR="out/runs/$(date -u +%Y%m%d_%H%M)_${GITHUB_RUN_ID:-local}"
mkdir -p "$RUN_DIR" out/recordings
cp reports/live_paper_*"$TAG"* "$RUN_DIR"/ 2>/dev/null
cp data/live_paper_fills_"$TAG"* data/live_paper_state_"$TAG"* "$RUN_DIR"/ 2>/dev/null
cp logs/live_paper_"$TAG".log "$RUN_DIR"/ 2>/dev/null
gzip -f "$RUN_DIR"/*.log "$RUN_DIR"/*.csv 2>/dev/null
mv data/recordings/*"$TAG"* out/recordings/ 2>/dev/null
ls -la "$RUN_DIR" out/recordings
exit 0
