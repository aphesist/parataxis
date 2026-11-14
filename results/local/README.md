# the local track: an exploratory result (2026-11-13)

> on one rented rtx 5090, do parallel local lanes under contracts and a test-gated merge solve more swe-bench pro tasks than an ungated merge of the same lane outputs, and how many test-passing tokens per second does that give?

> **status:** stopped after calibration by the owner's decision (option a), and paused. no main run. everything below is **exploratory and descriptive**, from 10–12 probe tasks; nothing here claims significance.
>
> on these tasks the local lanes rarely beat the ungated merge. pooled over both plan shapes, La and La-shadow each won 4 tasks the other lost. the cloud api study had 8 to 0. with 6–8 lanes per task, aggregate throughput stayed flat at about 220–240 tok/s whatever the concurrency.

- **setup:** qwen3.8-27b in nvfp4 with mtp (`sakamakismile/Qwen3.8-27B-MTP-NVFP4`), stock vllm v0.33.0 (pre-registered fallback 2), fp8 kv cache, prefix caching, `max_model_len` 98304, on one runpod community rtx 5090 at $0.69/h.
- **harness:** contraprova's swe-bench pro harness and docker verifier ran outside the pod and called vllm over https. an opus 5.5 planner (low effort) planned the lanes; lanes and repairs were local, with no cloud escalation.
- **protocol:** [PREREGISTRATION.md](../../PREREGISTRATION.md) part a. part b was proposed and never frozen (see "deviations").
- **evidence:**
  - [local-smoke](../local-smoke/README.md): day 1;
  - [local-calib](../local-calib/README.md): first calibration, narrow plans;
  - [local-calib3](../local-calib3/README.md): repeat calibration, wide plans, with the [power note](../local-calib3/power-note.md);
  - [local-calib4](../local-calib4/README.md): its completion.

## throughput

- **smoke test** (day 1, one run of each configuration, no repeats):
  - short streams (512 tokens): 116 tok/s at 1 stream, 849 at 8, 917 at 16. the viral demo this project started from showed about 665–700 tok/s for 8 lanes on the same card and model;
  - 8 long streams (~14.6K-token prompts, 1K outputs): 288 tok/s with 0 preemptions;
  - mtp acceptance 0.71 on day 1, 0.88–0.89 under calibration load.
- **real lanes at k ≈ 8** (the repeat calibration, 10 tasks; aggregate = decode tokens per second while at least one lane runs):

  | lanes at once (n) | aggregate tok/s, median [iqr] | per-request tok/s, median | tail share | preemptions |
  |---|---|---|---|---|
  | 2 | 216 [189, 240] | 129 | 0.47 | 0 |
  | 2 (repeat) | 235 [188, 250] | 121 | 0.28 | 0 |
  | 4 | 217 [200, 294] | 102 | 0.81 | 0 |
  | 8 | 238 [211, 274] | 69 | 0.84 | 3 (peak kv 80%) |

  - **aggregate throughput is flat across n** while the rate per lane falls about 1/n: more lanes at once buy no throughput here.
  - **the likely reasons:**
    - **prefill:** lane prompts are long (median ~6.6K tokens, p90 ~13K), so prefill, not decode, fills much of each round;
    - **idle gpu:** between rounds the merge, the gates and the docker verifier run on the harness side while the gpu idles. the tail share rises to 0.8 at n of 4 and 8.

    the day-1 short-stream sweep shows the card itself scales; the workload does not keep it busy.
  - **n = 8 preempted** at `max_model_len` 98304, so the pre-registered choice rule excludes it; the rule gives n = 2.
- **test-gated tok/s** (tokens of the shipped diff on solved tasks, per second of task time): L1 5.1; La at n = 2 5.5 and 1.8 in two runs of the same plans. the two runs show it varies more between runs than with n at this size.

## correctness on the calibration tasks

solved out of the tasks run. narrow plans: the first calibration, 12 probe tasks, SEARCH/REPLACE edits, the planner choosing 1–4 lanes. wide plans: the repeat calibration, the 10 probe tasks whose plans were bought, symbol-unit edits, the kernel packing one lane per listed change (k 6–8, median 8).

| plan shape | pass | tasks | La solved | La-shadow solved |
|---|---|---|---|---|
| narrow (k 1–4) | n = 8 | 12 | 4 | 3 |
| narrow | n = 4 | 12 | 4 | 5 |
| narrow | n = 2 | 12 | 4 | 4 |
| wide (k 6–8) | n = 2 | 10 | 2 | 1 |
| wide | n = 2 (repeat) | 10 | 1 | 1 |
| wide | n = 4 | 10 | 1 | 1 |
| wide | n = 8 | 10 | 0 | 1 |

| arm | tasks | solved |
|---|---|---|
| L1, narrow calibration (SEARCH/REPLACE, 8K) | 12 | 4 |
| L1, units format, 16K (first repeat session) | 10 | 2 |
| L1, units format, 16K, no-tools prompt and tool-call stop | 10 | 4 |

- **pooled La vs La-shadow discordance** (task runs where exactly one of the two solved):

  | | runs | La only | shadow only |
  |---|---|---|---|
  | wide | 40 | 2 | 2 |
  | narrow | 36 | 2 | 2 |
  | cloud api study (haiku lanes, opus planner, 37 tasks) | 37 | 8 | 0 |

  the local model solves few tasks either way, so the governed and the ungated merges rarely disagree.
- **wide plans did worse than narrow plans** on the same tasks: the first calibration's La solved 3 of these 10 (n = 8), and the wide passes 0–2.

## the decomposition finding

why did wide fan-out solve fewer tasks? clash counts per task run in the wide passes (governed merges only):

