# backlog

work the project means to do, not yet started. each entry says why, how and when to start.

## an inference engine of its own

> not now. the study runs on stock vllm first.

- **why:**
  - stock vllm is expected to give up about 20 to 45% of raw speed against tensorfold's engine (an estimate from the local-track research, see [design.md](design.md));
  - a lane-aware engine could close that gap, and add what generic servers lack.
- **the path, in stages; each stage is worth having on its own:**
  1. **a lane-aware scheduler**, as a vllm or sglang plugin:
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
