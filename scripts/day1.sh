#!/usr/bin/env bash
# Day 1: one RTX 5090 pod, the smoke test, terminate (PREREGISTRATION.md, "day 1").
# The pod is always terminated on exit, never stopped; a watchdog terminates it if idle or past its
# lifetime. Nothing here prints the per-pod vLLM key. A dry run against fakes:
#   POD_ARGS="--api http://127.0.0.1:8100/v2 --url http://127.0.0.1:8000" scripts/day1.sh
set -euo pipefail
NAME=${NAME:-parataxis-day1-$(date -u +%Y%m%dT%H%M%S)}
MAX_HOURS=${MAX_HOURS:-1.5}
OUT=${OUT:-results/local-smoke/smoke.json}
read -r -a POD_ARGS <<< "${POD_ARGS:-}"
read -r -a CREATE_ARGS <<< "${CREATE_ARGS:-}"
pod() { python -m parataxis.pod "${POD_ARGS[@]}" "$@"; }

pid=$(pod create --name "$NAME" --max-hours "$MAX_HOURS" "${CREATE_ARGS[@]}" \
      | python -c 'import json,sys; print(json.load(sys.stdin)["pod"])')
wd=""
cleanup() {
  pod terminate --pod "$pid" >/dev/null || echo "TERMINATE FAILED for pod $pid: terminate it in the RunPod console" >&2
  [ -n "$wd" ] && kill "$wd" 2>/dev/null || true
  pod spend
}
trap cleanup EXIT
pod watchdog --pod "$pid" --idle-minutes "${IDLE_MINUTES:-15}" --max-hours "$MAX_HOURS" >/dev/null &
wd=$!
pod wait --pod "$pid" --timeout-s "${READY_TIMEOUT_S:-2400}"
status=0
pod smoke --pod "$pid" --out "$OUT" || status=$?
exit "$status"
