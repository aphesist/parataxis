"""Symbol-level lanes: a lane owns functions, classes or methods instead of whole files.

The API study (results/swepro-lanes) assigned whole files to lanes. One file usually dominates a
task, so the largest lane held a median 80% of the task's code and the planner never chose more
than 2 lanes. Wide fan-out on one GPU needs lanes below file level. This module provides:

- :func:`units` splits a source file into contract units (Python via ``ast``; JavaScript and
  TypeScript via a brace scanner over a copy with comments and string contents blanked). A class
  larger than ``split_class_lines`` is split into its methods plus a header unit.
- :func:`lane_view` renders what a lane sees of one of its files: the owned spans in full and the
  rest of the file as an outline (module-level lines kept, other units reduced to their first line
  and an elision marker).
- :func:`plan_symbol_lanes` packs units into at most ``max_lanes`` lanes, the count chosen from
  the number of contract units, balancing tokens (largest first) and reporting each lane's prompt
  size against a per-lane token target.
- :func:`scope_violations` is the scope gate: every changed line of a lane's edit must fall inside
  a span the lane owns (insertions may also sit directly after an owned span, for new helpers).

No contraprova import: the module is pure and testable on its own. Token counts here are
estimates (characters / ``chars_per_token``); the fit study calibrates them against exact counts
logged by the API study, and a ``count_tokens`` pre-flight replaces them before a paid run.
"""

from __future__ import annotations

import ast
import difflib
import math
import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

PY_EXT = (".py", ".pyi")
JS_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
ELIDED = "…"


@dataclass(frozen=True, order=True)
class Span:
    """Lines ``start``..``end`` (1-based, inclusive) of ``path``, defining ``name``."""

    path: str
    start: int
    end: int
    name: str = ""
    kind: str = ""  # function | class | class-header | method | block

    @property
    def unit_id(self) -> str:
        return f"{self.path}::{self.name}"

    @property
    def lines(self) -> int:
        return self.end - self.start + 1

    def contains(self, line: int) -> bool:
        return self.start <= line <= self.end


# ------------------------------------------------------------------ Python


def _py_start(node: ast.AST) -> int:
    decos = getattr(node, "decorator_list", None) or []
    return min([node.lineno] + [d.lineno for d in decos])


