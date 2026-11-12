# local-track plan and cost

> **status:** a plan. nothing here has been rented, run or paid for. every step that spends money waits for the owner's approval.

the design is in [design.md](design.md). this page covers the benchmark choice, the steps, the cost and the stop rules.

## benchmark: swe-bench pro again, on the same tasks

- **main set: the 37 lanes-main tasks**, the ones the api study ran (`results/swepro-lanes/splits.json`, sha256 `9661965e…`, the 37 that fit the prompt bound).
  - **paired with the api study.** each task already has a haiku-lanes outcome, a shadow outcome and a cascade outcome. so local la can be set against haiku la, task by task, at $0 extra.
  - **multi-file by construction.** the selection picked multi-file tasks, which is what fan-out needs.
  - **the verifier and images are validated.** contraprova checked empty and gold patches and split gold patches into lanes on these images.
  - **contamination-resistant.** swe-bench pro is newer than most open-weight training cutoffs and uses copyleft and private repositories. still, a local model's cutoff should be checked against the task dates before the run.
- **calibration set: the 12 lanes-probe tasks**, which are disjoint from the main set. n (lanes and concurrency) is tuned here, never on the main set.
- **why not another benchmark now:**
  - aider polyglot is single-file and at ceiling (haiku 17/18 in contraprova's pilot), so it gives no room for fan-out.
  - swe-bench verified is mostly single-file and widely seen in training.
  - a second benchmark is the generalisation question, and it comes after the first local result.
  - if the 37 sit at ceiling for the local model too, the next set is fresh swe-bench pro tasks outside the 90 contraprova used.

## steps

1. **day 1: smoke test** (about 1 h of gpu, stop after it if any check fails):
   - start vllm ≥ 0.27.2 (needed for mtp with the hybrid gated-delta-net layers at long context) with qwen3.8-27b nvfp4, mtp speculative decoding, an fp8 kv cache, prefix caching, and `max_model_len` 32768;
   - one request: it loads, mtp is accepted (log the acceptance rate), single-stream tok/s;
   - `vllm bench` at 1, 2, 4, 8 and 16 concurrent streams, with mtp on and off: aggregate and per-stream tok/s, kv-cache use, preemptions;
   - re-count the 37 tasks' lane prompts with the local tokenizer (a `--tokenizer` option for `scripts/fit_symbol_lanes.py`, still to be built), and confirm every lane plus 12K of output fits;
   - one gold task end to end through the harness against the local endpoint, and one dry lane round.
2. **calibrate n on the 12 probe tasks:** la at n ∈ {2, 4, 8}, plus l1. choose the n with the most test-gated tok/s with no preemption, or the largest n whose solve rate is within one task of the best. write the choice into the pre-registration.
3. **pre-register** (committed before the main run):
   - the arms, n, prompts and their hashes, the ladder and blame rules;
   - the hashes of the task list and the harness files;
   - the analysis;
   - the stop rules.
4. **main run:** l1, la (with la-shadow derived) and lb-text on the 37 tasks. la and lb-text use the same plan per task, so they pair.
5. **lb-kv stretch**, time-boxed to 4 gpu-hours: a hogwild!-style shared-kv loop on 2 to 4 lanes for the 12 probe tasks only. reported as exploratory, whatever it shows.

## cost estimate

assumptions:

- **rental rate:** an rtx 5090 rents for about $0.40 to $0.99 per hour in 2026 (vast.ai marketplace median about $0.63; runpod community $0.69, secure $0.99). the estimate uses **$0.70/h**.
- **throughput:**
  - single stream: about 70 to 90 tok/s reported for this checkpoint;
  - aggregate: about 1,200 tok/s at 32 concurrent streams in one vllm test;
  - planned: **400 tok/s aggregate at 8 lanes** and 75 tok/s for one stream, to stay conservative.
- **output per task:**
  - la: 8 lanes × 3K tokens (thinking included), plus repairs, ≈ 30K → about 75 s;
  - l1: ≈ 10K → about 130 s.

| step | gpu-hours | at $0.70/h | note |
|---|---|---|---|
| smoke test | 1.5 | $1.05 | includes download and load time |
| calibrate n (12 tasks × 4 settings) | 2.5 | $1.75 | |
| main run (37 tasks × 3 arms) | 3.5 | $2.45 | generation only |
| verifier overlap and idle | 3.0 | $2.10 | the gpu waits while the verifier runs, unless rounds are pipelined |
| storage, setup and slack (+20%) | 2.0 | $1.40 | |
| **base plan** | **12.5** | **≈ $9** | $5 at $0.40/h, $12 at $0.99/h |
| lb-kv stretch | 4 | $2.80 | only if approved separately |

optional paid api items, off by default:

- **a cloud planner (opus, low):** about $1.90 for 37 tasks at the api study's measured cost, and the plan is shared by la and lb-text. the alternative is a local planner at $0. a local planner changes the planner variable, so the api comparison is then about the whole system.
- **cloud escalation after local repair (sonnet, then opus):** about $1 to $3, going by the api study's 5/37 first-merge blocks. it is a separate arm only if the owner wants a hybrid result.

the research put the base plan at about $10 of gpu. this estimate agrees: about $9 at $0.70/h, and up to $12 at secure-cloud rates.

## where the verifier runs

the swe-bench pro verifier runs task images in docker (2 to 3.5 gb each). most rented gpu pods are containers without docker-in-docker. there are two options:

- **a. verifier on the gpu box.** this needs a vm-type rental with docker (some vast.ai hosts, or a full-vm provider). it is simple, but the gpu idles while images pull and tests run.
- **b. verifier where contraprova ran it.** the harness calls the rented vllm endpoint over https with a bearer key. this needs the endpoint's host allowed in that environment's network policy, and the key stored as an environment secret, never in the repo. the gpu only generates, which is cheaper per hour of useful work.

the plan prefers b. it is an open decision for the owner.

## stop rules

- **stop after day 1** if the model does not load in nvfp4 with mtp on one 5090, or if 8 lanes at 32K preempt constantly. the fallback is fewer lanes or a 16K window, re-estimated before spending more.
- **hard budget cap per run** (default $15 of gpu). a gpu-time budget guard (gpu-seconds × rate, still to be built, alongside contraprova's dollar guard) stops the run cleanly at the cap.
- **no paid api request** unless the owner approved that item.

## open decisions for the owner

1. **planner:** local (at $0; it changes the planner) or cloud opus (about $2; it isolates the lane worker).
2. **verifier placement:** a (docker on the gpu box) or b (endpoint over https, which needs a network allowance and a secret).
3. **provider:** vast.ai (cheapest, variable hosts), runpod secure (stable, $0.99/h), or another.
4. **lb-kv stretch:** yes or no, at 4 gpu-hours.
5. **cloud escalation arm:** none (local-only result) or hybrid.
