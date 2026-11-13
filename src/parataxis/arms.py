"""The local track's own arms on contraprova's SWE-bench Pro harness (PREREGISTRATION.md, "arms").

- ``L1``: one local worker on the whole task: the cascade's worker prompt and SEARCH/REPLACE format
  (with contraprova's one edit-repair turn), the task's gates, then one local retry with the gate
  feedback. A change still blocked after the retry is not shipped (unsolved), as in La.
- ``Lb``: Lb-text, the shared blackboard (see :mod:`parataxis.lanes`, ``run_la(..., board=True)``).

:func:`install` registers them with the harness: the arm names join ``PRO_ARMS`` and
``ProHarness.run_task`` dispatches them. ``python -m parataxis.run`` calls it.
"""

from __future__ import annotations

from contraprova.harness.arms import TaskContext

from .lanes import LOCAL_LANE_MAX_TOKENS, LOCAL_MODEL

L1_ARM = "L1"
LB_ARM = "Lb"
LOCAL_ARMS = (L1_ARM, LB_ARM)


L1_TASK_SECONDS = 600.0  # the pre-registered 10-minute task cap: no retry starts after it


def run_l1(h, ex, ts, split: str = "", *, model: str = LOCAL_MODEL, max_tokens: int = LOCAL_LANE_MAX_TOKENS,
           task_seconds: float | None = L1_TASK_SECONDS) -> bool:
    import time

    started = time.monotonic()
    tid = f"{L1_ARM}:{ex.id}"
    contract = h.contract(tid, ex)
    h.create(L1_ARM, tid, ex, split, max_attempts=2,
             contract={"allowed": list(contract.allowed), "protected": list(contract.protected)})
    base = h.worker_prompt(ex, ts)
    sub = h._work(L1_ARM, tid, ex, model, base, 1, None, max_tokens=max_tokens, extra={"tier": "local"},
                  extra_tags={"tier": "local"})
    ctx = TaskContext(L1_ARM, tid, ex, ts, model, 1, contract, split, h.t2_reviewer(L1_ARM, tid, ex))
    passed, results = h._gate(sub, ctx)
    capped = bool(task_seconds) and time.monotonic() - started >= task_seconds
    if not passed and not capped:
        feedback = "\n".join(f"[{r.gate}] {r.reason}" for r in results if r.verdict != "pass")
        retry = h.retry_prompt(base, sub.files, feedback, ex)
        sub = h._work(L1_ARM, tid, ex, model, retry, 2, None, max_tokens=max_tokens,
                      extra={"tier": "local-retry"}, extra_tags={"tier": "local-retry"})
        ctx = TaskContext(L1_ARM, tid, ex, ts, model, 2, contract, split, h.t2_reviewer(L1_ARM, tid, ex))
        passed, results = h._gate(sub, ctx)
    return h.outcome(L1_ARM, sub, ctx, h.evaluate(sub, ctx), shipped=passed, gate_passed=passed,
                     attempts=sub.attempt, **({"capped": True} if capped and not passed else {}))


def install() -> None:
    """Make contraprova's SWE-bench Pro harness and command line know arms L1 and Lb."""
    from contraprova.harness import swepro_arms, swepro_run

    for mod in (swepro_arms, swepro_run):
        mod.PRO_ARMS = tuple(dict.fromkeys((*mod.PRO_ARMS, *LOCAL_ARMS)))
    cls = swepro_arms.ProHarness
    if getattr(cls.run_task, "_parataxis", False):
        return
    original = cls.run_task

    def run_task(self, arm, ex, ts, split=""):
        if arm == L1_ARM:
            return run_l1(self, ex, ts, split)
        if arm == LB_ARM:
            from .lanes import run_la

            return run_la(self, ex, ts, split, board=True)
        return original(self, arm, ex, ts, split)

    run_task._parataxis = True  # type: ignore[attr-defined]
    cls.run_task = run_task
