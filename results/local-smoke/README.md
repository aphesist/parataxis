# day 1: the smoke test on one rtx 5090 (2026-11-13)

> does qwen3.8-27b in nvfp4 with mtp serve under vllm on one rented rtx 5090, at 8 concurrent long lanes, as the pre-registration requires?

> **status:** passed every pre-registered criterion (PREREGISTRATION.md, "day 1"). one fallback applied: the image. gpu cost: $0.085 billed by runpod.

- **run:** `scripts/day1.sh` with `MAX_HOURS=1.5`, then `python -m parataxis.pod reap`.
- **pod:** runpod community cloud, `NVIDIA GeForce RTX 5090`, $0.69/h, host cuda ≥ 13.0 (rest api v2).
- **image:** `vllm/vllm-openai:v0.33.0`. fallback 2 of the pre-registration: the named `v0.27.2` does not exist on docker hub, and v0.33.0 is the newest release at or above it (cuda 13.0, entrypoint `vllm serve`).
- **checkpoint:** `sakamakismile/Qwen3.8-27B-MTP-NVFP4`, mtp `qwen3_5_mtp` with 3 tokens, fp8 kv cache, prefix caching, `max_model_len` 32768, `max_num_seqs` 16.
- **files:**
  - `smoke.json`: every check and number;
  - `ledger.jsonl`: pod created, ready and terminated, with the hourly price.

  neither holds a key.

## timeline

| event | time after create |
|---|---|
| pod running | 0.9 s |
| vllm serving the model (image pull, download, load) | 502.8 s (8.4 min) |
| pod terminated (after the smoke test) | 567 s (9.5 min) |

- **cost:** ledger estimate $0.109 (create to terminate at $0.69/h). runpod billed $0.085: the balance went from $15.00 to $14.915.
- **no pod left:** afterwards `GET /v2/pods` listed no pod, and the pod's id returned 404.

## checks

| check | result | numbers |
|---|---|---|
| models | **pass** | the served model listed; a request without the key gets 401 |
| sanity | **pass** | stops on its own, 18 tokens, 100% printable, code returned |
| sweep (512 tokens per stream) | **pass** | aggregate tok/s: 1 stream 116, 2 → 248, 4 → 367, 8 → 849, 16 → 917; per stream 116 → 91 |
| mtp acceptance over the sweep | **pass** (> 0) | 0.714 (10,826 accepted of 15,156 drafted) |
| long: 8 streams, ~14.6K-token prompts, 1K outputs | **pass** | no failed request, 0 preemptions, 288 tok/s aggregate, 49 per stream |
| prefix cache | **pass** | 8,000 hit tokens on a shared prefix |

## what these numbers are, and are not

- **one run of each configuration, after no warm-up.** the 4-stream row (367 tok/s) sits below the trend between 2 and 8 streams. throughput needs the pre-registered repeats (median and iqr over at least 3 runs) before any claim. these are smoke numbers.
- **the long check's prompts were ~14.6K tokens, not ~20K.** the smoke test sized them as characters / 4, and the local tokenizer counts fewer. the largest symbol-lane prompt in the fit study is 21.6K claude tokens, so a longer check belongs in the calibration.
- **8 short streams reach about 850 tok/s, and 8 long ones about 290.** the research estimated 400 to 600 tok/s at 8 lanes. the gap between short and long prompts is what the lanes will see, and calibration measures it on real lane prompts.
- **nothing here is about solving tasks.** that is the calibration on the probe tasks, then the main run.
