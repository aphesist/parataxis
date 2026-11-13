"""Symbol-unit edit blocks: the local track's edit format after calibration (PREREGISTRATION.md, b.6).

The calibration's L1 failed format compliance. Half its gated edits failed to parse or apply,
mostly SEARCH text that was not an exact copy of the file and answers cut off at the 8K output cap
while echoing long SEARCH parts. So a worker may now replace a whole function, method or class by
name instead of copying it:

    <<<<<<< UNIT path/relative/to/repo.py::Class.method
    the complete new text of that unit
    >>>>>>> END

    <<<<<<< AFTER path/relative/to/repo.py::function_name
    new code inserted directly below that unit
    >>>>>>> END

SEARCH/REPLACE blocks (contraprova's ``harness.edits``) stay for everything else: imports,
module-level lines, non-code files, new files.

:func:`expand_unit_blocks` rewrites each UNIT/AFTER block, in place, into a canonical
SEARCH/REPLACE block whose SEARCH part is the unit's exact current text, taken from the original
file. Everything downstream is unchanged: contraprova's parser, its exact-match apply, the scope
checks, the span scope gate, the merges and the logs. Rules:

1. A block starts at a line ``<<<<<<< UNIT ref`` or ``<<<<<<< AFTER ref`` and ends at the first
   line ``>>>>>>> END``. ``ref`` is ``path::name``. A block cut off before its END line is an error
   and is dropped, so a truncated reply never half-applies a block.
2. The name resolves (:func:`locate`) to one definition:
   - Python: ``function``, ``Class``, ``Class.method``, nested classes alike, including
     definitions inside a module-level ``if``/``try``;
   - JavaScript/TypeScript: a top-level function, class or assigned name (``module.exports``,
     ``Foo.bar``), ``Class.method``, or an assigned name anywhere in the file
     (``Hash.incrObjectFieldBy = async function``) when it occurs once.

   The unit runs from its first decorator (or its declaration line) to its last line. Comments
   above it are not part of it.
3. UNIT replaces the unit with the block's body; an empty body deletes the unit. AFTER inserts the
   body below the unit, after one blank line. Blocks naming the same unit merge into one SEARCH
   block, at the place of the first: the UNIT body (or the original unit) followed by every AFTER
   body. A second UNIT for the same unit, or a unit overlapping another named in the reply, is an
   error and that block is dropped.
4. The SEARCH text must be unique in the file, as contraprova requires. If the unit's text occurs
   more than once, lines above it are added until it is unique.
5. Errors are returned, never raised, and name the block's ref. The caller adds them to the parse
   errors, so they reach the one edit-repair turn like any malformed block.
"""

from __future__ import annotations

import ast
import difflib
import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from contraprova.harness.edits import DIVIDER, REPLACE_MARK, SEARCH_MARK, ParsedEdits, clean_path

from .symbols import JS_EXT, PY_EXT, _JS_METHOD, _JS_KEYWORDS, _js_extent, blank_js, js_units, units

EDIT_FORMATS = ("search", "units")
UNIT_MAX_LINES = 60  # the prompt's rule of thumb: longer units are changed with SEARCH/REPLACE unless mostly rewritten

_UNIT_OPEN = re.compile(r"^<<<<<<< (?P<kind>UNIT|AFTER)(?:[ \t]+(?P<ref>\S.*?))?[ \t]*$")
_UNIT_END = re.compile(r"^>>>>>>> END[ \t]*$")
_JS_COMMENT = ("/**", "/*", "*", "//")

NO_TOOLS = ("You have no tools: you cannot run commands, open or search files, or call functions, and nothing you "
            "write is executed. Everything you can use is in this message. Reply only with edit blocks.")

