# repeat calibration: wide fan-out on the probe tasks (2026-11-13)

> at 6–8 lanes per task (the lane count from the contract units), which n gives the most test-gated tok/s, and do L1's edits and the output caps now meet the pre-registered checks?

> **status:** partial. the plans were bought, and L1, La2, La2b and 7 of La4's 10 tasks ran. La8 did not run: the driver hit the 2-hour limit on a background command, and its exit trap terminated the pod. no limit was crossed.
>
> L1 still fails format compliance (29% of gated edits, threshold 20%) and output caps (20% of requests at 16K, limit 10%). by the pre-registered rule n = 2, but it is the only n with a complete pass.

- **plans:** 10 of the 12 probe plans, bought without a pod (`--plans-only`, [`logs/plans.jsonl`](logs/plans.jsonl)) for $0.7928.
  - the budget guard refused the other 2 (ansible `d72025be`, openlibrary `25858f9f`), because the next request's worst case passed the $1.80 cumulative calibration cap.
  - the calibration set is the 10 tasks with plans ([`tasks-10.txt`](tasks-10.txt)).
  - every La pass replayed the plans with `PARATAXIS_REPLAY_ONLY=1`: 0 planner tokens, $0.00, checked in each log.
- **sessions:**
  - **session 1:** pod `0s48fh8l90sbwl`, 06:39–07:08 utc. L1 ran ([`logs/L1-session1.jsonl`](logs/L1-session1.jsonl)). the La passes stopped at once: the budget guard checked the planner request's worst case before the replay could answer it. then my wrapper's `reap` ended the session.
  - **session 2:** pod `cukpo2ul52vj8e`, 07:19–09:21 utc. it ran the passes below after the fixes (b.5 item 13 and replay-only).
- **serving:** as in part b. 0 preemptions, peak kv-cache use 35%, mtp acceptance 0.88, prefix-cache hits 50%.

## results (session 2, the 10 tasks)

| pass | tasks | solved | shadow solved | test-gated tok/s | raw tok/s | requests at the output cap | gated edits failing | aggregate tok/s iqr / median |
|---|---|---|---|---|---|---|---|---|
| L1 (16K, units format, P1) | 10 | 4 | — | 5.1 [0.8, 13.4] | 128 | 5 / 25 (20%) at 16K | 5 / 17 (29%) | 0.26 |
| La, n = 2 | 10 | 2 | 1 | 5.5 [0.0, 17.9] | 180 | 2 / 109 at 8K | 7 / 115 (6%) | 0.23 |
| La, n = 2 (repeat) | 10 | 1 | 1 | 1.8 [0.0, 7.0] | 191 | 1 / 119 | 4 / 126 (3%) | 0.27 |
| La, n = 4 (partial) | 7 | 1 | 1 | 5.2 (estimated) | 210 | 5 / 102 | 5 / 94 (5%) | 0.38 |

- **test-gated tok/s:** tokenized with the pod's tokenizer, except La4 (characters / 3, finished after the pod ended).
- **lanes realised:** k = 6, 7, 7, 7, 8, 8, 8, 8, 8, 8; median 8.
- **lane prompts against the 98,304-token window:** La2 lane inputs had a median of 6.6K tokens, p90 12.9K and max 18.7K; La4's max was 25.2K. L1 inputs: median 21.4K, max 41.4K.
- **format compliance by cause:**
  - L1: 4 SEARCH text not found, 1 no block applied, 0 tool calls (5 of 19 replies in session 1). 15 UNIT blocks added new functions.
  - La lanes: almost all SEARCH text not found. tool calls: 0 in La2 and La2b, 1 reply plus 1 repair reply in La4.
- **truncated first replies:** L1 5 of 17; lanes 1–5 per pass.
- **coordination failures:**

  | | La2 | La2b | La4 (7 tasks) |
  |---|---|---|---|
  | wasted lane | 21 | 22 | 20 |
  | scope violation | 10 | 18 | 15 |
  | overwrite (shadow) | 12 | 14 | 8 |
  | ignored correction | 11 | 11 | 13 |
  | unlisted unit | 5 | 7 | 5 |
  | unattributable | 4 | 6 | 6 |
  | interface mismatch | 4 | 5 | 0 |

- **noise (rule 5, La2 against La2b, the same plans):**
  - aggregate throughput agrees: medians 216 and 235 tok/s; iqr / median 0.23 and 0.27, the second just over 0.25;
  - solves (2 and 1) and test-gated tok/s (5.5 and 1.8) differ widely between the two runs.
- **for comparison,** the first calibration on the same 10 tasks (k of 1–4, search format): L1 4, La8 3, La8-shadow 3.

## cost

| item | amount |
|---|---|
| session 1 (ledger) | 0.496 h, $0.342; billed $0.300 |
| session 2 (ledger) | 2.000 h, $1.380; billed $1.432 |
| all pods so far (ledger) | $3.441 of the $10 cap |
| balance | $11.522 |
| planner: 10 plans | $0.7928 (calibration total $1.587 of $1.80); replays $0 |

- **no pod left:** after the terminate and `parataxis.pod reap`, `GET /v2/pods` listed none and `currentSpendPerHr` was 0.

## files

- `logs/`: the hash-chained logs (verified), the plans, and each pass's task order.
- `analysis/`: `scripts/analyze_local.py` per pass, tokenized and `-est`.
- `calibration.json`: `scripts/calib_summary.py --dir results/local-calib3 --preemptions 0 --l1-cap16 --passes "La2=La2 La2b=La2b La4=La4 L1=L1"`.
- `ledger.jsonl`: both pods.
- `metrics.jsonl.gz`: vllm `/metrics` each minute in session 2.
- `smoke-98304.json`: the smoke test.

none holds a key.
