# power note: the primary on 37 tasks at the calibration's rates (2026-11-13)

> if the main run behaves like the probe calibration, can the primary (La vs La-shadow, exact McNemar, two-sided α = 0.05) detect a difference on 37 tasks?

> **status:** no. at the calibration's rates the main run expects about 4 discordant tasks and has under 1% power. at least 6 discordant tasks, all in La's favour, are needed for any p < 0.05. 80% power needs La to win on about 20% of tasks and lose on almost none (the api study had 22%: 8 to 0).

## the rates

| source | task runs | La only | La-shadow only | both solved |
|---|---|---|---|---|
| wide fan-out (k 6–8): La2, La2b, La4 (10 tasks), La8 | 40 | 2 | 2 | 2 |
| narrow plans (k 1–4): first calibration La8, La4, La2 | 36 | 2 | 2 | 10 |
| api study main (haiku lanes, opus planner) | 37 | 8 | 0 | 28 |

## power on 37 tasks

computed exactly over the multinomial of the discordant counts:

| assumed rates (La only / shadow only) | expected discordant | power |
|---|---|---|
| wide: 5.0% / 5.0% | 3.7 | 0.002 |
| narrow: 5.6% / 5.6% | 4.1 | 0.003 |
| 15% / 0% | 5.5 | 0.49 |
| 20% / 0% | 7.4 | 0.78 |
| 20% / 2% | 8.1 | 0.56 |
| 25% / 2% | 10.0 | 0.76 |
| 30% / 2% | 11.8 | 0.89 |

- **why the power is low:** the local model solves few tasks either way, so the governed and shadow merges rarely disagree. at 1–2 solves in 10, a governance effect has almost no room to show.
- **what a main run could still report:**
  - descriptively: the difference with its bootstrap ci, solve rates with wilson intervals, coordination failures by kind, and throughput scaling by n;
  - not a confirmatory primary at these rates.

## why wide fan-out solves fewer tasks than k ≤ 4 plans did

- **data:** the clash counts per task run in the wide passes (governed mode only), split by outcome. "lost" means a task the narrow plans solved in at least 2 of 3 runs and the wide plans failed (5 task runs, 3 tasks).

  | clash kind | per run when solved | per run when failed | per lost run |
  |---|---|---|---|
  | wasted lane | 2.2 | 2.2 | 2.6 |
  | scope violation (undone) | 0.8 | 1.7 | 2.2 |
  | unlisted unit | 0.0 | 0.7 | 1.2 |
  | interface mismatch | 0.0 | 0.4 | 0.8 |
  | ignored correction | 0.0 | 1.5 | 1.0 |
  | unattributable failure | 0.0 | 0.7 | 0.0 |

- **most plausible explanation: decomposition, not throughput.**
  - **scope violations and unlisted units:** the change needs edits outside the units a lane owns (scope violations, undone by the span gate), or in units no lane owns (unlisted units). both are about twice as frequent, or only present, when the task fails, and highest in the lost tasks. with 6–8 lanes on 1–3 files, a function a lane must touch is often someone else's or nobody's. with k ≤ 4 and whole files, that edit was in scope.
  - **interface mismatches:** they appear only in failed runs. more lanes mean more frozen cross-lane signatures to get right.
  - **wasted lanes:** equally common in solved and failed runs (the planner lists units that end up unchanged). they cost GPU but do not explain the drop.
  - **ignored corrections:** a symptom. a blamed lane repeats itself on repair because the gate feedback cannot point it at edits it is not allowed to make.
- **caveat:** 5 lost task runs on 3 tasks. this is a direction, not a measurement.