UNIT_EDIT_FORMAT = f"""{NO_TOOLS}

Return your changes as edit blocks. There are three kinds.

1. To change a short function, method or class (up to about {UNIT_MAX_LINES} lines), or to rewrite most of one, replace \
it whole:

<<<<<<< UNIT path/relative/to/repo.py::name
the complete new text of that function, method or class
>>>>>>> END

Name the unit path::function, path::Class or path::Class.method (in JavaScript or TypeScript also an assigned \
name, such as path::Hash.incrObjectFieldBy). The unit runs from its first decorator to its last line; comments \
above it are not part of it. Give its complete new text, decorators and docstring included, with the file's \
indentation. An empty body deletes the unit. A UNIT block naming a function or method that does not exist yet adds \
it: a new method at the end of its class, anything else at the end of the file.

2. To add new functions, methods or classes, put them directly after an existing one:

<<<<<<< AFTER path/relative/to/repo.py::name
the new code
>>>>>>> END

3. For a small change inside a long unit, and for anything else (imports, module-level lines, non-code files, \
new files), use a SEARCH/REPLACE block:

{SEARCH_MARK} path/relative/to/repo
lines copied exactly from the current file (enough to be unique in that file)
{DIVIDER}
the lines that replace them
{REPLACE_MARK}

The SEARCH lines must match the current file exactly, including indentation, and occur exactly once in it. To \
create a new file, leave the SEARCH part empty.

Blocks refer to the files as shown to you and apply in order. Name each unit in at most one UNIT block. Write \
the blocks directly: do not think aloud or draft code before them, and keep any text outside the blocks to a few \
lines. Never edit test files."""

TOOL_MARKERS = ("<tool_call>", "<function=")
REPAIR_TOOL_CALL = ("You have no tools: your tool call was not executed, and nothing can be run, opened or searched. "
                    "Everything you can use is in the first message. Reply with only the edit blocks for your change.")


def is_tool_call(text: str) -> bool:
    """Whether a reply contains an agent-style tool call (which is never executed here)."""
    return any(m in (text or "") for m in TOOL_MARKERS)


# The texts that ask for "SEARCH/REPLACE blocks" by name, as they read with this format.
REPAIR_TRUNCATED = ("Your answer was cut off at the output limit. Reply with only the remaining edit blocks; "
                    "do not repeat blocks you already sent in full.")
REPAIR_ERRORS = ("Some of your edit blocks could not be used:\n\n{errors}\n\n"
                 "Reply with only corrected edit blocks for those edits. The blocks that applied are kept; "
                 "do not repeat them.")


@dataclass(frozen=True)
class Expanded:
    text: str  # the reply with every UNIT/AFTER block rewritten as a SEARCH/REPLACE block
    errors: tuple[str, ...] = ()
    unit_blocks: int = 0  # UNIT/AFTER blocks found (well formed or not)
    refs: tuple[str, ...] = field(default=())  # the refs that resolved
    added: tuple[str, ...] = field(default=())  # UNIT refs naming a missing function or method, added


# ------------------------------------------------------------------ locating a unit


def locate(path: str, source: str, name: str) -> tuple[int, int] | str:
    """(first line, last line), 1-based and inclusive, of the definition ``name`` in ``path``, or
    an error message saying why it cannot be resolved."""
    if not name:
        return "no unit name after '::'"
    if path.endswith(PY_EXT):
        return _locate_py(source, name)
    if path.endswith(JS_EXT):
        return _locate_js(path, source, name)
    return ("UNIT and AFTER blocks need a Python, JavaScript or TypeScript file; "
            "use a SEARCH/REPLACE block for this file")


def _py_start(node: ast.AST) -> int:
    decos = getattr(node, "decorator_list", None) or []
    return min([node.lineno] + [d.lineno for d in decos])


def _py_defs(nodes: Sequence[ast.stmt]) -> list[ast.AST]:
    out: list[ast.AST] = []
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append(node)
        elif isinstance(node, (ast.If, ast.Try)):
            out += _py_defs(node.body)
            for h in getattr(node, "handlers", []):
                out += _py_defs(h.body)
            out += _py_defs(node.orelse)
            out += _py_defs(getattr(node, "finalbody", []))
    return out


def _locate_py(source: str, name: str) -> tuple[int, int] | str:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "the file does not parse as Python; use a SEARCH/REPLACE block"
    scope: Sequence[ast.stmt] = tree.body
    node: ast.AST | None = None
    for i, part in enumerate(name.split(".")):
        hits = [n for n in _py_defs(scope) if n.name == part]  # type: ignore[attr-defined]
        if not hits:
            where = ".".join(name.split(".")[:i]) or "the module level"
            return f"no function, method or class named {part!r} at {where}"
        if len(hits) > 1:
            return f"{part!r} is defined {len(hits)} times at the same level; use a SEARCH/REPLACE block"
        node = hits[0]
        scope = getattr(node, "body", [])
    assert node is not None
    return _py_start(node), node.end_lineno  # type: ignore[attr-defined]


