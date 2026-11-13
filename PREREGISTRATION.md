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

## part b: the freeze (proposed 2026-11-13, not yet in force)

> **status:** proposed after the calibration ([`results/local-calib/`](results/local-calib/README.md)) and awaiting review. it is not in force, and the main run waits for it.
>
> the calibration failed two pre-registered checks on L1: format compliance and output caps. one configuration, La2, also exceeded the throughput-noise limit. so this part holds what was measured, the deviations so far, and the decision the protocol now requires (b.6).

### b.1 serving configuration (as calibrated)

- **image:** `vllm/vllm-openai:v0.33.0`, under day-1 fallback 2: `v0.27.2` does not exist. the pod requires host cuda ≥ 13.0.
- **checkpoint:** `sakamakismile/Qwen3.8-27B-MTP-NVFP4`, served as `qwen3.8-27b`.
- **decoding:** mtp `qwen3_5_mtp` with 3 speculative tokens; fp8 kv cache; prefix caching; `max_num_seqs` 16; `max_model_len` **98304** (deviation b.5.2).
- **requests:** thinking off; temperature 0.7, top-p 0.8, top-k 20; at most 8K output tokens per lane request; 10 minutes per task.
- **gpu:** runpod community cloud, one `NVIDIA GeForce RTX 5090` at $0.69/h. the harness and docker verifier run outside the pod and call vllm over https (verifier option b).
- **measured at 98304:**
  - smoke test passed;
  - one 79,381-token prompt alone decoded at 44.7 tok/s;
  - 8 lanes of 21,697 tokens at once ran at 242 tok/s aggregate with 0 preemptions;
  - over the 2.3-hour calibration: 0 preemptions, peak kv-cache use 43%, mtp acceptance 0.89.

### b.2 n

- **by the choice rule:** n = 2. it has the most test-gated tok/s with no preemption (estimated 17.4 against 12.8 at n = 8 and 11.4 at n = 4), and no n solved more than 4 of 12.
- **why the choice is provisional:**
  - the cis overlap;
  - the planner chose at most 2 lanes on 10 of 12 tasks, so n rarely binds;
  - La2's aggregate-throughput iqr is 44% of its median, which triggers stop rule 5 (repeats are added).

  n is re-chosen by the same rule after the repeat calibration in b.6.
- **after the repeat calibration** ([`results/local-calib3`](results/local-calib3/README.md); 10 tasks, k of 6–8): n = 2 is the only n with a complete pass.
  - **runs:** La2 solved 2/10 and its repeat 1/10; test-gated tok/s 5.5 and 1.8. La4 reached 7 tasks (1 solved, about 5.2 estimated); La8 did not run.
  - **proposed:** n = 2 by the rule, with no preemption.
  - **caveat:** the two n = 2 runs show that test-gated tok/s varies more between runs than n is likely to change it at 10 tasks. raw throughput rose with n (180–191 tok/s at n = 2, 210 at n = 4).
  - **for the parent:** whether to finish La4 and La8 first (about 1 pod-hour, about $0.75).

### b.3 code and prompt hashes

[`results/local-calib/hashes.json`](results/local-calib/hashes.json):
- **commit:** `dad9da4`. `src/` there is identical to `06b8141`, which ran the calibration.
- **contraprova:** pinned at `403caf23e1f9321e0244f3805b00a177476df4e0`.
- **files:** the sha256 of every tracked file in `src/` and `scripts/`.
- **prompts:** the sha256 of every prompt constant in `parataxis.lanes` and contraprova's `swepro_arms`.

these hashes describe the calibrated code. they are re-frozen after b.6, and a change to any listed prompt or file after that is a deviation.

### b.4 contamination check

- **task dates:** the base commits of all 49 tasks (37 main, 12 probe) date from 2019-08-01 to 2025-06-04 ([`task-dates.json`](results/local-calib/task-dates.json)).
- **the model:** qwen3.8-27b's card states no training cutoff. its citation dates it to august 2026, and it reports swe-bench pro 61.7.
- **conclusion:** contamination cannot be excluded, and the results will say so.
  - it does not favour either side of the primary comparison: La and La-shadow merge the same lane outputs.
  - it bears most on comparing local and api solve rates.

### b.5 deviations from part a so far

1. **image:** `v0.33.0` instead of `v0.27.2`, under fallback 2 (day 1).
2. **`max_model_len`:** 98304 instead of 32768, approved before the calibration.
   - **reason:** the prompts do not fit in 32768 with 8K of output. calibration's local inputs reached 41,149 tokens (L1) and 43,790 (a La lane).
   - **re-check:** b.1, passed.
   - **effect:** none on what lanes see. lane views, unit listings and prompts are built by the harness regardless of the limit, which only decides whether a request is refused.
