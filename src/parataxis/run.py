"""``python -m parataxis.run``: contraprova's harness command line, with parataxis's lane layer.

Importing :mod:`parataxis.lanes` first registers it under ``contraprova.harness.lanes``, so arm La
runs this repository's lanes. Every other argument goes to ``contraprova.harness.run.main``
unchanged, for example ``--benchmark swepro --lanes --split lanes-probe --arms La --dry-solve all``.
The local track's arms ``L1`` and ``Lb`` (:mod:`parataxis.arms`) are available to ``--arms``.

``--local`` runs the lanes on the local model (the local track): arm La's ladder becomes
:data:`parataxis.lanes.LOCAL_LADDER` (local lane, then one local repair; no cloud escalation) with
:data:`~parataxis.lanes.LOCAL_LANE_MAX_TOKENS` per lane, ``--max-lanes`` may go up to 8, and the
local model is priced at $0, and lanes may own units of a file (symbol-level lanes). ``--concurrency N`` sends up to N local lane requests at once (default
8). Pair it with ``--client parataxis.local:LocalRoleClients`` (local lanes
over HTTPS to the pod's vLLM, the Opus planner through the Claude API).
"""

from __future__ import annotations

import functools
import sys

import parataxis.lanes as lanes  # noqa: F401  (must precede the harness import)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    concurrency = 8
    if "--concurrency" in args:
        i = args.index("--concurrency")
        concurrency = int(args[i + 1])
        del args[i:i + 2]
    if "--local" in args:
        args.remove("--local")
        import parataxis.local  # noqa: F401  (registers the local model's $0 price)
        from contraprova.harness import swepro_run

        swepro_run.LaneConfig = functools.partial(lanes.LaneConfig, ladder=lanes.LOCAL_LADDER,
                                                  lane_max_tokens=lanes.LOCAL_LANE_MAX_TOKENS,
                                                  concurrency=concurrency, symbol_lanes=True)
    from contraprova.harness.run import main as harness_main

    from .arms import install

    install()  # arms L1 and Lb

    return harness_main(args)


if __name__ == "__main__":
    sys.exit(main())