def _skip_comments(lines: Sequence[str], start: int, end: int) -> int:
    """Move a 0-based ``start`` past leading comment lines (comments above a unit are not part of it)."""
    while start < end and lines[start].lstrip().startswith(_JS_COMMENT):
        start += 1
    return start


def _locate_js(path: str, source: str, name: str) -> tuple[int, int] | str:
    lines = source.split("\n")
    blank = blank_js(source).split("\n")
    top = [u for u in js_units(path, source, split_class_lines=10 ** 9) if u.name == name]
    if len(top) == 1:
        u = top[0]
        return _skip_comments(lines, u.start - 1, u.end - 1) + 1, u.end
    if "." in name:
        cls, _, member = name.rpartition(".")
        owner = [u for u in js_units(path, source, split_class_lines=10 ** 9) if u.name == cls and u.kind == "class"]
        if len(owner) == 1:
            got = _js_member(lines, blank, owner[0].start - 1, owner[0].end - 1, member)
            if got is not None:
                return got
    # an assigned name anywhere in the file: ``Hash.incrObjectFieldBy = async function (...) {``
    prefix = r"(?:[A-Za-z_$][\w$]*\.)*" if "." not in name else ""  # a bare name also matches obj.name = ...
    pat = re.compile(rf"^\s*(?:(?:export\s+)?(?:const|let|var)\s+)?{prefix}{re.escape(name)}\s*(?::[^=]+)?=(?!=)")
    hits = [j for j, b in enumerate(blank) if pat.match(b)]
    if len(hits) == 1:
        j = hits[0]
        return j + 1, _js_extent(blank, j) + 1
    if len(hits) > 1:
        return f"{name!r} is assigned {len(hits)} times in the file; use a SEARCH/REPLACE block"
    return f"no function, method, class or assigned name {name!r}"


def _js_member(lines: Sequence[str], blank: Sequence[str], start: int, end: int, member: str) -> tuple[int, int] | None:
    depth = 0
    found: list[tuple[int, int]] = []
    for j in range(start, end + 1):
        b = blank[j]
        if depth == 1:
            m = _JS_METHOD.match(b)
            if m and m.group(1) == member and m.group(1) not in _JS_KEYWORDS:
                first = j
                while first > start and lines[first - 1].lstrip().startswith("@"):
                    first -= 1
                found.append((first + 1, _js_extent(blank, j) + 1))
        depth += b.count("{") - b.count("}")
    return found[0] if len(found) == 1 else None


# ------------------------------------------------------------------ expanding a reply


@dataclass
class _Block:
    kind: str  # UNIT | AFTER
    ref: str
    body: str
    at: int  # index in the output where its SEARCH/REPLACE block goes


def _body(lines: Sequence[str]) -> str:
    return "\n".join(lines) + "\n" if lines else ""


