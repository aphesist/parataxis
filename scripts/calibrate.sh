#!/usr/bin/env bash
# Calibration of N on the 12 probe tasks (PREREGISTRATION.md, "calibrating n").
#
# The repeat calibration (b.6) buys the plans first without a pod (python -m parataxis.run ... --plans-only),
# then runs PASSES="L1 La2 La2b La4 La8" REPLAY_LOG=<plans log> SKIP_CHECKS=1 PASS_HOURS_BY="...".
#
# One pod for the whole session, under the watchdog; always terminated on exit, never stopped.
# The harness and the Docker verifier run here and call the pod's vLLM over HTTPS (parataxis.pod exec
# passes the endpoint and its key in the child's environment only). Passes, in priority order, each
# into its own log under runs/calib/: La at N=8 (buys the Opus plans), L1, La at N=4, La at N=2 (plans
# replayed at zero tokens). Before each pass the GPU ledger and the remaining lifetime are checked; a
# pass that cannot finish inside the limits is not started.
set -euo pipefail
NAME=${NAME:-parataxis-calib-$(date -u +%Y%m%dT%H%M%S)}
MAX_HOURS=${MAX_HOURS:-3.5}
GPU_CAP=${GPU_CAP:-3.0}
PLANNER_CAP=${PLANNER_CAP:-0.80}
MAX_MODEL_LEN=${MAX_MODEL_LEN:-98304}
PASS_HOURS=${PASS_HOURS:-0.75}   # the most a pass is expected to take; no pass starts with less lifetime left
# per-pass estimates override PASS_HOURS, e.g. "L1=0.6 La2=1.3 La2b=1.3 La4=0.9 La8=0.7"
read -r -a PASS_HOURS_BY <<< "${PASS_HOURS_BY:-}"
REPLAY_LOG=${REPLAY_LOG:-}       # plans bought beforehand (--plans-only): every La pass replays them
SKIP_CHECKS=${SKIP_CHECKS:-}     # 1: skip the window re-check and the local recount (already done)
OUT=${OUT:-results/local-calib}
RUNS=${RUNS:-runs/calib}
PASSES=${PASSES:-"La8 L1 La4 La2"}
TASK_LIMIT=${TASK_LIMIT:-}       # only the first N tasks of each pass (dry runs)
mkdir -p "$OUT" "$RUNS"
read -r -a POD_ARGS <<< "${POD_ARGS:-}"
pod() { python -m parataxis.pod "${POD_ARGS[@]}" "$@"; }
COMMON=(--benchmark swepro --split lanes-probe --lanes-splits results/swepro-lanes/splits.json
        --client parataxis.local:LocalRoleClients --no-log-contents --max-image-gb 26 --max-lanes 8)

pid=$(pod create --name "$NAME" --max-hours "$MAX_HOURS" --cap-usd "$GPU_CAP" --max-model-len "$MAX_MODEL_LEN" \
      --assumed-rate "${ASSUMED_RATE:-0.69}" \
      | python -c 'import json,sys; print(json.load(sys.stdin)["pod"])')
start=$(date +%s)
wd=""
cleanup() {
  pod terminate --pod "$pid" >/dev/null || echo "TERMINATE FAILED for pod $pid: terminate it in the RunPod console" >&2
  [ -n "$wd" ] && kill "$wd" 2>/dev/null || true
  pod spend
}
trap cleanup EXIT
pod watchdog --pod "$pid" --idle-minutes 15 --max-hours "$MAX_HOURS" --cap-usd "$GPU_CAP" >/dev/null &
wd=$!
pod wait --pod "$pid" --timeout-s 2400
pod smoke --pod "$pid" --out "$OUT/smoke-${MAX_MODEL_LEN}.json" || { echo "smoke failed at max_model_len $MAX_MODEL_LEN"; exit 4; }
# the approved re-check of max_model_len: one ~80K prompt alone, then 8 lanes of ~22K at once, no preemption
if [ -z "$SKIP_CHECKS" ]; then
  pod window --pod "$pid" --out "$OUT/window-${MAX_MODEL_LEN}.json" --single-tokens "${WINDOW_SINGLE:-80000}" \
    || { echo "window check failed at max_model_len $MAX_MODEL_LEN: restart with a smaller MAX_MODEL_LEN"; exit 5; }
  pod exec --pod "$pid" -- sh -c 'python scripts/fit_symbol_lanes.py --offline --count-local "$PARATAXIS_VLLM_URL" --out '"$OUT"' >/dev/null' \
    || echo "count-local recount failed (continuing)"
fi

pass_hours() {  # the expected hours of pass $1
  local kv
  for kv in "${PASS_HOURS_BY[@]}"; do [ "${kv%%=*}" = "$1" ] && { echo "${kv#*=}"; return; }; done
  echo "$PASS_HOURS"
}
can_run() {  # enough lifetime and GPU budget left for pass $1?
  local now left_h spent need
  now=$(date +%s)
  need=$(pass_hours "$1")
  left_h=$(python -c "print(${MAX_HOURS} - ($now - $start) / 3600)")
  spent=$(pod spend | python -c 'import json,sys; print(json.load(sys.stdin)["usd"])')
  python -c "import sys; sys.exit(0 if ($left_h >= $need and $spent + $need * 0.69 <= $GPU_CAP) else 1)" \
    || { echo "stop before pass $1 (needs ${need} h): ${left_h} h left, \$${spent} spent"; return 1; }
}

order_fwd=$(python -c "print(' '.join(open('results/local/tasks-probe.txt').read().split()))")
order_rev=$(python -c "print(' '.join(reversed(open('results/local/tasks-probe.txt').read().split())))")
n=0
for p in $PASSES; do
  can_run "$p" || break
  n=$((n + 1))
  if [ $((n % 2)) -eq 1 ]; then order=$order_fwd; else order=$order_rev; fi  # alternate: reuse cached images
  printf '%s\n' $order > "$RUNS/order-$p.txt"
  case "$p" in
    La8) args=(--lanes --local --concurrency 8 --arms La --budget-usd "$PLANNER_CAP") ;;
    La4) args=(--lanes --local --concurrency 4 --arms La --budget-usd "$PLANNER_CAP") ;;
    La2|La2b) args=(--lanes --local --concurrency 2 --arms La --budget-usd "$PLANNER_CAP") ;;
    L1)  args=(--local --arms L1 --budget-usd "$PLANNER_CAP") ;;
  esac
  replay=""
  [ "$p" = La4 ] || [ "$p" = La2 ] && replay="$RUNS/La8.jsonl"
  if [ -n "$REPLAY_LOG" ] && [ "$p" != L1 ]; then replay="$REPLAY_LOG"; fi
  echo "pass $p: start $(date -u +%H:%M:%S)"
  PARATAXIS_PLAN_REPLAY="$replay" pod exec --pod "$pid" -- python -m parataxis.run "${COMMON[@]}" "${args[@]}" \
    --task-file "$RUNS/order-$p.txt" ${TASK_LIMIT:+--limit "$TASK_LIMIT"} --log "$RUNS/$p.jsonl" > "$RUNS/$p.out" 2>&1 \
    || echo "pass $p ended with exit $? (see $RUNS/$p.out)"
  echo "pass $p: end $(date -u +%H:%M:%S)"
done
