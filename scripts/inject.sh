#!/usr/bin/env bash
set -euo pipefail
scenario="${1:-checkout_latency}"
python3 chaos/chaosctl.py inject "$scenario"