def expand_unit_blocks(text: str, files: Mapping[str, str]) -> Expanded:
    """Rewrite every UNIT/AFTER block of a reply as a SEARCH/REPLACE block against ``files`` (the
    original files). SEARCH/REPLACE blocks and other text pass through unchanged."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    blocks: list[_Block] = []
    errors: list[str] = []
    found = 0
    i = 0
    while i < len(lines):
        m = _UNIT_OPEN.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        found += 1
        kind, ref = m.group("kind"), (m.group("ref") or "").strip().strip("`")
        j = i + 1
        while j < len(lines) and not _UNIT_END.match(lines[j]):
            j += 1
        if j >= len(lines):
            errors.append(f"{kind} {ref or '(no ref)'}: no '>>>>>>> END' line (block truncated); dropped")
            break
        blocks.append(_Block(kind, ref, _body(lines[i + 1:j]), len(out)))
        out.append("")  # the placeholder line its SEARCH/REPLACE block replaces
        i = j + 1

    groups: dict[tuple[str, int, int], list[_Block]] = {}
    order: list[tuple[str, int, int]] = []
    adds: dict[tuple[str, int, str], list[_Block]] = {}  # (path, anchor line, "after" | "before") -> new units
    for b in blocks:
        path, sep, name = b.ref.partition("::")
        clean = clean_path(path) if sep else None
        if not sep or clean is None:
            errors.append(f"{b.kind} {b.ref or '(no ref)'}: the ref must be path::name; dropped")
            continue
        if clean not in files:
            errors.append(f"{b.kind} {b.ref}: {clean} is not one of the files shown; dropped")
            continue
        got = locate(clean, files[clean], name.strip())
        if isinstance(got, str) and b.kind == "UNIT" and got.startswith("no function"):
            point = add_point(clean, files[clean], name.strip())
            if point is not None:  # a UNIT for a function or method that does not exist yet adds it
                adds.setdefault((clean, *point), []).append(b)
                continue
        if isinstance(got, str):
            known = ", ".join(u.name for u in units(clean, files[clean])[:30])
            errors.append(f"{b.kind} {b.ref}: {got}" + (f" (units in this file: {known})" if known else "") + "; dropped")
            continue
        key = (clean, *got)
        clash = next((k for k in order if k[0] == clean and k != key and not (k[2] < got[0] or got[1] < k[1])), None)
        if clash is not None:
            errors.append(f"{b.kind} {b.ref}: overlaps a unit named earlier in this reply (lines {clash[1]}-{clash[2]}); "
                          "dropped")
            continue
        if b.kind == "UNIT" and any(x.kind == "UNIT" for x in groups.get(key, [])):
            errors.append(f"UNIT {b.ref}: this unit is already replaced by an earlier block; dropped")
            continue
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(b)

    refs = []
    for key in order:
        path, start, end = key
        src = files[path]
        src_lines = src.split("\n")
        unit = "\n".join(src_lines[start - 1:end]) + "\n"
        group = groups[key]
        new = next((b.body for b in group if b.kind == "UNIT"), unit)
        for b in group:
            if b.kind == "AFTER" and b.body.strip():
                gap = "" if b.body.startswith("\n") else "\n"  # one blank line between the unit and new code
                new = new + gap + b.body
        search, replace_ = unit, new
        top = start - 1
        while _occurrences(src, search) > 1 and top > 0:  # rule 4: add lines above until unique
            top -= 1
            search = src_lines[top] + "\n" + search
            replace_ = src_lines[top] + "\n" + replace_
        if _occurrences(src, search) != 1:
            errors.append(f"{group[0].kind} {group[0].ref}: its text is not unique in {path}; use a SEARCH/REPLACE block; "
                          "dropped")
            continue
        out[group[0].at] = f"{SEARCH_MARK} {path}\n{search}{DIVIDER}\n{replace_}{REPLACE_MARK}"
        refs += [b.ref for b in group]
    added = []
    for (path, line, where), group in adds.items():
        src = files[path]
        src_lines = src.split("\n")
        anchor = src_lines[line - 1] + "\n"
        top_level = "." not in group[0].ref.partition("::")[2]
        gap = "\n\n" if (top_level and path.endswith(PY_EXT)) else "\n"
        body = "".join(gap + b.body if not b.body.startswith("\n") else b.body for b in group)
        # after: the anchor line, a gap, the new code; before (a JS class's closing line): a gap, the code, the line
        search, replace_ = (anchor, anchor + body) if where == "after" else (anchor, body + anchor)
        top = line - 1
        while _occurrences(src, search) > 1 and top > 0:
            top -= 1
            search = src_lines[top] + "\n" + search
            replace_ = src_lines[top] + "\n" + replace_
        if _occurrences(src, search) != 1:
            errors.append(f"UNIT {group[0].ref}: no unique place to add it in {path}; use a SEARCH/REPLACE block; dropped")
            continue
        out[group[0].at] = f"{SEARCH_MARK} {path}\n{search}{DIVIDER}\n{replace_}{REPLACE_MARK}"
        refs += [b.ref for b in group]
        added += [b.ref for b in group]
    return Expanded("\n".join(out), tuple(errors), found, tuple(refs), tuple(added))


def add_point(path: str, source: str, name: str) -> tuple[int, str] | None:
    """Where a UNIT block for a missing ``name`` adds it: (line, "after") below the end of its class
    (Python) or the end of the file, or (line, "before") the closing line of its class (JavaScript and
    TypeScript). None when the name's class does not exist either."""
    parent, _, _ = name.rpartition(".")
    if parent:
        got = locate(path, source, parent)
        if isinstance(got, str):
            return None
        return (got[1], "after") if path.endswith(PY_EXT) else (got[1], "before")
    lines = source.split("\n")
    last = max((i for i, x in enumerate(lines, 1) if x.strip()), default=0)
    return (last, "after") if last else None


