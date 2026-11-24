#!/usr/bin/env bash
# Commit out/runs/* to the paper-results branch and refresh SUMMARY.md (needs `permissions: contents: write`).
set -euo pipefail
cd "$(dirname "$0")/.."
ls out/runs/* >/dev/null 2>&1 || { echo "nothing to publish"; exit 0; }
git config user.name "github-actions[bot]"
git config user.email "41898283+github-actions[bot]@users.noreply.github.com"
git fetch --depth=1 origin paper-results:paper-results
git worktree add ../results paper-results
mkdir -p ../results/runs
cp -r out/runs/* ../results/runs/
python tools/summarize_runs.py ../results/runs > ../results/SUMMARY.md
cd ../results
git add -A
git commit -q -m "paper run ${GITHUB_RUN_ID:-local} (${GITHUB_REF_NAME:-?})" || exit 0
for i in 1 2 3 4 5; do
  if git push origin HEAD:paper-results; then exit 0; fi
  git fetch --depth=1 origin paper-results && git rebase origin/paper-results || true
  sleep 5
done
exit 1
