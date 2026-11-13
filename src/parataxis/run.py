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

``--edit-format units|search`` picks the workers' edit format. ``units`` (the default with ``--local``,
PREREGISTRATION.md b.6) adds UNIT/AFTER blocks that replace a whole function, method or class by name
(:mod:`parataxis.unit_edits`); ``search`` is contraprova's SEARCH/REPLACE format alone, as calibrated
first. With ``--local --dry-run`` the offline planner (:mod:`parataxis.dry`) plans one lane per unit the
gold patch touches, and each lane answers with its own units' share, in unit blocks with ``units``.
"""

from __future__ import annotations

import functools
import sys

import parataxis.lanes as lanes  # noqa: F401  (must precede the harness import)

# The lane pre-flight's expected planner output per plan. Calibration's 12 Opus plans fit
# 957 + 209 x k output tokens (k = lanes). Under the units rule (one lane per touched unit group,
# up to 8; PREREGISTRATION.md b.5) the dry planner gives k = 8 on every probe task, so 957 + 209 x 8,
# rounded up. It was 1,199 (the API study's median, at k of 1 to 4) for the first calibration.
LOCAL_PLAN_OUT = 2600


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    concurrency = 8
    if "--concurrency" in args:
        i = args.index("--concurrency")
        concurrency = int(args[i + 1])
        del args[i:i + 2]
    edit_format = None
    if "--edit-format" in args:
        i = args.index("--edit-format")
        edit_format = args[i + 1]
        del args[i:i + 2]
        if edit_format not in ("search", "units"):
            raise SystemExit("--edit-format must be search or units")
    local = "--local" in args
    if local:
        edit_format = edit_format or "units"
        args.remove("--local")
        import parataxis.local  # noqa: F401  (registers the local model's $0 price)
        from contraprova.harness import swepro_run

        # the lane pre-flight's expected planner output (LOCAL_PLAN_OUT) instead of the plan's assumed
        # 4,000. The budget guard still caps the real spend before every request.
        swepro_run.LaneAssumptions = functools.partial(lanes.LaneAssumptions, plan_out=LOCAL_PLAN_OUT)
        swepro_run.LaneConfig = functools.partial(lanes.LaneConfig, ladder=lanes.LOCAL_LADDER,
                                                  lane_max_tokens=lanes.LOCAL_LANE_MAX_TOKENS,
                                                  concurrency=concurrency, symbol_lanes=True,
                                                  task_seconds=600.0)
    if edit_format == "units":
        from . import unit_edits

        unit_edits.install()
    if local and "--dry-run" in args:
        from contraprova.harness import swepro_run

        from .dry import fake_client

        # offline planner answers with one lane per touched unit; lanes with their own units' share
        swepro_run.ProFakeClient = fake_client(swepro_run.ProFakeClient, units=edit_format == "units")
    from contraprova.harness.run import main as harness_main

    from .arms import install

    install()  # arms L1 and Lb

    return harness_main(args)


if __name__ == "__main__":
    sys.exit(main())
