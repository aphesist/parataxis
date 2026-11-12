"""``python -m parataxis.run``: contraprova's harness command line, with parataxis's lane layer.

Importing :mod:`parataxis.lanes` first registers it under ``contraprova.harness.lanes``, so arm La
runs this repository's lanes. Every argument goes to ``contraprova.harness.run.main`` unchanged,
for example ``--benchmark swepro --lanes --split lanes-probe --arms La --dry-solve all``.
"""

from __future__ import annotations

import sys

import parataxis.lanes  # noqa: F401  (must precede the harness import)


def main(argv: list[str] | None = None) -> int:
    from contraprova.harness.run import main as harness_main

    return harness_main(argv)


if __name__ == "__main__":
    sys.exit(main())
