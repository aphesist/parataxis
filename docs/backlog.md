# backlog

work the project means to do, not yet started. each entry says why, how and when to start.

## lanes that may edit what their change depends on

> next, before any local main run. the calibration's main finding points here.

- **why:**
  - at 6–8 lanes per task the local calibration solved fewer tasks than at 1–4 lanes;
  - the clashes associated with failure were scope violations (a lane's edit outside its units, undone) and unlisted units (an edit in a unit no lane owns) ([results/local](../results/local/README.md));
  - the span gate makes every lane's ownership exact, but a change often needs a few lines in a neighbouring unit.
- **how:**
  - a lane owns its units and may also edit the units its change depends on (callers, imports, the module-level lines of its files), declared in the plan or requested once during the interface round;
  - overlapping edits are arbitrated at merge time: identical edits merge, compatible ones are applied in plan order, and a true conflict is blamed and repaired, instead of being undone up front;
  - unlisted and out-of-scope edits stay counted, so the effect on coordination failures is measurable against the calibration's profile.
- **start when:** before any new local calibration. it is a $0 build, dry-run against the fake vllm and the gold patches.

## keeping the gpu busy during merge and verify

> next, together with the item above. it is stage 1 of the inference engine below.

- **why:**
  - aggregate throughput stayed flat at about 220–240 tok/s from 2 to 8 concurrent lanes, while the per-lane rate fell about 1/n;
  - between rounds the gpu idles while the harness merges, gates and runs the docker verifier, so the tail share reached 0.8;
  - the day-1 short-stream sweep (849 tok/s at 8 streams) shows the card itself scales.
- **how:**
  - pipeline the work: start the next task's planner-replayed lanes, or speculative repairs, while the current merge is verified;
  - schedule lanes across tasks so that the gpu always has requests;
  - this is the lane-aware scheduler of the engine backlog, stage 1 below.
- **start when:** with the decomposition item, before a new calibration; measured against the calibration's throughput table.

## an inference engine of its own

> not now. the study runs on stock vllm first.

- **why:**
  - stock vllm is expected to give up about 20 to 45% of raw speed against tensorfold's engine (an estimate from the local-track research, see [design.md](design.md));
  - a lane-aware engine could close that gap, and add what generic servers lack.
- **the path, in stages; each stage is worth having on its own:**
  1. **a lane-aware scheduler**, as a vllm or sglang plugin (see "keeping the gpu busy during merge and verify" above):
     - synchronised lane rounds;
     - the slowest lanes served first, to shorten the tail;
     - adaptive speculation depth.

     days of work, no gpu kernels.
  2. **shared-prefix attention**, computed once per round for all lanes (for example flashinfer's cascade attention), checked against qwen3.8's hybrid layers.
  3. **a full engine:**
     - nvfp4 kernels for blackwell;
     - paged attention;
     - gated deltanet linear-attention kernels;
     - tree-verified speculative decoding;
     - a batching scheduler.

     months of work.
- **constraints:**
  - **hardware:** developing it needs blackwell hardware. the owner's laptop rtx 4070 is ada: no fp4, and 8 gb.
  - **baseline:** it is measured against the stock-vllm baseline from the study.
  - **tensorfold:** tensorfold (apache-2.0) is studied and credited, never copied.
  - **governance:** the governance layer (contracts, merge, blame, shadow) stays engine-agnostic.
- **start when:** the vllm study has measured the real throughput gap.