3. **the lane pre-flight's planner output estimate:** set to 1,199 tokens, the api study's measured median, instead of contraprova's default. the calibration planner cap was raised from $0.80 to $1.00, keeping the 1.2 margin, with approval.
4. **L1's calibration pass ran in three logs:** a stream drop led to the fix `06b8141`, then a container restart. 2 + 5 + 5 tasks; tasks in flight were rerun from scratch.
5. **metrics logging** started at 02:25 instead of at the first pass. the preemption counter is cumulative, so preemptions are covered in full.
6. **edit format (calibration-stage change, approved; b.6):** the local arms' edit format is now symbol-unit blocks plus SEARCH/REPLACE ([`src/parataxis/unit_edits.py`](src/parataxis/unit_edits.py); `--edit-format units`, the default with `--local`).
   - a UNIT block replaces a function, method or class by name. an AFTER block adds code below one.
   - the harness rewrites both into exact SEARCH/REPLACE blocks from the original file, so parsing, scope gates, merges and logs are unchanged.
   - the prompt asks for UNIT only on units of up to about 60 lines, or ones mostly rewritten, and SEARCH/REPLACE for small changes inside long units. this keeps replies no longer than SEARCH/REPLACE: replaying the gold patches of the 37 main tasks, unit replies were 1.0× (median) and 1.1× (p90) the SEARCH/REPLACE length for L1. without the rule they were 1.14× and 1.68×.
   - it applies to L1, La and Lb alike, including their retry and repair texts. the calibration logs above used `--edit-format search`.
7. **Lb notes:** the blackboard note now strips edit blocks in their canonical form. the earlier pattern missed them. Lb has not run yet.
8. **the lane count from the contract units (calibration-stage change, approved; b.6).** the planner prompt as first built left the count to opus ("1 to 8 lanes … fewer when the files are tightly coupled"). now it follows part a and design.md:
   - **what the planner sees:** the units of every code file with two or more units, plus its module-level lines as `path::<module>`.
   - **what it returns:** a list of changes, one per unit. it is told to list every unit it might need, because a unit no change lists cannot be edited.
   - **packing:** the kernel packs the changes deterministically (`symbols.plan_symbol_lanes`): `k = min(8, changes)`, largest first, toward a 24K-token prompt per lane.
   - **multi-unit changes:** a change naming several units (one edit spanning them, such as code moved across adjacent units) stays in one lane.
   - **interface owners:** the planner names them as units, and they become the lanes holding those units.
   - **unlisted units:** an edit to a unit no lane owns is undone by the span gate and counted as its own clash kind, `unlisted_unit`.
9. **the span scope gate, for wide fan-out:**
   - one hunk may change several adjacent units the lane owns;
   - blank lines go with the units next to them;
   - every insertion point has exactly one owning span (inside it, directly below it, or in the blank lines below a unit), so two lanes never both insert the same code.

   without these, the gold patch could not be split into lane shares on 6 of the 12 probe tasks (moves and deletions across units, and new code inserted between units).
10. **L1 output cap:** 16K tokens (approved). L1 is not a lane, and 8K cannot hold the gold patch of 9 of the 37 main tasks.
11. **the lane pre-flight's planner output estimate:** 1,500 tokens per plan under the change list. this is an estimate: about 700 for the interfaces, rationale and JSON, plus about 65 per change, at a median of about 12 changes per probe task (the dry planner's count). it was 1,199 for the first calibration's schema. the budget guard caps the real spend whatever the estimate says.
12. **plans bought without a pod:** `--plans-only` buys each probe task's plan and stops. the calibration passes replay them, and the lane pre-flight prices a replayed plan at $0.
    - **plans bought:** 10 of the 12 probe plans, for $0.7928. the budget guard refused the last 2 (ansible `d72025be`, openlibrary `25858f9f`): the next request's worst case was above the $0.213 left of the $1.80 calibration cap.
    - **calibration set:** the repeat calibration runs on the 10 tasks with plans; the 2 are not bought (approved).
    - **replay:** replaying passes run with `PARATAXIS_REPLAY_ONLY=1`, so every request that is not a replayed plan is refused before it reaches the claude api, and their planner spend is exactly $0.
13. **after the first repeat-calibration L1 pass (calibration-stage change, approved).** L1 still failed format compliance: 9 of 19 gated edits failed (47%). two causes were new:
    - **tool calls:** 5 replies were agent-style tool calls (`<tool_call>` … `Bash`) instead of edits;
    - **UNIT misuse:** UNIT blocks named functions that did not exist yet.

    so, for L1, La and Lb alike:
    - the system prompt states that there are no tools and that the reply is edit blocks only;
    - local requests stop at `<tool_call>`, and a reply that is only a tool call is its own failure kind (`tool_call`), sent to the edit-repair turn with that message;
    - a UNIT block naming a missing function or method adds it, at the end of its class or of the file;
    - a bare javascript name also matches an assignment to `obj.name`.

    tool-call replies are logged per submission (`tool_call`, `repair_tool_call`), so the write-up can separate agent-trained behaviour from other format failures.

