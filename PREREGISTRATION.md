# pre-registration: the local track

> **question:** on one rented rtx 5090, do parallel local lanes under typed contracts and a test-gated merge solve more swe-bench pro tasks than an ungated merge of the same lane outputs, and how many test-passing tokens per second do they give?

> **status:** part a (this protocol) is committed before any gpu rental or paid request of the local track. part b (the freeze: code and prompt hashes, the chosen n, the serving configuration) is appended before the main run, after the day-1 smoke test and the calibration on the probe tasks. anything changed after part b is reported as a deviation.

written 2026-11-13. design: [docs/design.md](docs/design.md). plan and costs: [docs/local-plan.md](docs/local-plan.md). the owner's decisions of 2026-11-13 are binding here:
- a cloud opus 5.5 planner at low effort, as in the api study;
- runpod;
- the harness and docker in the cloud container, calling the pod's vllm endpoint over https;
- lb-kv only if the trigger below fires;
- no cloud escalation in the headline.

## part a: the protocol

### tasks

- **main set:** the 37 tasks of contraprova's pre-registered lanes-main run. these are the 40 tasks of `lanes-main` (split sha256 `9661965e359551d5cb117bb75bcf65acae2faef853bea5a4ac0c30681d74e828`, `results/swepro-lanes/splits.json`), minus the 3 dropped there for prompts over 90K, in the split's order. the list is [`results/local/tasks-main.txt`](results/local/tasks-main.txt), file sha256 `84750278490848aaf18fb6a7136f649f00a9fa930391ec8ac13da24aad435256`. every task is paired with its api-study outcomes (haiku lanes, shadow, cascade).
- **calibration set:** the 12 `lanes-probe` tasks (split sha256 `74574d74feb98bf97731c1c299f289ee521eb9191a626e716bc7824654c4854f`). the list is [`results/local/tasks-probe.txt`](results/local/tasks-probe.txt), file sha256 `435026cba99bec6c2600aef5b44ec70e5e5692edc0ab4b40b3a5f82aeba29b1c`. it is disjoint from the main set. n and any serving fallback are chosen here, never on the main set.
- **no task is added, removed or replaced** after part b, except for a harness or infrastructure failure on a task, which is reported per task.
- **contamination.** qwen3.8-27b reports a vendor swe-bench pro score (61.7). before part b, the model's stated training cutoff is compared with the task dates, and the comparison is disclosed in the results whatever it shows.

### arms

all arms use the same tasks, the same verifier and score tests, and the same local model and serving configuration.

| arm | what runs | planner |
|---|---|---|
| **L1** | one local worker on the whole task: the cascade's worker prompt and edit format, one edit-repair turn, then one local retry with the gate feedback | none |
| **La** | local lanes in separate contexts, at most 8, the lane count taken from the contract units. lanes own symbol-level units; the span scope gate, the interface round, the governed merge with gates, blame (rules 1 to 3 with widening) and the local ladder (a local lane, then one local repair). up to n lane requests are concurrent | opus 5.5, low effort, one plan per task |
| **La-shadow** | derived from La's first replies: merged with no contracts, no gate and no repair, then scored once. no extra tokens | La's |
| **Lb-text** | La plus a shared, append-only text blackboard: the lanes share one prompt prefix, and between rounds each lane's interface notes and progress are appended to it | **La's plan for the same task, replayed** (paired with La) |
| **Lb-kv** (conditional) | hogwild!-style shared kv on a standard-attention model, against a matched La on that model; probe tasks only; exploratory | see the trigger |

