# local-track plan and cost

> **status:** a plan. nothing here has been rented, run or paid for. every step that spends money waits for the owner's approval. every gpu number below is an estimate until day 1 measures it.

the design is in [design.md](design.md). this page covers the benchmark choice, the steps, the cost and the stop rules. it adapts the 2026-11-11 local-track research, which was written for aider polyglot: the api study has since moved lanes to swe-bench pro.

## benchmark: swe-bench pro again, on the same tasks

- **main set: the 37 lanes-main tasks**, the ones the api study ran (`results/swepro-lanes/splits.json`, sha256 `9661965e…`, the 37 that fit the prompt bound).
  - **paired with the api study.** each task already has a haiku-lanes outcome, a shadow outcome and a cascade outcome. so local la can be set against haiku la, task by task, at $0 extra.
  - **multi-file and decomposable.** polyglot exercises are small and weakly decomposable, and the research expected lanes to pick n = 1 or 2 there. on these tasks the fit study finds a median of 6 touched units.
  - **the verifier and images are validated.** contraprova checked empty and gold patches and split gold patches into lanes on these images.
  - **contamination.** qwen3.8-27b reports swe-bench pro 61.7 as a vendor score, so the public pro set may have been tuned on. the local model's training cutoff is checked against the task dates before the main run, and the result is disclosed either way.