def python_units(path: str, source: str, *, split_class_lines: int = 120) -> list[Span]:
    tree = ast.parse(source)
    out: list[Span] = []

    def top(nodes: Iterable[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append(Span(path, _py_start(node), node.end_lineno, node.name, "function"))
            elif isinstance(node, ast.ClassDef):
                start, end = _py_start(node), node.end_lineno
                methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                if end - start + 1 > split_class_lines and methods:
                    first = _py_start(methods[0])
                    out.append(Span(path, start, first - 1, node.name, "class-header"))
                    for i, m in enumerate(methods):
                        m_end = m.end_lineno
                        # attribute lines between methods go with the method before them
                        nxt = _py_start(methods[i + 1]) - 1 if i + 1 < len(methods) else end
                        out.append(Span(path, _py_start(m), max(m_end, nxt), f"{node.name}.{m.name}", "method"))
                else:
                    out.append(Span(path, start, end, node.name, "class"))
            elif isinstance(node, (ast.If, ast.Try)):
                # conditional definitions at module level (if TYPE_CHECKING, try/except import)
                top(node.body)
                for h in getattr(node, "handlers", []):
                    top(h.body)
                top(node.orelse)

    top(tree.body)
    return sorted(out)


# ------------------------------------------------------------------ JavaScript / TypeScript


def blank_js(source: str) -> str:
    """Blank comments and the contents of string and template literals, keeping every newline, so
    braces inside them do not count. Template ``${...}`` contents are blanked too (approximate)."""
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = source.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif c == "/" and nxt == "*":
            j = source.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join(ch if ch == "\n" else " " for ch in source[i:j]))
            i = j
        elif c in "'\"`":
            j = i + 1
            while j < n and source[j] != c:
                if source[j] == "\\":
                    j += 1
                elif source[j] == "\n" and c != "`":
                    break
                j += 1
            seg = source[i + 1:j]
            closed = j < n and source[j] == c
            out.append(c + "".join(ch if ch == "\n" else " " for ch in seg) + (c if closed else ""))
            i = j + 1 if closed else j
        else:
            out.append(c)
            i += 1
    return "".join(out)


_ID = r"[A-Za-z_$][\w$]*"
_JS_DECL = [
    (re.compile(rf"^(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?:abstract\s+)?class\s+({_ID})"), "class"),
    (re.compile(rf"^(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s*({_ID})"), "function"),
    (re.compile(rf"^(?:export\s+)?(?:declare\s+)?(?:interface|enum|namespace)\s+({_ID})"), "block"),
    (re.compile(rf"^(?:export\s+)?type\s+({_ID})"), "block"),
    (re.compile(rf"^(?:export\s+)?(?:const|let|var)\s+({_ID})\s*(?::[^=]+)?=\s*(?:async\s+)?"
                r"(?:function\b|\([^)]*\)?|[A-Za-z_$][\w$]*\s*=>|React\.memo|forwardRef|\{|\[|class\b)"), "function"),
    (re.compile(rf"^((?:module\.)?exports(?:\.{_ID})?)\s*="), "function"),
    (re.compile(rf"^({_ID}(?:\.{_ID})+)\s*=\s*(?:async\s+)?(?:function\b|\(|{_ID}\s*=>)"), "function"),
]
_JS_METHOD = re.compile(
    r"^\s*(?:(?:public|private|protected|static|readonly|async|get|set|override|abstract)\s+)*"
    rf"\*?\s*#?({_ID})\s*(?:<[^>]*>)?\s*\(")
_JS_KEYWORDS = frozenset({"if", "for", "while", "switch", "catch", "return", "function", "else", "do", "try",
                          "with", "typeof", "new", "await", "yield", "case", "delete", "void", "throw", "super"})


def _js_extent(blank_lines: Sequence[str], i: int) -> int:
    """Index of the last line of the statement starting at line index ``i`` (0-based): the line
    where braces/brackets/parens opened since ``i`` close again, or the first line ending the
    statement if none open."""
    depth = 0
    opened = False
    for j in range(i, len(blank_lines)):
        b = blank_lines[j]
        for ch in b:
            if ch in "{[(":
                depth += 1
                opened = True
            elif ch in "}])":
                depth -= 1
        if opened and depth <= 0:
            return j
        if not opened and (b.rstrip().endswith(";") or (j > i and not b.strip())):
            return j
    return len(blank_lines) - 1


def js_units(path: str, source: str, *, split_class_lines: int = 120) -> list[Span]:
    blank = blank_js(source).split("\n")
    out: list[Span] = []
    i = 0
    while i < len(blank):
        line = blank[i]
        if not line.strip() or line[0] in " \t}":
            i += 1
            continue
        hit = next(((m.group(1), kind) for p, kind in _JS_DECL if (m := p.match(line))), None)
        if hit is None:
            i += 1
            continue
        name, kind = hit
        end = _js_extent(blank, i)
        start = i
        # leading decorators and doc comments belong to the declaration
        while start > 0 and source.split("\n")[start - 1].lstrip().startswith(("@", "*", "/**", "//")) \
                and not blank[start - 1].strip().endswith(("}", ";")):
            start -= 1
        if kind == "class" and end - start + 1 > split_class_lines:
            out.extend(_js_class_members(path, blank, start, i, end, name))
        else:
            out.append(Span(path, start + 1, end + 1, name, kind))
        i = end + 1
    return sorted(out)


def _js_class_members(path: str, blank: Sequence[str], start: int, decl: int, end: int, cls: str) -> list[Span]:
    members: list[tuple[int, int, str]] = []
    depth = 0
    for j in range(decl, end + 1):
        b = blank[j]
        if depth == 1:
            m = _JS_METHOD.match(b)
            if m and m.group(1) not in _JS_KEYWORDS:
                members.append((j, _js_extent(blank, j), m.group(1)))
        depth += b.count("{") - b.count("}")
    if not members:
        return [Span(path, start + 1, end + 1, cls, "class")]
    spans = [Span(path, start + 1, members[0][0], cls, "class-header")]
    for k, (s, e, name) in enumerate(members):
        nxt = members[k + 1][0] - 1 if k + 1 < len(members) else end
        spans.append(Span(path, s + 1, max(e, nxt) + 1, f"{cls}.{name}", "method"))
    return spans


# ------------------------------------------------------------------ files


def text_units(path: str, source: str, *, chunk_lines: int = 60) -> list[Span]:
    """Units of a file with no code structure (YAML, XML, docs, or code that does not parse):
    blocks of at least ``chunk_lines`` lines, cut at blank lines where possible, else at the
    next line once a block reaches twice that size. Named by their line range."""
    lines = source.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    if not lines:
        return [Span(path, 1, 1, "L1-1", "block")]
    n = len(lines)
    out: list[Span] = []
    start = 1
    for no in range(1, n + 1):
        size = no - start + 1
        at_break = not lines[no - 1].strip()
        if no == n or (size >= chunk_lines and at_break) or size >= 2 * chunk_lines:
            out.append(Span(path, start, no, f"L{start}-{no}", "block"))
            start = no + 1
    return out


def units(path: str, source: str, *, split_class_lines: int = 120, chunk_lines: int = 60) -> list[Span]:
    """Contract units of one file: functions, classes (or methods of a large class) for Python and
    JavaScript/TypeScript; line blocks (:func:`text_units`) for any other file, a file that does
    not parse, or code with no unit found."""
    try:
        if path.endswith(PY_EXT):
            found = python_units(path, source, split_class_lines=split_class_lines)
        elif path.endswith(JS_EXT):
            found = js_units(path, source, split_class_lines=split_class_lines)
        else:
            found = []
    except (SyntaxError, ValueError):
        found = []
    return found or text_units(path, source, chunk_lines=chunk_lines)


def unit_text(source: str, span: Span) -> str:
    return "\n".join(source.split("\n")[span.start - 1:span.end])


def lane_view(path: str, source: str, owned: Sequence[Span], all_units: Sequence[Span] | None = None) -> str:
    """One file as a lane sees it: owned spans in full; every other unit reduced to its first line
    plus an elision marker; lines outside any unit (imports, module constants) kept."""
    lines = source.split("\n")
    all_units = list(all_units) if all_units is not None else units(path, source)
    own = [s for s in owned if s.path == path]
    keep_full = [False] * (len(lines) + 2)
    for s in own:
        for k in range(s.start, s.end + 1):
            keep_full[k] = True
    other_first: dict[int, Span] = {}
    hidden = [False] * (len(lines) + 2)
    for u in all_units:
        if any(o.start <= u.start and u.end <= o.end for o in own):
            continue
        # a unit partly owned (an owned method inside an unowned class block) shows its owned lines
        for k in range(u.start, u.end + 1):
            if not keep_full[k]:
                hidden[k] = True
        other_first[u.start] = u
    out: list[str] = []
    for no, text in enumerate(lines, start=1):
        if keep_full[no] or not hidden[no]:
            out.append(text)
        elif no in other_first:
            indent = re.match(r"\s*", text).group(0)
            out.append(text.rstrip())
            out.append(f"{indent}    {ELIDED} ({other_first[no].lines - 1} lines)")
    return "\n".join(out)


# ------------------------------------------------------------------ planning


def est_tokens(text: str, chars_per_token: float = 3.0) -> int:
    return math.ceil(len(text) / chars_per_token)


@dataclass
class SymbolLane:
    lane_id: str
    owned: list[Span] = field(default_factory=list)
    prompt_tokens: int = 0
    code_tokens: int = 0  # owned spans in full

    @property
    def files(self) -> list[str]:
        return sorted({s.path for s in self.owned})


@dataclass
class SymbolPlan:
    lanes: list[SymbolLane]
    shared_tokens: int
    target_tokens: int
    n_units: int

    @property
    def k(self) -> int:
        return len(self.lanes)

    @property
    def max_prompt(self) -> int:
        return max((ln.prompt_tokens for ln in self.lanes), default=self.shared_tokens)

    @property
    def fits(self) -> bool:
        return self.max_prompt <= self.target_tokens

    @property
    def largest_code_share(self) -> float:
        total = sum(ln.code_tokens for ln in self.lanes)
        return max((ln.code_tokens for ln in self.lanes), default=0) / total if total else 0.0


def lane_prompt_tokens(owned: Sequence[Span], sources: Mapping[str, str], shared_tokens: int,
                       unit_index: Mapping[str, Sequence[Span]], chars_per_token: float = 3.0) -> tuple[int, int]:
    """(prompt tokens, owned-code tokens) of a lane: the shared part, then each of its files as
    :func:`lane_view` renders it. Owned spans in new files (absent from ``sources``) count zero."""
    code = sum(est_tokens(unit_text(sources[s.path], s), chars_per_token) for s in owned if s.path in sources)
    view = sum(est_tokens(lane_view(p, sources[p], owned, unit_index.get(p)), chars_per_token)
               for p in sorted({s.path for s in owned}) if p in sources)
    return shared_tokens + view, code


def plan_symbol_lanes(owned_units: Sequence[Span], sources: Mapping[str, str], *, shared_tokens: int,
                      target_tokens: int = 24_000, max_lanes: int = 8, chars_per_token: float = 3.0,
                      split_class_lines: int = 120, keep_classes_together: bool = False) -> SymbolPlan:
    """Pack contract units into lanes. The lane count is the number of contract units, capped at
    ``max_lanes``; units are grouped when ``keep_classes_together`` (methods of one class in one
    group). Groups are assigned largest first to the lane with the smallest prompt so far (LPT),
    where a lane's prompt counts the outline of the rest of each file it touches."""
    unit_index = {p: units(p, s, split_class_lines=split_class_lines) for p, s in sources.items()}
    groups: dict[str, list[Span]] = {}
    for u in owned_units:
        key = u.unit_id
        if keep_classes_together and u.kind in ("method", "class-header"):
            key = f"{u.path}::{u.name.split('.')[0]}"
        groups.setdefault(key, []).append(u)
    k = max(1, min(max_lanes, len(groups)))

    def size(g: list[Span]) -> int:
        return sum(est_tokens(unit_text(sources[s.path], s), chars_per_token) if s.path in sources else 0 for s in g)

    lanes = [SymbolLane(f"L{i + 1}") for i in range(k)]
    for key in sorted(groups, key=lambda key: (-size(groups[key]), key)):
        best = None
        for ln in lanes:
            p, c = lane_prompt_tokens(ln.owned + groups[key], sources, shared_tokens, unit_index, chars_per_token)
            if best is None or (p, len(ln.owned)) < best[0]:
                best = ((p, len(ln.owned)), ln, c)
        (_, ln, c) = best
        ln.owned = sorted(ln.owned + groups[key])
        ln.prompt_tokens, ln.code_tokens = lane_prompt_tokens(ln.owned, sources, shared_tokens, unit_index,
                                                              chars_per_token)
    lanes = [ln for ln in lanes if ln.owned] or lanes[:1]
    for i, ln in enumerate(lanes):
        ln.lane_id = f"L{i + 1}"
    return SymbolPlan(lanes, shared_tokens, target_tokens, len(groups))


def touched_units(path: str, base: str, changed_base_lines: Iterable[int], *, split_class_lines: int = 120,
                  insert_points: Iterable[int] = ()) -> list[Span]:
    """Units of ``path`` that contain any changed base line or insertion point (an insertion
    between two units goes to the unit above it, or the first unit if it is at the top)."""
    us = units(path, base, split_class_lines=split_class_lines)
    hit: dict[str, Span] = {}
    for line in changed_base_lines:
        for u in us:
            if u.contains(line):
                hit[u.unit_id] = u
    for at in insert_points:
        inside = [u for u in us if u.start <= at <= u.end]
        above = [u for u in us if u.end <= at]
        u = (inside or above[-1:] or us[:1])[0]
        hit[u.unit_id] = u
    return sorted(hit.values())


def changed_lines(base: str, new: str) -> tuple[list[int], list[int]]:
    """(base lines replaced or deleted, base insertion points) of ``base`` -> ``new``. An insertion
    point ``n`` means new lines go after base line ``n`` (0 = top)."""
    a, b = base.split("\n"), new.split("\n")
    changed: list[int] = []
    inserts: list[int] = []
    for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            changed.extend(range(i1 + 1, i2 + 1))
        elif tag == "insert":
            inserts.append(i1)
    return changed, inserts


# ------------------------------------------------------------------ the scope gate


@dataclass(frozen=True)
class ScopeViolation:
    path: str
    line: int  # base line changed, or the insertion point
    what: str  # "changed" | "inserted" | "file"

    def reason(self) -> str:
        if self.what == "file":
            return f"{self.path}: no owned span in this file"
        verb = "changes line" if self.what == "changed" else "inserts after line"
        return f"{self.path}: {verb} {self.line}, outside the lane's owned spans"


def scope_violations(owned: Sequence[Span], before: Mapping[str, str], after: Mapping[str, str],
                     *, new_files: Sequence[str] = ()) -> list[ScopeViolation]:
    """Check a lane's edit against its owned spans. ``before``/``after`` map path -> text for every
    file the edit touched (missing in ``before`` = created). A created file is in scope only if it
    is in ``new_files``. A changed non-blank base line must lie in an owned span; an insertion
    point must be owned by one of the lane's spans (:func:`insertion_owner`: inside it, directly
    below it, or in the blank lines below it, so a lane can add a helper below its own function)."""
    out: list[ScopeViolation] = []
    by_path: dict[str, list[Span]] = {}
    for s in owned:
        by_path.setdefault(s.path, []).append(s)
    for path in sorted(set(before) | set(after)):
        if path not in before:
            if path not in new_files and not by_path.get(path):
                out.append(ScopeViolation(path, 0, "file"))
            continue
        base, new = before[path], after.get(path, "")
        if base == new:
            continue
        spans = by_path.get(path, [])
        if not spans:
            out.append(ScopeViolation(path, 0, "file"))
            continue
        base_lines = base.split("\n")
        changed, inserts = changed_lines(base, new)
        for line in changed:
            if base_lines[line - 1].strip() and not any(s.contains(line) for s in spans):
                out.append(ScopeViolation(path, line, "changed"))
        every = file_spans(path, base)
        for at in inserts:  # the scope gate's rule: exactly one span owns each insertion point
            ok = _in_scope(spans, at, at, base_lines, every)
            if not ok:
                out.append(ScopeViolation(path, at, "inserted"))
    return out


# ------------------------------------------------------------------ restricting and merging span edits


def _opcodes(base: str, new: str):
    a, b = base.split("\n"), new.split("\n")
    return a, b, [op for op in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op[0] != "equal"]


def _in_scope(spans: Sequence[Span], i1: int, i2: int, base_lines: Sequence[str],
              all_spans: Sequence[Span] | None = None) -> bool:
    """Whether the base-line range [i1, i2) (0-based, half-open) may be changed: every replaced or
    deleted non-blank line lies in an owned span (several adjacent owned units may change in one
    piece; blank lines between them go with them), or an insertion inside a span, at its edges, or
    in the blank lines right after it."""
    if i2 > i1:
        lines = [no for no in range(i1 + 1, i2 + 1) if base_lines[no - 1].strip()]
        if lines:
            return all(any(s.contains(no) for s in spans) for no in lines)
        if all_spans is None:  # only blank lines: in scope next to an owned span
            return any(s.start - 1 <= i2 and i1 <= s.end for s in spans)
    at = i1  # insertion after base line `at` (1-based count of lines before it)
    if all_spans is not None:  # the file's spans are known: exactly one span owns each insertion point
        owner = insertion_owner(all_spans, at, base_lines)
        return owner is not None and any((o.start, o.end, o.name) == (owner.start, owner.end, owner.name) for o in spans)
    if any(s.start - 1 <= at <= s.end for s in spans):
        return True
    k = at
    while k >= 1 and not base_lines[k - 1].strip():
        k -= 1
    return any(s.end == k for s in spans)


def restrict_to_spans(base: str, new: str, spans: Sequence[Span], *,
                      split_class_lines: int = 120) -> tuple[str, list[tuple[int, int]]]:
    """``new`` with every change outside ``spans`` undone: the text a lane may contribute to a file
    it shares with other lanes, and the rejected base ranges (1-based first line, line count)."""
    a, b, ops = _opcodes(base, new)
    every = file_spans(spans[0].path, base, split_class_lines=split_class_lines) if spans else None
    out: list[str] = []
    rejected: list[tuple[int, int]] = []
    pos = 0
    for tag, i1, i2, j1, j2 in ops:
        out += a[pos:i1]
        if _in_scope(spans, i1, i2, a, every):
            out += b[j1:j2]
        else:
            out += a[i1:i2]
            rejected.append((i1 + 1, i2 - i1))
        pos = i2
    out += a[pos:]
    return "\n".join(out), rejected


def merge_span_edits(base: str, versions: Sequence[tuple[str, str]]) -> tuple[str, list[tuple[str, str, int]]]:
    """Merge several lanes' versions of one file, each confined to its own spans of the same base.
    ``versions`` is (lane id, text) in plan order. Changes are applied to the base in line order;
    insertions at the same point keep plan order. Two changes whose base ranges overlap are a
    conflict: the earlier lane's change is kept and (later lane, earlier lane, base line) reported."""
    a = base.split("\n")
    changes: list[tuple[int, int, int, str, list[str]]] = []  # (i1, i2, lane order, lane, lines)
    for order, (lane, text) in enumerate(versions):
        _, b, ops = _opcodes(base, text)
        changes += [(i1, i2, order, lane, b[j1:j2]) for _, i1, i2, j1, j2 in ops]
    changes.sort(key=lambda c: (c[0], c[1], c[2]))
    out: list[str] = []
    conflicts: list[tuple[str, str, int]] = []
    pos, last_end, last_lane = 0, -1, None
    for i1, i2, _, lane, lines in changes:
        overlap = i1 < pos or (i2 > i1 and i1 < last_end)
        if overlap:
            conflicts.append((lane, last_lane or "", i1 + 1))
            continue
        out += a[pos:i1]
        out += lines
        pos = max(pos, i2)
        last_end, last_lane = max(last_end, i2), lane
    out += a[pos:]
    return "\n".join(out), conflicts


def spans_for(path: str, source: str, names: Iterable[str], *, split_class_lines: int = 120) -> list[Span]:
    """The spans of ``path`` named ``names`` (unit names as :func:`units` gives them, or
    :data:`MODULE` for the file's module-level lines)."""
    want = set(names)
    out = [u for u in units(path, source, split_class_lines=split_class_lines) if u.name in want]
    if MODULE in want:
        out += module_spans(path, source, split_class_lines=split_class_lines)
    return sorted(out)


MODULE = "<module>"  # the pseudo-unit of a code file's module-level lines (imports, constants, top-level code)


def module_spans(path: str, source: str, *, split_class_lines: int = 120) -> list[Span]:
    """The lines of a code file outside every unit, as spans named :data:`MODULE`: imports, module
    constants and other top-level code. A lane that owns ``path::<module>`` may change them, so a
    file split by units can still get a new import. Empty for files whose units are line blocks."""
    us = units(path, source, split_class_lines=split_class_lines)
    if not us or all(u.kind == "block" for u in us):
        return []
    lines = source.split("\n")
    n = len(lines) - 1 if lines and lines[-1] == "" else len(lines)
    covered = [False] * (n + 2)
    for u in us:
        for k in range(u.start, min(u.end, n) + 1):
            covered[k] = True
    out: list[Span] = []
    start = None
    for no in range(1, n + 2):
        if no <= n and not covered[no]:
            start = no if start is None else start
        elif start is not None:
            out.append(Span(path, start, no - 1, MODULE, "module"))
            start = None
    return out


def file_spans(path: str, base: str, *, split_class_lines: int = 120) -> list[Span]:
    """Every span of a file: its units and its module-level spans, in line order."""
    return sorted(units(path, base, split_class_lines=split_class_lines)
                  + module_spans(path, base, split_class_lines=split_class_lines))


def _blank_span(s: Span, base_lines: Sequence[str]) -> bool:
    return s.kind == "module" and not any(base_lines[k - 1].strip() for k in range(s.start, min(s.end, len(base_lines)) + 1))


def insertion_owner(spans: Sequence[Span], at: int, base_lines: Sequence[str]) -> Span | None:
    """The one span that owns an insertion after base line ``at`` (0 = top), so that two lanes never
    both may insert at the same point: the span holding the point inside it; else the span ending at
    it (a helper goes directly below its unit); a run of blank lines between units belongs to the
    unit above it; the top of the file to the first span."""
    if not spans:
        return None
    spans = sorted(spans)
    holder = next((s for s in spans if s.start <= at < s.end), None) or next((s for s in spans if s.end == at), None)
    if holder is None:
        return spans[0]
    while _blank_span(holder, base_lines):  # blank separators go with the unit above them
        above = [s for s in spans if s.end < holder.start]
        if not above:
            return holder
        holder = above[-1]
    return holder


def unit_groups(path: str, base: str, new: str, *, split_class_lines: int = 120) -> list[list[str]]:
    """The units a change touches, grouped so that units one contiguous change (one diff hunk of
    replaced or deleted lines) crosses are in one group: no lane could make that change unless it
    owns all of them. Groups in file order; names as :func:`unit_items` gives them."""
    us = units(path, base, split_class_lines=split_class_lines)
    spans = sorted(us + module_spans(path, base, split_class_lines=split_class_lines))
    a, b = base.split("\n"), new.split("\n")
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            x = parent[x]
        return x

    order = unit_items(path, base, new, split_class_lines=split_class_lines)
    for name in order:
        find(name)
    for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag not in ("replace", "delete"):
            continue
        hit = {s.name for s in spans for no in range(i1 + 1, i2 + 1) if a[no - 1].strip() and s.contains(no)}
        hit &= set(order)
        hit = sorted(hit)
        for x in hit[1:]:
            parent[find(x)] = find(hit[0])
    groups: dict[str, list[str]] = {}
    for name in order:
        groups.setdefault(find(name), []).append(name)
    return list(groups.values())


def unit_items(path: str, base: str, new: str, *, split_class_lines: int = 120) -> list[str]:
    """The unit names (``MODULE`` included) a change from ``base`` to ``new`` touches, in file order,
    using the scope gate's rules: a changed non-blank line belongs to the span holding it; an
    insertion (or new code written over blank lines) to :func:`insertion_owner`."""
    us = units(path, base, split_class_lines=split_class_lines)
    spans = sorted(us + module_spans(path, base, split_class_lines=split_class_lines))
    base_lines, new_lines = base.split("\n"), new.split("\n")
    changed: list[int] = []
    inserts: list[int] = []
    for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, base_lines, new_lines, autojunk=False).get_opcodes():
        if tag == "insert":
            inserts.append(i1)
        elif tag in ("replace", "delete"):
            solid = [no for no in range(i1 + 1, i2 + 1) if base_lines[no - 1].strip()]
            changed += solid  # blank lines go with the units next to them (the scope gate's rule)
            if not solid and tag == "replace":
                inserts.append(i1)  # new code written over blank lines is an insertion there
    hit: dict[str, int] = {}
    for line in changed:
        for s in spans:
            if s.contains(line):
                hit.setdefault(s.name, s.start)
    for at in inserts:
        owner = insertion_owner(spans, at, base_lines)
        if owner is not None:
            hit.setdefault(owner.name, owner.start)
    return sorted(hit, key=lambda name: hit[name])
