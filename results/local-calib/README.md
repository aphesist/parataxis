# calibration: n on the 12 probe tasks, one rtx 5090 (2026-11-13)

> at which lane concurrency n does local La give the most test-gated tok/s on the probe tasks, and do L1's edits and the output caps meet the pre-registered checks?

> **status:** done, inside every limit. the choice rule gives **n = 2**, but every n solved 4 of 12 and the tok/s intervals overlap. two pre-registered checks failed on **L1**:
> - **format compliance:** 50% of L1's gated edits failed to parse or apply, against a 20% threshold;
> - **output caps:** 23% of L1's requests hit the 8K cap, against a 10% limit.
>
> also, La2's throughput spread is over the noise limit (stop rule 5). the pre-registration sends both back to calibration, so part b is a proposal (PREREGISTRATION.md, "part b"). the main run has not started.

- **run:** `scripts/calibrate.sh` (create, watchdog, wait, smoke, window check, local recount, La8), then the passes resumed by hand after two interruptions (see "incidents"). cost limits: gpu ≤ $3.00 for the session, pod lifetime 3.5 h, 15-minute idle terminate, planner ≤ $1.00 with the 1.2 pre-flight margin.
- **pod:** `eq4o4ucbibfpx8`, runpod community cloud, `NVIDIA GeForce RTX 5090`, $0.69/h, image `vllm/vllm-openai:v0.33.0`, `max_model_len` 98304. otherwise the day-1 serving configuration. vllm served 260.7 s after create.
- **planner:** opus 5.5, low effort. La8 bought the 12 plans for $0.7942. La4 and La2 replayed them at zero tokens (`PARATAXIS_PLAN_REPLAY`, events marked `replay: true`).
- **harness and verifier:** run here, calling the pod's vllm over https (verifier option b). the logs hold no repository file contents (`--no-log-contents`).

## results

test-gated tok/s are ratios of sums over the 12 tasks, with a 95% bootstrap ci (seed 20261113).
- **tokenized:** counted with the model's tokenizer through vllm `/tokenize`, possible only while the pod lived. La2 finished as the pod was terminated.
- **estimated:** characters / 3, computed for every pass so they compare on one count. the estimate runs about 1.2× the tokenized value.

| pass | solved | shadow solved | test-gated tok/s (tokenized) | test-gated tok/s (estimated) | raw tok/s | requests at the 8K cap | gated edits failing to parse or apply | aggregate tok/s iqr / median |
|---|---|---|---|---|---|---|---|---|
| La, n = 8 | 4 / 12 | 3 / 12 | 10.8 [1.6, 25.2] | 12.8 [1.6, 30.3] | 113 | 1 / 48 (2%) | 6 / 56 (11%) | 0.23 |
| La, n = 4 | 4 / 12 | 5 / 12 | 9.7 [1.1, 25.8] | 11.4 [1.1, 30.7] | 116 | 3 / 42 (7%) | 4 / 54 (7%) | 0.25 |
| La, n = 2 | 4 / 12 | 4 / 12 | n/a | 17.4 [2.4, 41.0] | 129 | 0 / 44 (0%) | 3 / 56 (5%) | **0.44** |
| L1 | 4 / 12 | — | 9.0 [1.4, 20.8] | 10.9 [1.6, 25.6] | 153 | **8 / 35 (23%)** | **11 / 22 (50%)** | 0.13 |

- **choice of n (rule as pre-registered):** the most test-gated tok/s with no preemption is n = 2. no other n solved a task more, so **n = 2**.
  - the difference is not a measured effect: the cis overlap almost entirely.
  - the planner chose 1 or 2 lanes on 10 of the 12 tasks (lane counts 1: 2, 2: 8, 3: 1, 4: 1), so n above 2 rarely binds. La2's shorter total task time without the verifier (505 s against 777 s and 779 s) is mostly run-to-run variance at temperature 0.7.