- **calibration set: the 12 lanes-probe tasks**, which are disjoint from the main set. n (lanes and concurrency) is tuned here, never on the main set.
- **why not another benchmark now:**
  - aider polyglot is at ceiling for haiku (17/18 in contraprova's pilot) and single-file.
  - swe-bench verified is mostly single-file and widely seen in training.
  - generalisation comes after the first local result. if the 37 tasks sit at ceiling for the local model too, the next set is fresh swe-bench pro tasks outside the 90 contraprova used.

## steps

1. **off-gpu first, at $0:**
   - build the vllm client arm, the timing events and the gpu-time budget guard;
   - dry-run every arm against a fake openai-compatible endpoint.
2. **day 1: smoke test** (about 1 h of gpu; stop if a check fails):
   - start vllm ≥ 0.27.2 with qwen3.8-27b nvfp4 (w4a4, `mtp.*` unquantised), mtp speculation (`num_speculative_tokens` 3), an fp8 kv cache, prefix caching, `max_model_len` 32768, thinking off;
   - check output sanity and a non-zero mtp acceptance at concurrency 1 and 8;
   - `vllm bench` at 1, 2, 4, 8 and 16 streams, with mtp on and off: aggregate and per-stream tok/s, kv-cache use, preemptions;
   - confirm the prefix-cache hit tokens on a shared-prefix pair;
   - re-count the 37 tasks' lane prompts with the local tokenizer (a `--tokenizer` option for `scripts/fit_symbol_lanes.py`, still to be built);
   - run one gold task end to end through the harness against the endpoint.
3. **calibrate n on the 12 probe tasks:**
   - run la at n ∈ {2, 4, 8} and l1, plus the format-compliance check;
   - choose the n with the most test-gated tok/s and no preemption, or the largest n within one solved task of the best solve rate;
   - write the choice into the pre-registration.
4. **pre-register** (committed before the main run):
   - the arms, n, prompts and their hashes, the ladder and blame rules;
   - the hashes of the task list and the harness files;
   - the analysis, with la vs la-shadow as the first-listed primary contrast;
   - the stop rules.
5. **main run:** l1, la (with la-shadow derived) and lb-text on the 37 tasks. la and lb-text share one plan per task, so they pair.
6. **repeat runs for throughput:** at least 3 runs per configuration, after a discarded warm-up. the solve-rate contrast uses the first run only, as pre-registered.
7. **lb-kv stretch**, only if a trigger fires on the probe tasks: lb-text and la differ in coordination-failure counts on at least 3 tasks, or lb-text shows ignored-correction ("fixation") events on at least 2.
   - setup: hogwild_llm with a standard-attention model and a matched la on the same model;
   - budget: about 3 gpu-hours and one development day;
   - reported as exploratory.

## cost estimate

assumptions:

- **rental rate:** an rtx 5090 rents for $0.40 to $0.99 per hour in 2026 (vast.ai median about $0.63; runpod community $0.69, secure $0.99). the estimate uses runpod community at **$0.69/h plus 3.5% iof** (the brazilian tax on card purchases abroad), billed per second.
- **throughput** (none of it measured on our setup):
  - plain nvfp4 decode on a 5090 is about 86 to 93 tok/s at 1 stream and 344 tok/s aggregate at 8, with no speculation;
  - vllm with mtp gave 318 → 387 tok/s at 8 on other blackwell cards;
  - the research put vllm at 0.55 to 0.8× tensorfold, about 400 to 600 tok/s at 8 lanes;
  - **planned: 350 tok/s aggregate at 8 lanes, 75 tok/s for one stream.**
- **output per task, thinking off:**
  - la: 8 lanes × about 1.5K, plus repairs, ≈ 15K → about 45 s;
  - l1: ≈ 6K → about 80 s.

| step | gpu-hours | runpod $0.69/h + iof | vast $0.45/h + iof |
|---|---|---|---|
| day-1 smoke test and debug | 1.0 | $0.71 | $0.47 |
| calibrate n (12 tasks: l1, la at n = 2/4/8, mtp on/off subset) | 2.0 | $1.43 | $0.93 |
| main l1 (37 tasks) | 0.8 | $0.57 | $0.37 |
| main la (37 tasks) | 1.0 | $0.71 | $0.47 |
| main lb-text (37 tasks, round barriers) | 1.5 | $1.07 | $0.70 |
| repeat runs for throughput (l1, la, lb-text) | 2.0 | $1.43 | $0.93 |
| gpu idle while the verifier runs (option a only) | 2.0 | $1.43 | $0.93 |
| setup and model loads (2 sessions) | 1.0 | $0.71 | $0.47 |
| **subtotal** | **11.3** | **$8.07** | **$5.26** |
| contingency 20% | 2.3 | $1.61 | $1.05 |
| **base plan** | **13.6** | **≈ $9.7** | **≈ $6.3** |
| lb-kv stretch (if triggered) | 3 + loads | ≈ $3, up to $6 with the matched la | ≈ $2 to $4 |

- **base plan:** about **$10 of cash** on runpod community ($14 on runpod secure, $6 on vast), matching the research's ~$10. with the stretch, about $16.
- **headroom:** against the owner's $40 cash ceiling, about $24 stays unspent on purpose.

optional paid api items, off by default:

- **a cloud planner (opus, low):** about $1.90 for 37 tasks at the api study's measured cost, and the plan is shared by la and lb-text. the alternative is a local planner at $0. a local planner changes the planner variable, so the api comparison is then about the whole system.
- **cloud escalation after local repair (sonnet, then opus):** about $1 to $3, going by the api study's 5/37 first-merge blocks. it is a separate arm only if the owner wants a hybrid result.

### the economics, stated plainly

a rented gpu loses to haiku 5.5 on dollars:

- **haiku 5.5:** $0.10/$0.50 per mtok. a lane is cents.
- **a rented 5090:** 3 to 4× haiku per solved task at this plan's low utilisation (about 18%).
- **break-even:** about 43% sustained utilisation on vast, or 66% on runpod.

the local track's case rests elsewhere:

- wall-clock time to a passing solution;
- data that never leaves the machine;
- independence from api pricing;
- near-zero marginal cost on owned hardware (about $0.002 per task in electricity);
- the open coordination question.

parataxis makes no cheaper-than-haiku claim.

## where the verifier runs

the swe-bench pro verifier runs task images in docker (2 to 3.5 gb each). most rented gpu pods are containers without docker-in-docker. there are two options:

- **a. verifier on the gpu box.** this needs a vm-type rental with docker. it is simple, but the gpu idles while images pull and tests run.
- **b. harness and verifier off-gpu, where contraprova ran them.** they call the pod's openai-compatible vllm endpoint over https with a bearer key. this needs the endpoint's host allowed in that environment's network policy, and the key stored as an environment secret, never in the repo. the gpu only generates.

the research and this plan prefer b, which drops the idle row from the cost (about $1.40).

## stop rules

1. **mtp smoke test.** if acceptance is 0% or the output is malformed: check that `mtp.*` is unquantised, try the other method name, then run without mtp or switch to sglang. the choice is recorded before the freeze.
2. **format compliance.** if more than 20% of l1's probe edits are malformed, switch the edit format, else swap the model.
3. **caps.** thinking is off; requests are capped at 8K output tokens and tasks at 10 minutes. if more than 10% of requests hit a cap, the configuration is invalid.
4. **day 1.** if the model does not load in nvfp4 on one 5090, or 8 lanes at 32K preempt constantly, fall back to fewer lanes or a 16K window, and re-estimate before spending more.
5. **cash kill switch.** $10 for the base plan, $16 with the stretch. a gpu-time guard (gpu-seconds × rate, still to be built beside contraprova's dollar guard) stops the run cleanly.
6. **idle.** pods auto-terminate after 10 minutes idle. scripts terminate pods, never stop them, because stopped pods still bill storage.
7. **throughput noise.** if the iqr is over 25% of the median, add repeats.
8. **no paid api request** unless the owner approved that item.

## open decisions for the owner

1. **planner:** local (at $0; it changes the planner) or cloud opus (about $2; it isolates the lane worker).
2. **verifier placement:** a (docker on the gpu box) or b (endpoint over https, which needs a network allowance and a secret). b is recommended.
3. **provider and payment:**
   - runpod community ($0.69/h; a prepaid card needs a $100 deposit, so pay by credit card);
   - runpod secure ($0.99/h);
   - vast.ai (about $0.45/h, variable hosts).

   iof applies to any of them.
4. **a local gpu of your own?** if there is one, the cost becomes electricity and the economics flip.
5. **lb-kv:** is the trigger above the right bar?
6. **cloud escalation arm:** none (a local-only result) or hybrid.