def _occurrences(src: str, search: str) -> int:
    """How often ``search`` occurs in ``src``, counting the file's end when the file has no final
    newline (contraprova's rule 8 matches it there)."""
    n = src.count(search)
    if n == 0 and search.endswith("\n") and not src.endswith("\n") and src.endswith(search[:-1]):
        return src.count(search[:-1])
    return n


def strip_blocks(text: str) -> str:
    """The reply without its edit blocks (SEARCH/REPLACE, UNIT and AFTER): the notes around them."""
    text = re.sub(r"(?ms)^<{7} (?:SEARCH|UNIT|AFTER)\b.*?^>{7} (?:REPLACE|END)[ \t]*$\n?", "", text or "")
    return re.sub(r"(?ms)^<{7} (?:SEARCH|UNIT|AFTER)\b.*\Z", "", text)  # a block cut off at the end


# ------------------------------------------------------------------ installing the format

_SAVED: dict[str, object] = {}


def _work_units(self, arm, task_id, ex, model, prompt, attempt, effort=None, role="worker", fork_id=None,
                cache_upto=0, *, scope=None, max_tokens=None, system=None, extra=None, extra_tags=None):
    """contraprova's ``ProHarness._work`` (one worker request plus at most one edit-repair turn,
    then ``task.submitted``) with each reply expanded by :func:`expand_unit_blocks` before it is
    parsed. The logged response is the reply as sent; ``task.submitted`` adds ``edit_format``,
    ``unit_blocks`` and the expansion's errors (also part of ``parse_errors``)."""
    from dataclasses import replace

    from contraprova.harness import swepro_arms as sa

    self.emit("task.claimed", f"worker:{model}", {"task_id": task_id, "worker": model, "attempt": attempt})
    if effort is None:
        effort = self.worker_effort(model)
    mt = max_tokens or self.worker_max_tokens(model)
    kw = dict(arm=arm, role=role, task_id=task_id, model=model, system=system or self.worker_system,
              max_tokens=mt, effort=effort, fork_id=fork_id)
    c = self.call(user=prompt, cache_upto=cache_upto, extra_tags=extra_tags, **kw)
    lane_scope = scope is not None
    scope = scope or self.scope(ex)

    def parse(text: str):
        x = expand_unit_blocks(text, ex.context.files)
        p = sa.parse_edits(x.text)
        return ParsedEdits(p.blocks, x.errors + p.errors), x

    def failure_of(text: str, stop, p, a):
        # a reply that only calls a tool (never executed here) is its own failure kind, sent to the repair turn
        if is_tool_call(text) and not p.blocks:
            return "tool_call"
        return sa.edit_failure(stop, p.errors, a.errors)

    parsed, x1 = parse(c.text)
    applied = sa.apply_edits(parsed.blocks, ex.context.files, scope=scope)
    failure = failure_of(c.text, c.stop_reason, parsed, applied)
    first_errors = list(parsed.errors + applied.errors)
    info = {"repair_used": False, "original_failure": failure, "original_errors": first_errors,
            "stop_reason": c.stop_reason, "edit_format": "units", "unit_blocks": x1.unit_blocks,
            "unit_errors": list(x1.errors), "unit_added": list(x1.added), "tool_call": is_tool_call(c.text)}
    blocks, final, last_parse, last_stop = list(parsed.blocks), applied, parsed.errors, c.stop_reason
    sent = list(parsed.blocks)
    if failure and self.repair:
        history = (sa.Message("user", prompt, cache_upto), sa.Message("assistant", c.text.rstrip() or "(no output)"))
        c2 = self.call(user=REPAIR_TOOL_CALL if failure == "tool_call" else sa.repair_message(failure, first_errors),
                       history=history,
                       extra_tags={**dict(extra_tags or {}), "repair": True}, **kw)
        parsed2, x2 = parse(c2.text)
        offset = max((b.index for b in parsed.blocks), default=0)
        ok = set(applied.applied)
        blocks = [b for b in parsed.blocks if b.index in ok] + [replace(b, index=b.index + offset) for b in parsed2.blocks]
        sent += [replace(b, index=b.index + offset) for b in parsed2.blocks]
        final = sa.apply_edits(blocks, ex.context.files, scope=scope)
        last_parse, last_stop = parsed2.errors, c2.stop_reason
        info.update(repair_used=True, repair_stop_reason=c2.stop_reason, repair_response=c2.text,
                    repair_blocks=len(parsed2.blocks), repair_unit_blocks=x2.unit_blocks,
                    repair_unit_errors=list(x2.errors), repair_unit_added=list(x2.added),
                    repair_tool_call=is_tool_call(c2.text))
        last_text = c2.text
    else:
        last_text = c.text
    errors = list(last_parse + final.errors)
    if last_stop == "max_tokens":
        errors.append(f"reply cut off at max_tokens ({mt}); the unfinished block was dropped")
    info["final_failure"] = ("tool_call" if is_tool_call(last_text) and not blocks
                             else sa.edit_failure(last_stop, last_parse, final.errors))
    if lane_scope:
        info["rejected_blocks"] = [{"block": b.index, "path": b.path, "reason": scope(b.path)}
                                   for b in sent if scope(b.path)]
    info.update(extra or {})
    self._last_blocks = len(blocks)
    return self.submit(task_id, attempt, model, sa.ParsedFiles(final.files, tuple(errors)), ex, response=c.text,
                       extra=info)


