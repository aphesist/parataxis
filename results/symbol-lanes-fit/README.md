# symbol-level lanes: fit on the 37 lanes-main tasks ($0, estimated)

> do symbol-level lanes fit a local model's window when a task is split into up to 8 lanes?

> **status:** an offline estimate. no model ran, nothing was paid for, and count_tokens was not called (this session has no api key). token counts are characters / 3, calibrated per task against the exact counts the api study logged. these are claude-tokenizer counts, not the local model's.

- **run:** `python scripts/fit_symbol_lanes.py` (defaults: `--target 24000 --max-lanes 8 --board-tokens 400 --split-class-lines 120`). it reads `results/swepro-lanes/main/log.jsonl` and fetches each task's scope files at its base commit from raw.githubusercontent.com into `data/sources/` (gitignored, never committed). `fit.json` holds the summary and one row per task: unit names and token counts, no file contents.
- **tasks:** the 37 tasks of the pre-registered lanes-main run (python and javascript/typescript; ansible, openlibrary, qutebrowser, nodebb, element-web).

## how a lane prompt is counted

- **the shared part:** the exact lead-prompt count the api study logged (`d_lead`: statement, requirements, interface, the outline of every scope file, visible test names), plus 400 tokens for the lane contract and the interface board. median 5.8K, p90 9.6K. this is above the ~4K median the api study measured for its lanes' shared part, because the lead prompt outlines every file. it is conservative.
- **the lane's own files:** each file it owns spans in, as a lane view: the owned spans in full, every other unit reduced to its first line and an elision marker, and module-level lines (imports, constants) kept.
- **calibration:** per task, `d_worker` (exact count_tokens of the single-worker prompt) ÷ contraprova's characters/3 estimate of the same prompt. median 1.09 [0.94, 1.24 across tasks]. as a check, the fetched scope files plus the shared part come to 0.99 to 1.20 times `d_worker` (median 1.06). the excess is the outline of the files, counted once in the shared part and again as file bodies, so the fetch is complete and the estimate errs high.

## three ways to split a task

1. **whole-file lanes:** one lane per file the final governed merge touched, which is the api study's ownership unit at full fan-out.
2. **symbol lanes on the touched units:** the units (function, class, method of a class over 120 lines, or a block of about 60 lines in a non-code file) that the final governed merge changed. the lane count is the number of units, capped at 8, packed largest first. this knows where the edit lands, so it is an optimistic planner.
3. **symbol lanes covering every unit:** all units of every scope file in 8 lanes, with no knowledge of the edit. this is the pessimistic bound.

## results

| | lanes per task: median (max) | largest lane prompt: median / p90 / max | tasks where every lane ≤ 16K / 24K / 32K | largest lane's share of the code: median / p90 |
|---|---|---|---|---|
| whole-file lanes (touched files) | 4 (11) | 18.8K / 37.4K / 43.6K | 15 / 20 / 29 of 37 | 0.60 / 0.94 |
| symbol lanes (touched units) | 6 (8) | 9.9K / 13.3K / 16.9K | 35 / **37** / 37 of 37 | 0.42 / 0.79 |
| symbol lanes (every unit, 8 lanes) | 8 (8) | 15.3K / 19.7K / 20.1K | 22 / **37** / 37 of 37 | 0.15 / 0.17 |

- **every task fits a 24K per-lane target with symbol lanes**, even when the lanes cover every unit of the scope. with whole-file lanes, 17 of 37 tasks have a lane over 24K, and the largest is 43.6K.
- **the lane count follows the work.** touched units per task: median 6, p90 14, max 20. 12 of 37 tasks reach the cap of 8 lanes, and one task has a single unit.
- **one unit can still dominate.** with symbol lanes on the touched units, the largest lane holds a median 42% of the owned code, and 79% at p90. tasks whose edit sits in one large function stay narrow. "code share" here is over the touched units, and for whole-file lanes over the touched files, so the two rows have different denominators.
- **non-code files needed their own units.** before line blocks were added, 3 tasks had a lane over 24K because a whole asciidoc, yaml or xml file was one unit (`doc/help/commands.asciidoc`, `lib/ansible/config/base.yml`, `managed-schema.xml`).

## what this does not show

- **that lanes this narrow still solve the task.** a lane that sees one method and outlines of the rest may miss context a whole-file lane had. only a run with a solve rate, governed against shadow, can show that.
- **local-model token counts.** a local model's tokenizer differs from claude's. the local pre-flight re-counts with the local model's tokenizer before anything runs.
- **output.** a local window must hold the prompt and the lane's output. a lane's edit is usually a few hundred to a few thousand tokens, but a reasoning model's thinking adds to that, so budget the window as prompt + output + thinking.
- **count_tokens.** the free endpoint was not called, because there is no api key here. the per-task calibration against logged exact counts stands in for it, and the script's numbers are estimates until a count_tokens or local-tokenizer pass replaces them.

## the exact count (for a session with an api key)

```sh
git clone https://github.com/aphesist/parataxis && cd parataxis
python -m venv .venv && . .venv/bin/activate && pip install -e .   # installs contraprova at the pinned commit
python scripts/fit_symbol_lanes.py --count-tokens                   # writes results/symbol-lanes-fit/fit-counted.json
```

- **what it counts.** it uses the free count_tokens endpoint through contraprova's client, with `claude-haiku-5-5` as the lane worker's tokenizer. it counts each lane's own-file part exactly (its lane views as the lane sees them) and, for whole-file lanes, every touched file, taking the largest by tokens. the shared part stays the exact logged `d_lead` plus 400 tokens for the board. the estimate in `fit.json` is left untouched.
- **requirements.** the key comes from `PROJECTS_ANTHROPIC_KEY` or `ANTHROPIC_API_KEY`, read by contraprova and never printed. the scope files are fetched from raw.githubusercontent.com, or read from `data/sources/` if they are already cached.
- **cost.** about 700 requests, all free; the endpoint is rate-limited, not billed.
