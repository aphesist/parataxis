<div align="center">

<a href="https://github.com/aphesist/parataxis"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/readme/header-dark.svg"><img src="assets/readme/header-light.svg" alt="parataxis: parallel lanes for one coding task on one gpu, governed." width="100%"></picture></a>

</div>

parallel lanes for one coding task on one gpu, governed. *parataxis* (παράταξις) is "placing side by side": several streams work on the same task at once, each inside a typed contract (the code it owns, the interfaces it provides and needs, its tests). an interface round freezes the signatures before any lane writes code. the lanes' edits meet in a test-gated merge, a failure is blamed on specific lanes, and only those lanes are repaired or escalated. every coordination failure is counted. the control is a **shadow merge**: the same lane outputs, token for token, merged with no contracts, no gate and no repair.

the engine is [contraprova](https://github.com/aphesist/contraprova), pinned as a dependency: its event-sourced, hash-chained log with a single validating writer, its gates, statistics, pricing and the swe-bench pro harness. parataxis owns the lane layer.

> on one consumer gpu, do parallel local lanes under contracts and a test-gated merge solve more tasks than an ungated merge of the same lane outputs, and how many test-passing tokens per second does that give?

> **status:** phase 1, no spending yet.
> - **done:** the lane layer moved here from contraprova with its history, and the full suite passes (54 passed at 8729726, with contraprova installed at the pinned commit; run in the contraprova working session, because this session cannot execute contraprova). symbol-level lanes (below file level) are built and tested offline. a $0 fit study ran on the 37 tasks of contraprova's lanes study.
> - **not yet:** no local model has run. the local-track plan ([docs/local-plan.md](docs/local-plan.md), about $10 of rented gpu) waits for approval.

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
- **the fit study** ([results/symbol-lanes-fit](results/symbol-lanes-fit/README.md), $0, estimated). on the 37 tasks, with symbol lanes, every lane prompt fits 24K tokens: the largest lane per task is a median 9.9K and at most 16.9K, and 20.1K when 8 lanes cover every unit. with whole-file lanes, only 20 of 37 tasks fit 24K, and the worst lane is 43.6K.
- **the local track** ([docs/design.md](docs/design.md)): qwen3.8-27b in nvfp4 with mtp, under vllm, on one rented rtx 5090. the arms:
  - l1, one local worker;
  - la, separate lane contexts;
  - lb-text, a shared blackboard;
  - lb-kv, a shared kv cache (a time-boxed stretch behind a trigger; it needs a standard-attention model, because qwen3.8's deltanet layers have no kv cache to share).

  the headline is governed against shadow, plus test-gated tok/s.

## pre-registration

- **the starting evidence was pre-registered.** contraprova's [PREREG.md](results/swepro-lanes/PREREG.md) was written and committed before any paid request of the main run, on 2026-11-12 (contraprova commit 1ed672e); its probe has its own ([PREREG-probe.md](results/swepro-lanes/PREREG-probe.md)). the hashes it freezes refer to contraprova's paths, not to this repository's copy of the lane layer ([provenance](results/swepro-lanes/PROVENANCE.md)).
- **the local track is not pre-registered yet.** its plan commits a pre-registration before the main run ([docs/local-plan.md](docs/local-plan.md), step 4).

## honesty table

every claim this project makes, and what kind of evidence stands behind it today.

| claim | status | basis |
|---|---|---|
| lane contracts and a test-gated merge beat an ungated merge of the same lane outputs (haiku lanes, cloud api) | **measured** (pre-registered, n=37, by contraprova) | [results/swepro-lanes/main](results/swepro-lanes/main/README.md): 36/37 vs 28/37, discordant 8:0, p = 0.008, +21.6 points [+8.1, +35.1] |
| haiku lanes match contraprova's cascade in solve rate and cost | **measured** (inconclusive; n=37, both near ceiling) | 36/37 vs 34/37, +5.4 points [0.0, +13.5], p = 0.50; cost per solved task ratio 1.07 [0.62, 1.76] |
| symbol-level lanes fit a 24K per-lane prompt on these tasks, up to 8 lanes | estimated (offline, characters/3 calibrated against logged exact counts; no ci, not count_tokens, not the local tokenizer) | [results/symbol-lanes-fit](results/symbol-lanes-fit/README.md): 37/37 within 24K, largest lane median 9.9K |
| the lane layer behaves as it did in contraprova after the move | built | same logic, absolute imports and a module-routing hook; the full suite (`tests/test_lanes.py`, `tests/test_route.py`, `tests/test_symbols.py`) passed, 54 of 54, at 8729726 in a fresh venv with contraprova at 403caf2. it was run in the contraprova working session, because this session cannot execute contraprova |
| symbol-level lanes solve as many tasks as whole-file lanes | **hypothesis** | la with symbol lanes vs the api study's file lanes, same tasks |
| governed beats shadow with a local 27b lane worker | **hypothesis** | la vs la-shadow on the 37 tasks, one rtx 5090 |
| parallel local lanes beat one local worker in solve rate or wall time | **hypothesis** | la vs l1 |
| a shared text blackboard beats separate lane contexts | **hypothesis** | lb-text vs la |
| a shared kv cache (hogwild!-style) works under governance | **hypothesis** (stretch) | lb-kv on the probe tasks against a matched la on the same model, exploratory |
| test-gated tok/s on one rtx 5090 is a useful fraction of raw tok/s | **hypothesis** | both reported per arm |
| results generalise beyond swe-bench pro | **hypothesis** | out of scope for now |

rows move from hypothesis or estimated to measured only when a result with its confidence interval is committed under `results/`.

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

the logs, reports and analyses are under [`results/`](results): `swepro-lanes` is contraprova's study, copied unchanged ([provenance](results/swepro-lanes/PROVENANCE.md)); `symbol-lanes-fit` is this project's $0 fit study. the logs hold `contents_sha256` fields, never repository file contents. `contraprova verify results/swepro-lanes/main/log.jsonl` checks the chain and replays every event.

## layout

- `src/parataxis/lanes.py`, `lanes_detect.py`: the lane layer (planner, interface board, governed and shadow merges, blame, ladder, detectors), moved from contraprova 403caf2 with its history.
- `src/parataxis/run.py`: the harness command line, routed to parataxis's lanes.
- `src/parataxis/symbols.py`: symbol-level units, lane views, packing and the span scope gate.
- `scripts/fit_symbol_lanes.py`: the fit study.
- `results/`: committed evidence. `swepro-lanes` is from contraprova; `symbol-lanes-fit` is this project's.
- `docs/design.md`: the local track. `docs/local-plan.md`: the plan, benchmark choice and cost.

## licence

apache-2.0 ([LICENSE](LICENSE)), as contraprova.

the pictures in `assets/readme/` are drawn with the aphes.ist readme kit and embed subsets of Aphesis Script (SIL Open Font License 1.1, reserved font name "Aphesis Script") and Special Elite (apache-2.0, © 2010 Astigmatic), and the project's icon, a mark of aphesist's that is not covered by this project's licence.