def _units_text(text: str) -> str:
    return text.replace("as SEARCH/REPLACE blocks", "as edit blocks").replace(
        "Outside your SEARCH/REPLACE blocks", "Outside your edit blocks")


def install() -> None:
    """Make the local arms (L1, La, Lb) use this format: the worker and lane system prompts, the
    retry and repair texts, the worker edit path and the shadow merge's parser. Idempotent;
    :func:`uninstall` restores contraprova's SEARCH/REPLACE format."""
    from contraprova.harness import swepro_arms as sa
    from contraprova.harness.edits import EDIT_FORMAT

    from . import lanes

    if _SAVED:
        return
    _SAVED.update({
        "sa.PRO_WORKER_RETRY": sa.PRO_WORKER_RETRY, "sa.REPAIR_TRUNCATED": sa.REPAIR_TRUNCATED,
        "sa.REPAIR_ERRORS": sa.REPAIR_ERRORS, "ProHarness.worker_system": sa.ProHarness.worker_system,
        "ProHarness._work": sa.ProHarness.__dict__["_work"], "lanes.LANE_SYSTEM": lanes.LANE_SYSTEM,
        "lanes.LANE_RETRY": lanes.LANE_RETRY, "lanes.BOARD_LANE": lanes.BOARD_LANE,
        "lanes.reply_blocks": lanes.reply_blocks,
    })
    assert EDIT_FORMAT in sa.ProHarness.worker_system and EDIT_FORMAT in lanes.LANE_SYSTEM
    sa.ProHarness.worker_system = sa.ProHarness.worker_system.replace(EDIT_FORMAT, UNIT_EDIT_FORMAT)
    sa.PRO_WORKER_RETRY = _units_text(sa.PRO_WORKER_RETRY)
    sa.REPAIR_TRUNCATED, sa.REPAIR_ERRORS = REPAIR_TRUNCATED, REPAIR_ERRORS
    sa.ProHarness._work = _work_units
    lanes.LANE_SYSTEM = lanes.LANE_SYSTEM.replace(EDIT_FORMAT, UNIT_EDIT_FORMAT)
    lanes.LANE_RETRY = _units_text(lanes.LANE_RETRY)
    lanes.BOARD_LANE = _units_text(lanes.BOARD_LANE)
    lanes.reply_blocks = lambda text, files: lanes.parse_edits(expand_unit_blocks(text, files).text)


