"""parataxis: parallel lanes for one coding task, governed by contracts and a test-gated merge.

The engine (event log, kernel, gates, statistics, pricing, benchmark harness) is contraprova,
pinned in pyproject.toml. Importing this package does not import contraprova; the lane layer
(:mod:`parataxis.lanes`) does.
"""

__version__ = "0.1.0"
