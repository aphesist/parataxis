# calibration completion: La4's last 3 tasks and La8 (2026-11-13)

> how do solves and throughput change with n at 6–8 lanes per task, on the 10 probe tasks with plans?

> **status:** done, inside the session's limits (≤ $1.20 ledger, ≤ 1.5 h). La at n = 8 solved 0 of 10 (shadow 1) and had 3 preemptions, so the rule excludes it. n = 2 stays the proposal.
>
> aggregate throughput hardly scales with n at k ≈ 8 (216–238 tok/s), while the rate per request falls (129 → 69 tok/s).

- **pod:** `m214yezt6pgalg`, community rtx 5090, $0.69/h, 09:26–10:16 utc. vllm served 495 s after create.
- **driver:** detached (`setsid nohup`), with the watchdog. the pod was terminated by the driver's exit, then `parataxis.pod reap` ran by hand: `GET /v2/pods` empty, spend $0/h.
- **plans:** replayed (`PARATAXIS_REPLAY_ONLY=1`). La4c's 3 and La8's 10 planner requests were all replays at 0 tokens: $0.00.

## n, all passes on the 10 tasks

tokens are estimated (characters / 3) for every pass here, so the passes compare on one count. the tokenized La2 figures are in [`../local-calib3`](../local-calib3/README.md).

| n | runs | La solved | shadow solved | test-gated tok/s (est.) | aggregate tok/s, median [iqr] | per-request tok/s, median | tail share | preemptions |
|---|---|---|---|---|---|---|---|---|
| 2 | La2 | 2 | 1 | 6.7 | 216 [189, 240] | 129 | 0.47 | 0 |
| 2 | La2b (repeat) | 1 | 1 | 2.1 | 235 [188, 250] | 121 | 0.28 | 0 |
| 4 | La4 + La4c (7 + 3 tasks, two sessions) | 1 | 1 | 3.9 | 217 [200, 294] | 102 | 0.81 | 0 |
| 8 | La8 | 0 | 1 | 0.0 | 238 [211, 274] | 69 | 0.84 | **3** (at 10:13; peak kv 80%) |

- **choice rule:** the most test-gated tok/s with no preemption. n = 8 is excluded by its preemptions, and n = 2 has the most of the rest. no n solved a task more, so **n = 2**.
- **scaling at k ≈ 8:** more concurrent lanes do not raise aggregate decode throughput much here. the rate per request falls about as fast as concurrency rises. the lane prompts are long (median ~6.6K tokens, so prefill dominates) and the merge and verify steps between rounds idle the gpu. the day-1 sweep with short prompts reached 849 tok/s at 8 streams.
- **coordination failures (governed):**

  | | La4 (10 tasks) | La8 |
  |---|---|---|
  | wasted lane | 27 | 20 |
  | scope violation | 20 | 15 |
  | ignored correction | 19 | 12 |
  | unlisted unit | 8 | 6 |
  | unattributable | 7 | 3 |
  | interface mismatch | 0 | 4 |
  | interface change request | 0 | 2 |

## cost

| item | amount |
|---|---|
| this session (ledger) | 0.834 h, $0.575; billed $0.587 |
| all pods (ledger) | $4.017 of the $10 cap |
| balance | $10.935 |

## files

- `logs/`: La4c and La8, verified, with their task orders.
- `analysis/`: `La4-combined-est.json` (session 2's La4 log plus La4c) and `La8-est.json`.
- `ledger.jsonl`: this pod.
- `metrics.jsonl.gz`: vllm `/metrics` each minute.
- `smoke-98304.json`: the smoke test.

none holds a key.
