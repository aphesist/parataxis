"""Import the lane layer before any test module imports contraprova's harness, so contraprova's
SWE-bench Pro harness runs parataxis's lanes, not its own frozen copy (see parataxis.lanes).

Without contraprova installed, the modules that need it fail on their own imports; the pure
modules (parataxis.symbols) still test."""

try:
    import parataxis.lanes  # noqa: F401
except ModuleNotFoundError as exc:  # pragma: no cover - only without the pinned dependency
    if not (exc.name or "").startswith("contraprova"):
        raise
