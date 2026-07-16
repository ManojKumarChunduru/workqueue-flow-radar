#!/usr/bin/env bash
# End-to-end demo: simulate, analyze, render the ops packet, score.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1. simulate claims through the workqueue lifecycle =="
wq-radar generate --quiet

echo "== 2. reconstruct journeys and detect routing conflicts =="
wq-radar analyze --quiet

echo "== 3. render the daily ops packet =="
wq-radar report --quiet

echo "== 4. score detection against planted ground truth =="
wq-radar score --quiet

echo
echo "Ops packet: output/wq-daily-ops-packet.xlsx and output/wq-daily-ops-summary.pdf"
