<div align="center">

<a href="https://github.com/aphesist/parataxis"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/readme/header-dark.svg"><img src="assets/readme/header-light.svg" alt="parataxis: parallel lanes for one coding task on one gpu, governed." width="100%"></picture></a>

</div>

parallel lanes for one coding task on one gpu, governed. *parataxis* (παράταξις) is "placing side by side": several streams work on the same task at once, each inside a typed contract (the code it owns, the interfaces it provides and needs, its tests). an interface round freezes the signatures before any lane writes code. the lanes' edits meet in a test-gated merge, a failure is blamed on specific lanes, and only those lanes are repaired or escalated. every coordination failure is counted. the control is a **shadow merge**: the same lane outputs, token for token, merged with no contracts, no gate and no repair.

the engine is [contraprova](https://github.com/aphesist/contraprova), pinned as a dependency: its event-sourced, hash-chained log with a single validating writer, its gates, statistics, pricing and the swe-bench pro harness. parataxis owns the lane layer.

> on one consumer gpu, do parallel local lanes under contracts and a test-gated merge solve more tasks than an ungated merge of the same lane outputs, and how many test-passing tokens per second does that give?

> **status:** paused. the local track stopped after calibration, by the owner's decision ([results/local](results/local/README.md), exploratory).
> - **done:** the lane layer, symbol-level lanes, the local arms and the pod tooling are built and tested (about 140 tests). day 1 and the calibration ran on one rented rtx 5090: gpu $4.02, planner $1.59.
> - **found:** on 10–12 probe tasks the local lanes rarely beat the ungated merge (pooled 4 runs each way; the api study had 8 to 0). wide fan-out (6–8 lanes) solved fewer tasks than 1–4 lanes, most plausibly because of how the change was cut into units. aggregate throughput stayed flat at about 220–240 tok/s across concurrency.
> - **not done:** the main run. at these rates the primary had about 0.2% power ([power note](results/local-calib3/power-note.md)).

## what it starts from

contraprova's pre-registered contract lanes study, on 37 fresh multi-file swe-bench pro tasks. haiku 5.5 lanes, an opus planner, and a haiku repair → sonnet → opus ladder. the results are copied here as starting evidence ([results/swepro-lanes](results/swepro-lanes/main/README.md), see its [provenance](results/swepro-lanes/PROVENANCE.md)).

- **governance pays.** the governed merge solved 36/37 and the shadow merge of the same first-pass outputs 28/37: discordant 8:0, exact mcnemar p = 0.008, +21.6 points [+8.1, +35.1].
- **it did not fan out.** the planner never chose more than 2 lanes. lanes owned whole files, and the largest lane held a median 80% of a task's code.
- **the planner was half the bill**, and on a local gpu the lanes cost almost nothing.

## what is new here

- **symbol-level lanes** (`src/parataxis/symbols.py`). a lane owns functions, classes or methods:
  - it sees them in full, with an outline of the rest of its files;
  - a scope gate checks that every changed line falls inside its spans;
  - there are up to 8 lanes, the count taken from the contract units, under a per-lane token target.
- **the fit study** ([results/symbol-lanes-fit](results/symbol-lanes-fit/README.md), $0, exact count_tokens counts with claude's tokenizer). on the 37 tasks, with symbol lanes, every lane prompt fits 24K tokens: the largest lane per task is a median 10.2K and at most 17.1K, and 21.6K when 8 lanes cover every unit. with whole-file lanes, only 20 of 37 tasks fit 24K, and the worst lane is 43.8K. a local model's tokenizer will count differently.
- **the local track** ([docs/design.md](docs/design.md)): qwen3.8-27b in nvfp4 with mtp, under vllm, on one rented rtx 5090. the arms:
  - l1, one local worker;
  - la, separate lane contexts;
  - lb-text, a shared blackboard;
  - lb-kv, a shared kv cache (a time-boxed stretch behind a trigger; it needs a standard-attention model, because qwen3.8's deltanet layers have no kv cache to share).

  the headline is governed against shadow, plus test-gated tok/s.

## pre-registration

- **the starting evidence was pre-registered.** contraprova's [PREREG.md](results/swepro-lanes/PREREG.md) was written and committed before any paid request of the main run, on 2026-11-12 (contraprova commit 1ed672e); its probe has its own ([PREREG-probe.md](results/swepro-lanes/PREREG-probe.md)). the hashes it freezes refer to contraprova's paths, not to this repository's copy of the lane layer ([provenance](results/swepro-lanes/PROVENANCE.md)).
- **the local track's protocol is pre-registered** ([PREREGISTRATION.md](PREREGISTRATION.md), part a), committed before any gpu rental or paid request of the local track. part b, the freeze, was proposed after calibration and never frozen. the track stopped there, and the closing status section says why.

## honesty table

every claim this project makes, and what kind of evidence stands behind it today.

| claim | status | basis |
|---|---|---|
| lane contracts and a test-gated merge beat an ungated merge of the same lane outputs (haiku lanes, cloud api) | **measured** (pre-registered, n=37, by contraprova) | [results/swepro-lanes/main](results/swepro-lanes/main/README.md): 36/37 vs 28/37, discordant 8:0, p = 0.008, +21.6 points [+8.1, +35.1] |
| haiku lanes match contraprova's cascade in solve rate and cost | **measured** (inconclusive; n=37, both near ceiling) | 36/37 vs 34/37, +5.4 points [0.0, +13.5], p = 0.50; cost per solved task ratio 1.07 [0.62, 1.76] |
| symbol-level lanes fit a 24K per-lane prompt on these tasks, up to 8 lanes | estimated (exact count_tokens counts with claude's tokenizer, a deterministic count with no sampling and so no ci; the local tokenizer is not yet counted) | [results/symbol-lanes-fit](results/symbol-lanes-fit/README.md): 37/37 within 24K, largest lane median 10.2K, max 17.1K (21.6K when 8 lanes cover every unit) |
| the lane layer behaves as it did in contraprova after the move | built | same logic, absolute imports and a module-routing hook; the full suite (`tests/test_lanes.py`, `tests/test_route.py`, `tests/test_symbols.py`) passed, 54 of 54, at 8729726 in a fresh venv with contraprova at 403caf2. it was run in the contraprova working session, because this session cannot execute contraprova |
| symbol-level lanes solve as many tasks as whole-file lanes | **measured** (exploratory; calibration, n = 10–12; no ci claimed) | local model, probe tasks: wide symbol plans (k 6–8) solved 0–2 of 10; narrow plans (k ≤ 4, mostly whole files) solved 4 of 12, and 3 of the same 10 ([results/local](results/local/README.md)). scope violations and unlisted units are associated with the failures |
| governed beats shadow with a local 27b lane worker | **measured** (exploratory; calibration, n = 10–12; no ci claimed) | pooled la vs la-shadow on probe tasks: 2 vs 2 discordant (wide, 40 runs) and 2 vs 2 (narrow, 36 runs). the 37-task main run was not run: about 0.2% power at these rates ([power note](results/local-calib3/power-note.md)) |
| parallel local lanes beat one local worker in solve rate or wall time | **measured** (exploratory; calibration, n = 10–12; no ci claimed) | L1 4/12 and 4/10 against la 4/12 (narrow) and 0–2/10 (wide). L1 failed the format-compliance and output-cap rules after two format changes ([results/local](results/local/README.md)) |
| a shared text blackboard beats separate lane contexts | **hypothesis** | lb-text vs la |
| a shared kv cache (hogwild!-style) works under governance | **hypothesis** (stretch) | lb-kv on the probe tasks against a matched la on the same model, exploratory |
| test-gated tok/s on one rtx 5090 is a useful fraction of raw tok/s | **measured** (exploratory; calibration, n = 10) | test-gated 1.8–6.7 tok/s against raw 130–232. aggregate throughput was flat at about 220–240 tok/s from 2 to 8 concurrent lanes, while the per-lane rate fell about 1/n ([results/local](results/local/README.md)) |
| results generalise beyond swe-bench pro | **hypothesis** | out of scope for now |

rows move from hypothesis or estimated to measured only when a result with its confidence interval is committed under `results/`. the local rows are the exception, marked exploratory: calibration evidence on 10–12 probe tasks, descriptive, with no significance claimed.

## next

the calibration points to two directions before any local main run:

- **decomposition.** a lane may also edit the units its change depends on, not only the units it owns. the merge arbitrates overlapping edits at merge time, instead of the span gate undoing them up front. scope violations and unlisted units were the clashes associated with failure ([backlog](docs/backlog.md)).
- **keeping the gpu busy during merge and verify.** between rounds the gpu idles while the harness merges, gates and runs the docker verifier, so throughput did not rise with more lanes. this is stage 1 of the engine backlog, the lane-aware scheduler ([backlog](docs/backlog.md)).

## quick start

```sh
pip install -e ".[dev]"     # installs contraprova at the pinned commit
pytest

python scripts/fit_symbol_lanes.py   # the $0 fit study; fetches scope files into data/ (not committed)
```

the lane harness is contraprova's command line with parataxis's lane layer in place (`python -m parataxis.run` imports `parataxis.lanes` first, then passes every argument to `contraprova.harness.run`):

```sh
python -m parataxis.run --benchmark swepro --lanes --split lanes-probe --arms La --dry-solve all \
  --lanes-splits results/swepro-lanes/splits.json --log runs/dry.jsonl
```

a dry run reads the swe-bench pro task data from `data/`, as contraprova's [swe-bench pro guide](https://github.com/aphesist/contraprova/blob/main/docs/swepro.md) describes; it is never committed.

## the data

the logs, reports and analyses are under [`results/`](results):
- `swepro-lanes`: contraprova's study, copied unchanged ([provenance](results/swepro-lanes/PROVENANCE.md));
- `symbol-lanes-fit`: this project's $0 fit study;
- `local` and `local-*`: the local track (its report, day 1 and the calibration sessions). the logs hold `contents_sha256` fields, never repository file contents. `contraprova verify results/swepro-lanes/main/log.jsonl` checks the chain and replays every event.

## layout

- `src/parataxis/lanes.py`, `lanes_detect.py`: the lane layer (planner, interface board, governed and shadow merges, blame, ladder, detectors), moved from contraprova 403caf2 with its history.
- `src/parataxis/run.py`: the harness command line, routed to parataxis's lanes.
- `src/parataxis/symbols.py`: symbol-level units, lane views, packing and the span scope gate.
- `scripts/fit_symbol_lanes.py`: the fit study.
- `results/`: committed evidence. `swepro-lanes` is from contraprova; `symbol-lanes-fit` is this project's.
- `docs/design.md`: the local track. `docs/local-plan.md`: the plan, benchmark choice and cost. `docs/backlog.md`: work planned for later, such as an inference engine of parataxis's own.

## licence

apache-2.0 ([LICENSE](LICENSE)), as contraprova.

the pictures in `assets/readme/` are drawn with the aphes.ist readme kit and embed subsets of Aphesis Script (SIL Open Font License 1.1, reserved font name "Aphesis Script") and Special Elite (apache-2.0, © 2010 Astigmatic), and the project's icon, a mark of aphesist's that is not covered by this project's licence.