def uninstall() -> None:
    from contraprova.harness import swepro_arms as sa

    from . import lanes

    if not _SAVED:
        return
    sa.PRO_WORKER_RETRY = _SAVED["sa.PRO_WORKER_RETRY"]
    sa.REPAIR_TRUNCATED = _SAVED["sa.REPAIR_TRUNCATED"]
    sa.REPAIR_ERRORS = _SAVED["sa.REPAIR_ERRORS"]
    sa.ProHarness.worker_system = _SAVED["ProHarness.worker_system"]
    sa.ProHarness._work = _SAVED["ProHarness._work"]
    lanes.LANE_SYSTEM = _SAVED["lanes.LANE_SYSTEM"]
    lanes.LANE_RETRY = _SAVED["lanes.LANE_RETRY"]
    lanes.BOARD_LANE = _SAVED["lanes.BOARD_LANE"]
    lanes.reply_blocks = _SAVED["lanes.reply_blocks"]
    _SAVED.clear()


def installed() -> bool:
    return bool(_SAVED)


# ------------------------------------------------------------------ dry runs and tests


def to_unit_reply(reply: str, files: Mapping[str, str]) -> str:
    """Rewrite a SEARCH/REPLACE reply (against ``files``) as unit blocks, for dry runs and tests.

    Per changed Python or JavaScript/TypeScript file, every unit the reply changes becomes a UNIT
    block with its new text when the prompt's rule says so (the unit is at most
    :data:`UNIT_MAX_LINES` lines, or mostly rewritten); what is left (module-level lines, new units) follows as
    SEARCH/REPLACE blocks against the file with those units already replaced. Other files keep the
    reply's own blocks. :func:`expand_unit_blocks` of the result applies to the same files as the
    original reply."""
    from contraprova.harness.edits import apply_edits, diff_to_blocks, parse_edits, unified_patch

    blocks = parse_edits(reply).blocks
    new_files = {**files, **apply_edits(blocks, files).files}
    paths = list(dict.fromkeys(b.path for b in blocks))
    text: list[str] = []

    def search_block(b) -> str:
        return f"{SEARCH_MARK} {b.path}\n{b.search}{DIVIDER}\n{b.replace}{REPLACE_MARK}"

    for path in paths:
        base, new = files.get(path), new_files.get(path)
        if base is None or new is None or not path.endswith((*PY_EXT, *JS_EXT)):
            text += [search_block(b) for b in blocks if b.path == path]
            continue
        cur = base
        for u in units(path, base):
            if u.kind == "class-header":  # its name resolves to the whole class; header lines go below
                continue
            old_at, new_at = locate(path, base, u.name), locate(path, new, u.name)
            if isinstance(old_at, str) or isinstance(new_at, str):
                continue
            old_t = "\n".join(base.split("\n")[old_at[0] - 1:old_at[1]]) + "\n"
            new_t = "\n".join(new.split("\n")[new_at[0] - 1:new_at[1]]) + "\n"
            short = old_at[1] - old_at[0] + 1 <= UNIT_MAX_LINES
            rewritten = difflib.SequenceMatcher(None, old_t, new_t, autojunk=False).ratio() < 0.5
            if old_t != new_t and (short or rewritten) and cur.count(old_t) == 1:
                text.append(f"<<<<<<< UNIT {path}::{u.name}\n{new_t}>>>>>>> END")
                cur = cur.replace(old_t, new_t, 1)
        if cur != new:
            text += [search_block(b) for b in diff_to_blocks(unified_patch({path: cur}, {path: new}), {path: cur})]
    return "Here are the changes.\n\n" + "\n\n".join(text) + "\n"


def unit_fake_client(base):
    """A subclass of contraprova's offline ``ProFakeClient`` whose workers and lanes answer with
    their gold blocks as UNIT blocks (:func:`to_unit_reply`), for ``--dry-run --edit-format units``."""

    class UnitFakeClient(base):
        def _worker_text(self, tid, model, prompt):
            text = super()._worker_text(tid, model, prompt)
            if tid in self.exercises and "## Request: lane plan" not in prompt and "<<<<<<< SEARCH" in text:
                return to_unit_reply(text, self.exercises[tid].context.files)
            return text

    return UnitFakeClient