- **preemptions:** 0 over the whole session (`vllm:num_preemptions_total` is cumulative from vllm's start and read 0 at the end). peak kv-cache use 43%.
- **mtp acceptance:** 0.89 (accepted / drafted tokens from 02:25 to 03:54 utc).
- **prefix cache:** 974,400 hits of 3,163,405 queried tokens since start (31%).
- **coordination failures (La):**

  | | n = 8 | n = 4 | n = 2 |
  |---|---|---|---|
  | wasted lane | 9 | 5 | 7 |
  | interface mismatch | 6 | 4 | 7 |
  | ignored correction | 4 | 1 | 4 |
  | unattributable | 3 | 4 | 4 |
  | scope violation | 0 | 1 | 1 |

- **10-minute task cap:** no task reached it.
- **primary comparison on the probe set** (descriptive only; n = 12): La − La-shadow was +1, −1 and 0 tasks at n = 8, 4 and 2. exact mcnemar p = 1.0 each time.

### why L1 fails the checks

L1 is one worker on the whole task. it sees whole files (median input 21,084 tokens, max 41,149) and must echo exact SEARCH text.
- **first responses:** of its 23 submissions, 7 first responses were cut off at 8K. some were narration ("let me check what was already sent…") despite thinking being off. 4 more did not parse.
- **gated edits that failed:** 5 applied no block, 5 had SEARCH text not found in the file, 1 had a missing path.
- **La, for contrast:** lanes see symbol-level views (median input 12.7K–15.5K) and stay within both limits.

## incidents

1. **L1's stream dropped mid-response** at its third task (`ConnectionResetError` through the pod proxy). The pass stopped after 2 tasks.
   - fixed in `06b8141`: a lane request is sent again when its stream drops;
   - the remaining 10 tasks ran as `L1b` after La8, keeping the approved priority (L1 before La4 and La2);
   - no stream retry fired in any later pass.
2. **the container restarted at about 02:38 utc**, killing every local process (driver, watchdog, the L1b pass). the pod kept running.
   - a new watchdog took over at once, with the same end time (`--max-hours 2.41`, 15 minutes idle, $3 cap);
   - the 5 unfinished L1 tasks ran as `L1c`, then La4 and La2;
   - the task in flight was rerun from scratch.
3. **code:** La8 and `L1` ran on `c65db79`; L1b, L1c, La4 and La2 on `06b8141`. the only difference is the stream retry, which never fired.
4. **metrics logging** started at 02:25, after La8 began. the preemption count is cumulative, so it covers the whole session; mtp acceptance covers 02:25 to the end.

## cost

| item | amount |
|---|---|
| pod hours (ledger, create to terminate) | 2.334 h |
| gpu, ledger estimate | $1.6105 |
| gpu, billed by runpod (balance $14.915 → $13.302) | $1.613 |
| gpu so far, both pods (ledger) | $1.719 of the $10 cap |
| planner (La8, 12 plans) | $0.7942 of the $1.00 cap; pre-flight expected $0.748 |

- **no pod left:** after the terminate and `parataxis.pod reap`, `GET /v2/pods` listed no pod and runpod's `currentSpendPerHr` was 0.

## main-run planner estimate

`results/local-calib/preflight-main.json`: the lane pre-flight on the 37 main tasks.
- **planner input:** counted with anthropic `count_tokens` on the real symbol-lane planner prompts.
- **planner output:** 1,199 tokens per plan (the measured median of the api study).
- **result:** expected **$2.389**, $2.867 with the 1.2 margin.

calibration's real planner spend was 6% above its pre-flight ($0.794 against $0.748), which puts the main run at about $2.53.

## contamination check

`task-dates.json` holds the committer date of each task's base commit, for the 37 main and 12 probe tasks. they come from shallow fetches of the public repositories.
- **range:** 2019-08-01 to 2025-06-04 (by year: 2019 2, 2020 7, 2021 4, 2022 11, 2023 14, 2024 6, 2025 5).
- **the model:** qwen3.8-27b's card states no training cutoff. its citation dates the model to august 2026, and it reports a swe-bench pro score of 61.7 (claude code harness).
- **conclusion:** every task predates the model, so contamination cannot be excluded.
  - it affects La and La-shadow alike: both merge the same lane outputs.
  - it bears most on comparing local solve rates with the api study's.

## files

- `logs/`:
  - the hash-chained logs (`L1`, `L1b`, `L1c`, `La8`, `La4`, `La2`), each verified with contraprova's `EventLog.verify`;
  - each pass's task order.

  sha256:
  - `L1` d0cd04a6…, `L1b` 2b4a6aea…, `L1c` adc48c11…;
  - `La8` 25e9df16…, `La4` fe96b668…, `La2` 565166a0….
- `analysis/<pass>.json`: `scripts/analyze_local.py` with the local tokenizer (La8, La4, L1). La2's copy is the estimated one.
- `analysis/<pass>-est.json`: the same, with tokens estimated.
- `calibration.json`: `scripts/calib_summary.py --dir results/local-calib --preemptions 0`, holding the per-pass checks and the choice of n.
- `hashes.json`: `scripts/freeze_hashes.py`, holding the code, the contraprova pin and the prompt hashes at `dad9da4` (src identical to `06b8141`).
- `smoke-98304.json`, `window-98304.json`: the smoke test and the approved `max_model_len` re-check at 98304.
- `fit-local.json`: the fit study recounted with the local tokenizer.
- `ledger.jsonl`: the pod's create, ready and terminate events.
- `metrics.jsonl.gz`: vllm `/metrics` once a minute from 02:25.
- `preflight-main.json`: the main-run planner pre-flight.
- `task-dates.json`: the contamination dates.

none holds a key: every log was searched for both pods' keys.
