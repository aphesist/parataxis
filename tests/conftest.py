"""Import the lane layer before any test module imports contraprova's harness, so contraprova's
SWE-bench Pro harness runs parataxis's lanes, not its own frozen copy (see parataxis.lanes)."""

import parataxis.lanes  # noqa: F401