### b.6 required before the freeze: the failed checks

- **format compliance (L1):** 11 of 22 gated L1 edits failed to parse or apply (50%; threshold 20%). part a says: change the edit format, else swap the model, and repeat the calibration.
- **output caps (stop rule 4):** 8 of 35 L1 requests hit the 8K cap (23%; limit 10%), so the L1 configuration is invalid. La was within both limits: 0–7% at the cap, 5–11% failed edits.
- **throughput noise (stop rule 5):** La2 needs repeats.
- **proposed remedy** (the first step of the protocol's order):
  1. **the edit format.** change the local arms' edit format to symbol-unit replacement, with SEARCH/REPLACE kept for text outside units:
     - the response names a unit (`path::qualified.name`, from the unit listing the harness already builds) and gives its full new text;
     - new units are placed after a named unit.

     it is meant to remove the failures from echoing SEARCH text exactly, and to shorten responses for small edits inside large files; the repeat calibration measures whether it does. it applies to L1 and La alike, so that their comparison stays on one format. it is built and tested offline at $0.
  2. **repeat the calibration** with the plans replayed: L1, La2 twice, La4, La8; $0 planner, about 2.5 pod hours, about $1.75 gpu inside the $10 cap.
  3. **then:** re-choose n by the same rule, re-check format compliance, output caps and noise, and re-freeze the hashes.
- **if the new format still fails compliance:** the protocol's next step is another model, which this part would name.
- **built (2026-11-13):** the format and its tests (30), and $0 dry runs where the offline workers answer the gold patch in unit blocks. every task solved, with no unit-block error and no edit failure:
  - 12 probe tasks with L1, La and Lb (54 unit blocks from L1);
  - 37 main tasks with L1 and La (194 unit blocks).
- **found while building: L1's 8K output cap is too small for its task.** written as compact SEARCH/REPLACE blocks, the gold patch alone exceeds 8K tokens on 9 of the 37 main tasks for L1 (6 at 12K, 3 at 16K; characters / 3.6). only 5 of 111 La lane replies do, because lanes split the work.
  - part a fixes 8K per lane request; L1's 8K was an implementation choice (it reused the lane constant).
  - decided: **L1 gets 16K output tokens** (b.5 item 10).
- **the lane count** did not follow part a: the calibration plans had 1–4 lanes (10 of 12 had 1 or 2), and only 2 of 25 lanes owned units. fixed before the repeat (b.5 items 8 and 9).
- **the repeat calibration, as approved (conditional go):**
  1. buy the 12 probe plans under the change list (`--plans-only`), within the $1.80 cumulative calibration planner cap ($0.7942 spent). the pre-flight expects $0.821, $0.985 with the 1.2 margin.
  2. if the median k of the real plans is at least 3: L1 (units format, 16K), La2 twice, La4 and La8 on those plans. per session: ≤ $3.00 gpu (ledger), 3.5 h, community cloud, 15-minute idle terminate, then reap and verify. a pass that cannot finish inside the limits is not started.
  3. if the median k is below 3: stop after the plans and report what opus produced.
  4. noise is judged on La2 × 2 (T2). main-run throughput repeats run only if stop rule 5 fires on the main run, and then for La only (T1). the $10 gpu cap stays: if the plan cannot fit it, stop and report.

### b.7 main-run planner cost and the proposed cap

- **expected:** $2.389 for the 37 main plans ([`preflight-main.json`](results/local-calib/preflight-main.json)):
  - input counted with `count_tokens` on the real symbol-lane planner prompts;
  - output at 1,199 tokens per plan;
  - $2.867 with the 1.2 margin.
- **calibration's real spend** was 6% above its pre-flight, which puts the main run at about $2.53.
- **proposed cap:** **$2.90** for the main run, so the pre-flight fits with its 1.2 margin ($2.867 ≤ $2.90). with calibration's $0.794 the track's planner total would be at most $3.69, against the $3.00 in part a's stop rule 2. the repeat calibration replays plans and adds nothing.
- **after the change list (b.5 item 8), re-run 2026-11-13:**
  - the main pre-flight with the new prompt expects **$2.611**, $3.134 with the 1.2 margin (input counted, a median of 9,609 tokens per plan; output at 1,500 per plan, b.5 item 11);
  - proposed main-run cap: **$3.30**, pre-approved up to that amount;
  - the track's planner total would be at most $1.80 + $3.30 = $5.10.

  the real plans of the repeat calibration measure the output per plan. if they run above the estimate, the main estimate and cap are revised before the main run.