- **lb-kv trigger.** it is built only if, on the 12 probe tasks, Lb-text and La differ in coordination-failure counts on at least 3 tasks, or Lb-text shows ignored-correction events on at least 2. it is time-boxed to 4 gpu-hours, and its result is exploratory whatever it shows.
- **no cloud escalation** in any headline arm. the ladder ends at the local repair, and a lane still blamed after it ends the task unsolved.
- **sampling:** thinking off, temperature 0.7, top-p 0.8, top-k 20 (qwen's non-thinking recommendation), at most 8K output tokens per lane request. each task is run once per arm.

### primary analysis

- **La vs La-shadow, solve rate on the score tests**, paired by task on the 37 main tasks.
- **exact mcnemar, two-sided, alpha 0.05.** this is the only primary contrast (holm with m = 1).
- the paired difference is reported with a 95% bootstrap ci (10,000 resamples, seed 20261113).

### secondary analyses (descriptive, unadjusted)

- **test-gated tok/s** per arm, defined exactly:
  - for each task, the tokens of the diff of the shipped merge if it passes the score tests, else 0, counted with the local tokenizer;
  - divided by the task's end-to-end wall time (from the plan request, or the first worker request for L1, to the final merge decision), with verifier time excluded and reported separately;
  - aggregated as the sum of tokens over the sum of times, with a bootstrap ci over tasks.
- **raw tok/s** per arm: all generated output tokens over the same times.
- **paired solve-rate contrasts** (exact mcnemar and bootstrap ci each): La vs L1; Lb-text vs La; local La vs the api study's haiku La on the same tasks.
- **wall time to a passing solution**, La vs L1: the median of the paired differences, with a bootstrap ci.
- **coordination failures** per task by kind, from contraprova's detectors, La vs Lb-text: wilcoxon signed-rank.
- **lane counts and ladder:**
  - the distribution of chosen lane counts;
  - how often each blame rule fired;
  - how often the local repair rescued a lane;
  - gate replays (blocked merges scored on the score tests).
- **throughput:** median and iqr of per-lane and aggregate decode tok/s, time to first token, the tail share (time with fewer than n lanes active), and mtp acceptance per round.
- **cost:**
  - gpu-hours and gpu dollars per arm and per solved task, from the pod ledger;
  - planner dollars, from the log;
  - no cheaper-than-haiku claim is made.

### day 1: the smoke test

`scripts/day1.sh` creates one pod, waits until vllm serves, runs `parataxis.smoke`, and terminates the pod.

**serving configuration:**
- image `vllm/vllm-openai:v0.27.2`;
- checkpoint `sakamakismile/Qwen3.8-27B-MTP-NVFP4` (w4a4 nvfp4 with the `mtp.*` modules unquantised);
- mtp speculation (`qwen3_5_mtp`, 3 tokens), an fp8 kv cache, prefix caching;
- `max_model_len` 32768, `max_num_seqs` 16.

**pass criteria (all must hold):**
1. **models:** the endpoint lists the served model, and refuses a request without the key.
2. **sanity:** a short coding prompt at concurrency 1 returns code that stops on its own, more than 95% printable.
3. **sweep:** 1, 2, 4, 8 and 16 concurrent streams of 512 tokens complete with no failed request, and the mtp acceptance rate over the sweep is above 0.
4. **long:** 8 concurrent streams with ~20K-token prompts and 1K outputs complete with no failed request and no preemption.

the prefix-cache counter is recorded (unverified if vllm does not export it).

**fallbacks, in this order; each is recorded and re-tested:**
1. mtp acceptance is 0, or the output is malformed:
   - check that `mtp.*` is unquantised;
   - retry with the method name `mtp`;
   - else serve without speculation.
2. the image tag is missing or fails to start: the newest `vllm/vllm-openai` tag at or above 0.27.2.
3. the checkpoint fails to load: another nvfp4 build of qwen3.8-27b with unquantised `mtp.*`, named in part b.
4. long fails on preemption: `max_model_len` 16384 or `max_num_seqs` 8, then the long check again. lanes keep 8K of output either way.
5. **stop.** if none passes, the run stops, and the outcome is reported as a negative result for this configuration.

### calibrating n (on the probe tasks)

- **runs:** La on the 12 probe tasks at concurrency n ∈ {2, 4, 8}, plus L1.
- **plans are shared across runs.** each probe task's opus plan is requested once, and the other n values replay it. replays are recorded with zero tokens and marked as replays, so they cost nothing and are not counted twice.
- **choice rule:** the n with the most test-gated tok/s and no preemption. if another n solves at least one more probe task, the larger of the two. the choice goes into part b.
- **format compliance.** if more than 20% of L1's probe edits fail to parse or apply, change the edit format, else swap the model, and repeat the calibration.

### stop rules and kill switches

1. **gpu cap.** base plan $10; with lb-kv $16. `parataxis.pod` refuses to create a pod past the cap, and the watchdog terminates at the cap.
2. **api cap.** planner dollars are capped at $3.00 by contraprova's budget guard (`--budget-usd`), checked before every request. the expected cost is $0.60 for the probe plans plus about $1.90 for the main plans.
3. **pods are terminated, never stopped.** each pod has a maximum lifetime (`--max-hours`). the watchdog terminates after 15 minutes idle (counted once vllm answers) or at the lifetime. `parataxis.pod reap` runs at the end of every session.
4. **output caps.** at most 8K tokens per lane request and 10 minutes per task. if more than 10% of requests hit a cap, the configuration is invalid and goes back to calibration.
5. **throughput noise.** if a configuration's iqr is over 25% of its median, repeats are added.
6. **no paid request** without the owner's approval of that item.

### reporting

- **evidence:** results go under `results/local-*`, with the hash-chained logs (no repository file contents), the pod ledger, the smoke-test output, the analysis and a report.
- **honesty:** README rows move to measured only with a ci committed there.
- **deviations:** every deviation from this document is listed with its reason.

## what is built and what is still to build before part b

- **built and tested offline:**
  - the local client: streaming, thinking off, local tokenizer counts;
  - the role client (local lanes, opus planner);
  - the local ladder, and up to 8 lanes;
  - concurrent local lane requests with an unchanged event order;
  - the pod lifecycle with its watchdog, ledger and gpu cap;
  - the smoke test;
  - fake vllm and runpod endpoints;
  - symbol-level units, lane views and the span scope gate (`parataxis.symbols`).
- **to build, at $0, before part b:**
  - the planner and merge integration of symbol-level lanes (lanes own spans; prompts use lane views; the scope gate applies spans);
  - arm L1 on the local model;
  - arm Lb-text and plan replay;
  - the per-task wall-time events and the test-gated tok/s analysis;
  - the local-tokenizer re-count in the fit study;
  - the ignored-correction detector used by the lb-kv trigger;
  - the 10-minute task cap.
