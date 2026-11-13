"""Code and prompt hashes for the pre-registration's part b (the freeze).

    python scripts/freeze_hashes.py --out results/local-calib/hashes.json

Records the git commit, the sha256 of every tracked file under ``src/`` and ``scripts/``, the pinned
contraprova commit (from pyproject.toml), and the sha256 of every prompt constant the local arms send:
``parataxis.lanes`` (planner, lanes, blackboard), contraprova's ``swepro_arms`` (worker, retry,
edit format and repair turns, used by L1 and by the lanes' edit repair) and ``parataxis.unit_edits``,
read after :func:`parataxis.unit_edits.install` when ``--edit-format units`` (the default), so the
hashes are of the texts as sent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prompts(mod) -> dict[str, str]:
    return {n: sha(getattr(mod, n).encode()) for n in sorted(dir(mod))
            if n.isupper() and isinstance(getattr(mod, n), str) and len(getattr(mod, n)) > 80}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--edit-format", choices=("units", "search"), default="units",
                    help="hash the prompts as sent with this edit format (units: the local track's, b.6)")
    args = ap.parse_args(argv)
    import parataxis.lanes as lanes
    from contraprova.harness import swepro_arms

    from parataxis import unit_edits

    if args.edit_format == "units":
        unit_edits.install()

    git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    files = git("ls-files", "src", "scripts").split()
    pin = re.search(r"github.com/aphesist/contraprova@([0-9a-f]{40})",
                    (ROOT / "pyproject.toml").read_text())
    out = {
        "commit": git("rev-parse", "HEAD").strip(),
        "dirty": bool(git("status", "--porcelain", "--", "src", "scripts").strip()),
        "contraprova_pin": next(g for g in pin.groups() if g) if pin else None,
        "files": {f: sha((ROOT / f).read_bytes()) for f in files if (ROOT / f).is_file()},
        "edit_format": args.edit_format,
        "prompts": {"parataxis.lanes": prompts(lanes), "contraprova.harness.swepro_arms": prompts(swepro_arms),
                    "parataxis.unit_edits": prompts(unit_edits),
                    "ProHarness.worker_system": sha(swepro_arms.ProHarness.worker_system.encode())},
    }
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"commit": out["commit"], "dirty": out["dirty"], "files": len(out["files"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