| clash kind | per run when solved | per run when failed | per run, tasks narrow plans solved and wide plans lost |
|---|---|---|---|
| wasted lane (no change) | 2.2 | 2.2 | 2.6 |
| scope violation (edit outside the lane's units, undone) | 0.8 | 1.7 | 2.2 |
| unlisted unit (edit in a unit no lane owns, undone) | 0.0 | 0.7 | 1.2 |
| interface mismatch | 0.0 | 0.4 | 0.8 |
| ignored correction (a repaired lane repeats itself) | 0.0 | 1.5 | 1.0 |

- **what it points to:** a decomposition problem, not a throughput problem.
  - **scope violations and unlisted units** are associated with failures. a change needs edits outside the units its lane owns, or in units no lane owns, and the span scope gate undoes them. with 6–8 lanes on 1–3 files, the function a lane must touch is often someone else's or nobody's. with whole-file lanes (k ≤ 4) that edit was in scope.
  - **interface mismatches** grow with the number of cross-lane signatures.
  - **wasted lanes** are as common in solved as in failed runs: they cost gpu time, not correctness.
  - **ignored corrections** look like a symptom: the gate's feedback points a lane at edits it may not make.
- **caveat:** the "lost" column rests on 5 task runs on 3 tasks. an association on a handful of tasks, not a measured cause.

## L1, the single local worker

L1 failed the pre-registered format-compliance rule (at most 20% of gated edits failing to parse or apply) and the output-cap rule (at most 10% of requests at the cap) after two format changes:

| configuration | edits failing | requests at the cap | tool-call replies |
|---|---|---|---|
| SEARCH/REPLACE, 8K output | 11 / 22 (50%) | 8 / 35 at 8K (23%) | (not logged then) |
| symbol-unit blocks, 16K | 9 / 19 (47%) | 2 / 25 at 16K (8%) | 5 of 19 replies |
| symbol-unit blocks, 16K, no-tools prompt, stop at `<tool_call>`, missing units added | 5 / 17 (29%) | 5 / 25 at 16K (20%) | 0 |

- **tool calls:** they are agent-trained behaviour. the model answered with `<tool_call><function=Bash> cat …` instead of edits, despite thinking being off, until the prompt and a stop sequence ruled it out.
- **the failures left after the fix:** mostly SEARCH text that does not match the file, and answers cut off at the cap.
- **decision:** the parent did not swap the model. L1 is reported as "failed compliance". it was never part of the primary.

## why the main run was not run

the [power note](../local-calib3/power-note.md):
- **expected discordance:** at the calibration's rates, the 37-task primary (exact mcnemar, two-sided α = 0.05) expects about 4 discordant tasks.
- **power:** about 0.2%.
- **what significance takes:** any p < 0.05 needs at least 6 discordant tasks, all in La's favour. 80% power needs La to win on about 20% of tasks and lose on almost none, as the cloud api study did.

the main run could only have been descriptive, so the owner stopped the track after calibration.

## deviations from part a

part b of the pre-registration lists them in full (b.5 items 1–13). in short:

1. **image:** vllm v0.33.0, under fallback 2 (v0.27.2 does not exist).
2. **`max_model_len`:** 98304, not 32768. approved, and re-checked with 0 preemptions until n = 8 at k ≈ 8.
3. **the pre-flight's planner output estimate:** 1,199 tokens, then 1,500 under the change list. the calibration planner cap went from $0.80 to $1.00, then to $1.80 cumulative.
4. **split passes:**
   - the first L1 pass ran in three logs (a dropped stream, then a container restart);
   - the repeat calibration ran in three sessions (a budget-guard and replay clash, my wrapper's reap, a 2-hour background limit);
   - La4 ran in two logs.
5. **edit format:** symbol-unit blocks for all local arms (approved), then no-tools prompt and tool-call stop (approved).
6. **lane count:** taken from the contract units as part a says. the planner lists changes and the kernel packs them; the first build had left the count to the planner.
7. **span scope gate:** adjusted for wide fan-out: adjacent units in one hunk, blank lines with their neighbours, one owner per insertion point, identical changes from two lanes applied once.
8. **L1 output cap:** 16K (approved).
9. **probe set:** only 10 of 12 probe plans were bought within the calibration cap, and the repeat calibration ran on those 10.
10. **Lb-text:** never run on the gpu, and the lb-kv trigger was never evaluated.

## spend

| item | ledger | billed by runpod |
|---|---|---|
| day 1 (pod `gf8sf5ayon5u1x`) | $0.109 | $0.085 |
| first calibration (`eq4o4ucbibfpx8`) | $1.611 | $1.613 |
| residual between sessions | — | $0.048 |
| repeat calibration, session 1 (`0s48fh8l90sbwl`) | $0.342 | $0.300 |
| repeat calibration, session 2 (`cukpo2ul52vj8e`) | $1.380 | $1.432 |
| completion (`m214yezt6pgalg`) | $0.575 | $0.587 |
| **gpu total** | **$4.017** (cap $10) | **$4.065** (balance $15.00 → $10.935) |
| planner, opus 5.5 (12 + 10 plans; every replay $0) | $1.587 (calibration cap $1.80) | |

- **no pod left:** every pod was terminated and reaped. `GET /v2/pods` is empty and `currentSpendPerHr` is 0.

## contamination

the 49 tasks' base commits date from 2019-08-01 to 2025-06-04 ([task dates](../local-calib/task-dates.json)). qwen3.8-27b's card states no training cutoff; its citation dates it to august 2026, and it reports a vendor swe-bench pro score of 61.7. contamination cannot be excluded. it would affect La and La-shadow alike, since they merge the same lane outputs, and it bears most on comparing local and api solve rates.
