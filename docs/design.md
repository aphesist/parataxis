# design: the local track

> parataxis (παράταξις, "placing side by side"): many lanes working on one coding task at once, on one gpu, under contracts.

## the question

> on one consumer gpu, do parallel local lanes under typed contracts and a test-gated merge solve more tasks than the same lanes' outputs merged without governance, and how many test-passing tokens per second does that buy?

a viral demo (tensorfold) ran 8 lanes at about 700 tok/s on one rtx 5090, with no quality check. raw tok/s says nothing about whether the merged code works. parataxis measures the merged result:

- **the headline is a paired contrast.** the governed merge is set against an ungated **shadow merge** of the same lane outputs, so both see identical tokens and the only difference is the governance.
- **throughput is gated.** **test-gated tok/s** counts only tokens that end in a patch passing the task's tests.

## what the api study taught

contraprova ran contract lanes through the cloud api, pre-registered, on 37 fresh multi-file swe-bench pro tasks ([results/swepro-lanes](../results/swepro-lanes/main/README.md), produced by contraprova at 403caf2). haiku 5.5 lanes, an opus-low planner, and a per-lane ladder of haiku repair → sonnet → opus (never fable).

- **governance pays.** governed 36/37 against shadow 28/37: discordant 8:0, exact mcnemar p = 0.008, +21.6 points [+8.1, +35.1].
- **it costs no more than the cascade.** lanes 36/37 against contraprova's cascade 34/37, at about the same cost per solved task (ratio 1.07 [0.62, 1.76]).
- **the planner is half the bill** (50% of la's dollars). on a local gpu the lanes are nearly free, so a cloud planner would be most of the cost.
- **the planner never chose more than 2 lanes.** lanes owned whole files, and the largest lane held a median 80% of a task's code, because one file usually dominates. **wide fan-out needs lanes below file level.**
- **a lane prompt is mostly its own files.** about 82% of a lane prompt is its own files in full. the shared part (statement, requirements and interface; outlines of the other files; the board; test names) is a median ~4K tokens, ~7K at p90.
- **blame rule 2** (a failing test's stem or a traceback names a lane's file) never fired on real output. rules 1 and 3 did all the blaming.
- **the sonnet reviewer made 2 false blocks**, both on merges that pass the score tests. a same-vendor reviewer is a weak independent check.

the api study does not show any of these:

- a local model as the lane worker;
- throughput or concurrency on one gpu;
- a shared window (a shared blackboard or a shared kv cache);
- fan-out wider than 2 lanes.

those gaps are the local track.

## mechanism

parataxis keeps contraprova's engine and changes only what the local setting needs. contraprova provides:

- the event log (append-only, hash-chained, with a single validating writer);
- the kernel, the gates, the statistics, the pricing;
- the swe-bench pro harness and verifier.

the lane layer (`src/parataxis/lanes.py`, `lanes_detect.py`) was moved from contraprova and registers itself under contraprova's module names, so the harness runs parataxis's copy.

1. **contract units below file level** (`src/parataxis/symbols.py`). a unit is a function, a class, or a method of a class over 120 lines. in yaml, xml, docs or unparsable code, a unit is a block of about 60 lines. each lane owns a set of units:
   - it sees them in full, plus an outline of the rest of its files (other units reduced to their first line, imports and module constants kept);
   - it sees the shared part: statement, requirements, interface, the outline of every scope file, its contract, the board and its visible tests.
2. **lane count from the contract.** the planner names the units to change. the lane count is the number of units, capped at 8, and units are packed largest first under a per-lane token target (24K by default).
3. **interface round.** this is a kernel step with no model call. the planner's frozen signatures and every symbol in the task's interface field go on the board, together with each lane's provides and needs. a lane that needs a change writes an interface request, which is logged, rejected and counted.
4. **scope gate on spans.** every changed line of a lane's edit must fall inside a span it owns. an insertion may also sit directly after an owned span, so a lane can add a helper below its function. created files must be in the lane's contract. out-of-scope edits are rejected before the merge and counted as clashes, as in the api study.
5. **governed merge.** the lanes' edits are merged and the merge is gated: `T0.scope`, `T0.edits`, `T0.interfaces`, visible tests, private tests. there is no same-vendor reviewer by default, because of the 2 false blocks above.
6. **blame, repair, escalation.** blame works as in the api study (rule 1 direct; rule 2 tests and tracebacks; rule 3 every lane, with widening when the same lanes are blamed again). the local ladder is: local lane → local repair with the gate feedback → (optional, paid) cloud escalation. only blamed lanes move.
7. **shadow merge.** the lanes' first replies are concatenated with no contracts, no gates and no repair, then scored once by the verifier. it costs no tokens.
8. **counted coordination failures.** contraprova's detectors (`lanes_detect.py`) count overlapping scopes, unresolved uses, interface-output clashes, duplicated work, scope violations, unattributable failures, wasted lanes and regressions after escalation. each one is a `coordination.detected` event.

## arms

| arm | what runs | what it isolates |
|---|---|---|
| **L1** | one local worker on the whole task: the cascade's worker prompt, the same model, gate and repair | is parallelism worth anything over one local worker? |
| **La** | N local lanes, separate contexts, symbol-level contracts, governed merge | the governed lanes; **La vs La-shadow is the primary contrast** |
| **La-shadow** | derived from La's first replies, ungated | no extra tokens |
| **Lb-text** | La plus a shared text blackboard: lanes share one prompt prefix (the shared part and the board), and between rounds each lane's interface notes and progress are appended to the board, so every lane's next step sees them. prefix caching serves the shared prefix once | does a shared window help coordination? |
| **Lb-kv** (stretch, time-boxed) | hogwild!-style: lanes attend to each other's kv cache while they generate | whether live shared attention beats a turn-based board; needs a custom inference loop, not stock vllm |

l1 and la answer different questions:

- **la vs la-shadow** is the governance claim, carried to a local model.
- **la vs l1** is the parallelism claim: more solved tasks, or the same solved tasks sooner.

## serving

- **gpu:** a rented rtx 5090 (32 gb).
- **server:** vllm with continuous batching and automatic prefix caching, so the shared prefix is prefilled once per round.
- **model:** qwen3.8-27b in nvfp4 with multi-token prediction (mtp) for speculative decoding.
- **window:** the per-sequence context, set as `max_model_len`, must hold the prompt, the output and any thinking. the fit study ([results/symbol-lanes-fit](../results/symbol-lanes-fit/README.md)) puts every lane prompt of 8 symbol lanes under 20.1K claude tokens on all 37 tasks, with median 9.9K for touched-unit lanes. a 32K window leaves about 12K for output and thinking on the worst task. the local tokenizer differs from claude's, so the day-1 smoke test re-counts.
- **memory:** the weights take about half the card. what is left is kv cache, and N concurrent lanes × their context must fit in it. calibrating N measures this directly, instead of trusting a formula.

## metrics

- **primary:** la vs la-shadow solve rate on the score tests, paired by task, exact mcnemar, with a bootstrap ci for the paired difference.
- **test-gated tok/s:** the lane output tokens (thinking included) of tasks whose governed merge passes the score tests, divided by the wall-clock time of the whole arm, verifier time excluded and reported separately. raw tok/s (all output tokens ÷ the same wall time) is reported next to it, so the gap between the two is visible.
- **secondary:**
  - la vs l1 (solve rate and wall time);
  - lb-text vs la;
  - solve rate by lane count;
  - coordination failures per task, by kind;
  - blame-rule firing counts;
  - gate replay quality (blocked merges scored on the score tests);
  - gpu-hours per solved task.

## what stays from the api study, and what changes

- **stays:**
  - the event types;
  - the blame rules, widening included;
  - the detectors;
  - the shadow merge;
  - the analysis (`contraprova report --lanes`);
  - pre-registration before any spend.
- **changes:**
  - lanes own symbols, not files;
  - up to 8 lanes, with the count from the contract units;
  - a per-lane token target;
  - the local ladder;
  - no t2 reviewer by default;
  - the local model's own tokenizer for pre-flight counts.

the plan, the benchmark choice and the costs are in [local-plan.md](local-plan.md).
