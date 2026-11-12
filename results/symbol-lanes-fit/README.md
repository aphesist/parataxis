# symbol-level lanes: fit on the 37 lanes-main tasks ($0)

> do symbol-level lanes fit a local model's window when a task is split into up to 8 lanes?

> **status:** counted.
> - **counts:** every lane prompt's own-file part was counted with the free count_tokens endpoint (`claude-haiku-5-5`'s tokenizer), and the shared part is the exact count the api study logged.
> - **no spend:** no model ran and nothing was paid for.
> - **tokenizer:** these are claude-tokenizer counts, not the local model's.
>
> `fit-counted.json` holds the exact counts, and `fit.json` the earlier offline estimate (characters / 3, calibrated per task).

- **run:** `python scripts/fit_symbol_lanes.py --count-tokens` for the exact counts (see [provenance](#provenance-of-the-exact-counts)); without the flag, the offline estimate. the defaults are `--target 24000 --max-lanes 8 --board-tokens 400 --split-class-lines 120`. it reads `results/swepro-lanes/main/log.jsonl` and fetches each task's scope files at its base commit from raw.githubusercontent.com into `data/sources/` (gitignored, never committed). each json file holds the summary and one row per task: unit names and token counts, no file contents.
- **tasks:** the 37 tasks of the pre-registered lanes-main run (python and javascript/typescript; ansible, openlibrary, qutebrowser, nodebb, element-web).

## how a lane prompt is counted

- **the shared part:** the exact lead-prompt count the api study logged (`d_lead`: statement, requirements, interface, the outline of every scope file, visible test names), plus 400 tokens for the lane contract and the interface board. median 5.8K, p90 9.6K. this is above the ~4K median the api study measured for its lanes' shared part, because the lead prompt outlines every file. it is conservative.
- **the lane's own files:** each file it owns spans in, as a lane view: the owned spans in full, every other unit reduced to its first line and an elision marker, and module-level lines (imports, constants) kept.
- **calibration** (the estimate only): per task, `d_worker` (exact count_tokens of the single-worker prompt) ÷ contraprova's characters/3 estimate of the same prompt. median 1.09 [0.94, 1.24 across tasks]. as a check, the fetched scope files plus the shared part come to 0.99 to 1.20 times `d_worker` (median 1.06). the excess is the outline of the files, counted once in the shared part and again as file bodies, so the fetch is complete and the estimate errs high.

## three ways to split a task

1. **whole-file lanes:** one lane per file the final governed merge touched, which is the api study's ownership unit at full fan-out.
2. **symbol lanes on the touched units:** the units (function, class, method of a class over 120 lines, or a block of about 60 lines in a non-code file) that the final governed merge changed. the lane count is the number of units, capped at 8, packed largest first. this knows where the edit lands, so it is an optimistic planner.
3. **symbol lanes covering every unit:** all units of every scope file in 8 lanes, with no knowledge of the edit. this is the pessimistic bound.

## results

exact counts (`fit-counted.json`):

| | lanes per task: median (max) | largest lane prompt: median / p90 / max | tasks where every lane ≤ 16K / 24K / 32K | largest lane's share of the code: median / p90 |
|---|---|---|---|---|
| whole-file lanes (touched files) | 4 (11) | 18.8K / 38.2K / 43.8K | 16 / 20 / 29 of 37 | 0.60 / 0.94 |
| symbol lanes (touched units) | 6 (8) | 10.2K / 13.5K / 17.1K | 35 / **37** / 37 of 37 | 0.42 / 0.79 |
| symbol lanes (every unit, 8 lanes) | 8 (8) | 15.8K / 20.2K / 21.6K | 20 / **37** / 37 of 37 | 0.15 / 0.17 |

- **every task fits a 24K per-lane target with symbol lanes**, even when the lanes cover every unit of the scope. with whole-file lanes, 17 of 37 tasks have a lane over 24K, and the largest is 43.8K.
- **the estimate held.** the offline estimate (`fit.json`) put the medians of the largest lane at 18.8K, 9.9K and 15.3K. against the exact counts that is 0.3% high for whole-file lanes, 2.2% low for touched-unit lanes and 3.0% low for every-unit lanes. no task changed its 24K verdict.
- **code shares are by characters.** the share columns are computed from characters, in both files.
- **the lane count follows the work.** touched units per task: median 6, p90 14, max 20. 12 of 37 tasks reach the cap of 8 lanes, and one task has a single unit.
- **one unit can still dominate.** with symbol lanes on the touched units, the largest lane holds a median 42% of the owned code, and 79% at p90. tasks whose edit sits in one large function stay narrow. "code share" here is over the touched units, and for whole-file lanes over the touched files, so the two rows have different denominators.
- **non-code files needed their own units.** before line blocks were added, 3 tasks had a lane over 24K because a whole asciidoc, yaml or xml file was one unit (`doc/help/commands.asciidoc`, `lib/ansible/config/base.yml`, `managed-schema.xml`).

## what this does not show

- **that lanes this narrow still solve the task.** a lane that sees one method and outlines of the rest may miss context a whole-file lane had. only a run with a solve rate, governed against shadow, can show that.
- **local-model token counts.** a local model's tokenizer differs from claude's. the local pre-flight re-counts with the local model's tokenizer before anything runs.
- **output.** a local window must hold the prompt and the lane's output. a lane's edit is usually a few hundred to a few thousand tokens, but a reasoning model's thinking adds to that, so budget the window as prompt + output + thinking.

## running the exact count (needs an api key)

```sh
git clone https://github.com/aphesist/parataxis && cd parataxis
python -m venv .venv && . .venv/bin/activate && pip install -e .   # installs contraprova at the pinned commit
python scripts/fit_symbol_lanes.py --count-tokens                   # writes results/symbol-lanes-fit/fit-counted.json
```

- **what it counts.** it uses the free count_tokens endpoint through contraprova's client, with `claude-haiku-5-5` as the lane worker's tokenizer. it counts each lane's own-file part exactly (its lane views as the lane sees them) and, for whole-file lanes, every touched file, taking the largest by tokens. the shared part stays the exact logged `d_lead` plus 400 tokens for the board. the estimate in `fit.json` is left untouched.
- **requirements.** the key comes from `PROJECTS_ANTHROPIC_KEY` or `ANTHROPIC_API_KEY`, read by contraprova and never printed. the scope files are fetched from raw.githubusercontent.com, or read from `data/sources/` if they are already cached.
- **cost.** about 700 requests, all free; the endpoint is rate-limited, not billed.

## provenance of the exact counts

- **who ran it:** the contraprova working session ran it on 2026-11-12, because this session has no api key and cannot execute contraprova. the file was relayed here, and both its sha256 values were checked on arrival: the compact form `47e72ed7…27ff`, and the written file `6744b08fdf40f32a41978a7d53a37ebf01eec455a0e589f5debeedc1ca304f57`.
- **code:** parataxis `2786c2d2eb50761a4000a858126f8a857e014d9a` (fresh clone, fresh venv, `pip install -e ".[dev]"`), with contraprova installed at `403caf23e1f9321e0244f3805b00a177476df4e0`. that commit is the fix that counts every touched file for the whole-file lane.
- **command:** `python scripts/fit_symbol_lanes.py --count-tokens` with default arguments. it exited 0. `count_model` is `claude-haiku-5-5`, and `fit.json` was left unchanged.
- **sources:** raw.githubusercontent.com rate-limited the run (429), so `data/sources/` was seeded from an earlier parataxis run. that cache was filled from contraprova's `data/swepro/context`, which is byte-identical to the base-commit files. the 10 files the gold patches create are marked absent at base.
- **independent check.** a separate counter in the contraprova session (669 count_tokens calls at parataxis 8729726) counted the whole concatenated lane prompt: lead system, lead context, brief request and the lane's views, plus 400. its shared part equalled the logged `d_lead` on 37 of 37 tasks. this file's per-task maxima minus that counter's:
  - whole-file lanes: +2 on 37 of 37;
  - touched units: +2 on 37 of 37;
  - every unit: +2 to +11 (+2 on 9, +5 on 14, +8 on 11, +11 on 3).

  the difference is message framing.
- **the fix it confirms:** before 2786c2d, the counted whole-file maximum on NodeBB-a5afad27 was 8,715, from the longest file by characters, a json file. it is now 9,664, from `src/messaging/index.js`, against 9,662 from the independent counter. the summary is otherwise identical to a pre-fix run at 1410d1e.
