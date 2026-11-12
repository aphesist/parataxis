"""The fit study's whole-file lane size: counted, the largest by tokens, not by characters."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fit_symbol_lanes", ROOT / "scripts/fit_symbol_lanes.py")
fit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fit)


def test_counted_whole_file_lane_takes_the_max_over_every_file():
    sources = {"a.json": '{"k": "v"}\n' * 400, "b.js": "f(x);\n" * 300}  # a.json has more characters
    assert len(sources["a.json"]) > len(sources["b.js"])

    def count(text):  # a fake tokenizer where JSON is cheap: one token per line, JS one per char
        return text.count("\n") if '"k"' in text else len(text)

    seen = []

    def counting(text):
        seen.append(text)
        return count(text)

    got = fit.largest_file_tokens(sorted(sources), sources, counting, lambda n: n)
    assert got == count(f"b.js\n```\n{sources['b.js']}\n```")
    assert len(seen) == 2  # every touched file counted


def test_estimated_whole_file_lane_uses_the_largest_by_characters():
    sources = {"a.py": "x" * 300, "b.py": "y" * 30}
    assert fit.largest_file_tokens(["a.py", "b.py"], sources, None, lambda n: 2 * n) == 2 * 100
    assert fit.largest_file_tokens([], sources, None, lambda n: n) == 0
