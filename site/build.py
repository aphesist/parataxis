#!/usr/bin/env python3
"""Build site/index.html, parataxis's paper page (aphes.ist design system, system/page-types/paper).

Every number in the results comes from results/swepro-lanes/main/analysis.json (contraprova's study, copied here as
starting evidence), and the honesty table from README.md, so the page says nothing they do not. Run from the
repository root: python3 site/build.py (--check to test that site/index.html is current)."""
import html, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
A = json.loads((ROOT / "results/swepro-lanes/main/analysis.json").read_text(encoding="utf-8"))
GH = "https://github.com/aphesist/parataxis/blob/main/"
KINDS = ("measured", "modelled", "tested", "hypothesis")
# the arms in the order of the lane chain, with the names the study's report uses
ARMS = [("La-shadow", "La-shadow · ungated merge of the first replies"), ("La-first", "La · first merge"),
        ("B", "B · one haiku (derived)"), ("D", "D · the cascade"), ("La", "La · governed, final")]
SHORT = {"La-shadow": "La-shadow", "La-first": "La, first merge", "B": "B", "D": "D", "La": "La, final"}
CONTRASTS = [("La_vs_La-shadow", "La − La-shadow (primary)"), ("La-first_vs_La-shadow", "first merge − shadow"),
             ("La-sonnet_vs_La-first", "sonnet round − first merge"), ("La_vs_D", "La − D"), ("La_vs_B", "La − B")]


def inline(md):
    out = []
    for p in re.split(r"(`[^`]*`)", md):
        if p.startswith("`") and p.endswith("`") and len(p) > 1:
            out.append("<code>" + html.escape(p[1:-1]) + "</code>"); continue
        t = html.escape(p, quote=False)
        t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: '<a href="%s">%s</a>' % (m.group(2) if m.group(2).startswith("http") else GH + m.group(2), m.group(1)), t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
        out.append(t)
    return "".join(out)


def honesty_rows():
    sec = README.split("## honesty table", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in sec.splitlines():
        if not line.startswith("|") or line.startswith("|---") or line.startswith("| claim"):
            continue
        claim, status, basis = [c.strip() for c in line.strip().strip("|").split("|")]
        m = re.match(r"^\*\*(\w+)\*\*\s*(.*)$", status)
        st = ('<span class="lab-ev" data-ev="%s">%s</span>%s' % (m.group(1), m.group(1), (" " + inline(m.group(2))) if m.group(2) else "")
              if m and m.group(1) in KINDS else inline(status))
        rows.append("        <tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (inline(claim), st, inline(basis)))
    return "\n".join(rows)


def pct(x):
    return "%.1f" % x


def solve_chart():
    L, R, W, top, gap = 250, 500, 520, 18, 30
    X = lambda p: round(L + (R - L) * (p - 50) / 50, 1)          # 50% to 100%
    H = top + gap * len(ARMS) + 34
    s = A["solve"]
    la, sh = s["La"], s["La-shadow"]
    g = ['<svg viewBox="0 0 %d %d" role="img" aria-label="solve rate by arm on %d tasks: the governed lanes solve %d, the ungated merge of the same first replies %d">' % (W, H, A["n"], la["solved"], sh["solved"])]
    g.append('<g class="lab-grid">' + "".join('<line x1="%s" x2="%s" y1="%d" y2="%d"/>' % (X(t), X(t), top - 8, H - 30) for t in (50, 75, 100)) + "</g>")
    g.append('<g class="lab-axis" transform="translate(0,%d)"><line class="domain" x1="%d" x2="%d" y1="0" y2="0"/>' % (H - 26, L, R))
    g += ['<g class="tick" transform="translate(%s,0)"><line y2="5"/><text y="18" text-anchor="middle">%d%%</text></g>' % (X(t), t) for t in (50, 60, 70, 80, 90, 100)]
    g.append("</g>")
    for i, (k, name) in enumerate(ARMS):
        y, a = top + gap * i, s[k]
        lo, hi, p = 100 * a["wilson95"][0], 100 * a["wilson95"][1], 100 * a["solved"] / a["n"]
        cls = "lab-ink" if k == "La" else "lab-dim" if k == "La-shadow" else "lab-c1"
        g.append('<text class="lab-label" x="0" y="%d">%s</text>' % (y + 4, html.escape(SHORT[k])))
        g.append('<rect class="lab-band %s" x="%s" y="%d" width="%s" height="12" data-tip="%d/%d · 95%% wilson %s–%s"/>' % (cls, X(lo), y - 6, round(X(hi) - X(lo), 1), a["solved"], a["n"], pct(lo), pct(hi)))
        g.append('<rect class="lab-dot %s" x="%s" y="%d" width="6" height="6"/>' % (cls, round(X(p) - 3, 1), y - 3))
        if k == "La":
            g.append('<circle class="lab-ring" cx="%s" cy="%d" r="9"/>' % (X(p), y))
    g.append("</svg>")
    return "\n        ".join(g)


def solve_table():
    s = A["solve"]
    return "\n".join('          <tr%s><th scope="row">%s</th><td class="num">%d/%d</td><td class="num">%s%%</td><td class="num">%s–%s</td></tr>'
                     % (' class="lab-ref-row"' if k == "La" else "", html.escape(name), s[k]["solved"], s[k]["n"], pct(100 * s[k]["solved"] / s[k]["n"]), pct(100 * s[k]["wilson95"][0]), pct(100 * s[k]["wilson95"][1]))
                     for k, name in ARMS)


def contrast_chart():
    L, R, W, top, gap = 210, 500, 520, 18, 30
    X = lambda d: round(L + (R - L) * (d + 10) / 50, 1)          # −10 to +40 points
    H = top + gap * len(CONTRASTS) + 34
    p = A["La_vs_La-shadow"]
    g = ['<svg viewBox="0 0 %d %d" role="img" aria-label="paired differences in points with 95%% bootstrap intervals; the primary, governed minus shadow, is +%s [%s, %s]">' % (W, H, pct(p["diff_points"]), pct(p["ci95"][0]), pct(p["ci95"][1]))]
    g.append('<line class="lab-rule-ref" x1="%s" x2="%s" y1="%d" y2="%d"/><text class="lab-label-soft" x="%s" y="%d">no difference</text>' % (X(0), X(0), top - 10, H - 30, X(0) + 4, top - 8))
    g.append('<g class="lab-axis" transform="translate(0,%d)"><line class="domain" x1="%d" x2="%d" y1="0" y2="0"/>' % (H - 26, L, R))
    g += ['<g class="tick" transform="translate(%s,0)"><line y2="5"/><text y="18" text-anchor="middle">%+d</text></g>' % (X(t), t) for t in (-10, 0, 10, 20, 30, 40)]
    g.append("</g>")
    for i, (k, name) in enumerate(CONTRASTS):
        y, c = top + 8 + gap * i, A[k]
        cls = "lab-ink" if i == 0 else "lab-c1"
        g.append('<text class="lab-label" x="0" y="%d">%s</text>' % (y + 4, html.escape(name)))
        g.append('<rect class="lab-band %s" x="%s" y="%d" width="%s" height="12" data-tip="%+.1f points [%+.1f, %+.1f] · discordant %d:%d · exact mcnemar p = %.3g"/>' % (cls, X(c["ci95"][0]), y - 6, max(1, round(X(c["ci95"][1]) - X(c["ci95"][0]), 1)), c["diff_points"], c["ci95"][0], c["ci95"][1], c["a_only"], c["b_only"], c["mcnemar_p"]))
        g.append('<rect class="lab-dot %s" x="%s" y="%d" width="6" height="6"/>' % (cls, round(X(c["diff_points"]) - 3, 1), y - 3))
    g.append("</svg>")
    return "\n        ".join(g)


def contrast_table():
    return "\n".join('          <tr%s><th scope="row">%s</th><td class="num">%+.1f</td><td class="num">%+.1f to %+.1f</td><td class="num">%d:%d</td><td class="num">%.3g</td></tr>'
                     % (' class="lab-ref-row"' if i == 0 else "", html.escape(name), A[k]["diff_points"], A[k]["ci95"][0], A[k]["ci95"][1], A[k]["a_only"], A[k]["b_only"], A[k]["mcnemar_p"])
                     for i, (k, name) in enumerate(CONTRASTS))


def main():
    p, s = A["La_vs_La-shadow"], A["solve"]
    fill = {
        "<!--HONESTY-->": honesty_rows(), "<!--SOLVE-CHART-->": solve_chart(), "<!--SOLVE-TABLE-->": solve_table(),
        "<!--DIFF-CHART-->": contrast_chart(), "<!--DIFF-TABLE-->": contrast_table(),
        "{n}": str(A["n"]), "{la}": "%d/%d" % (s["La"]["solved"], s["La"]["n"]), "{shadow}": "%d/%d" % (s["La-shadow"]["solved"], s["La-shadow"]["n"]),
        "{diff}": "%+.1f" % p["diff_points"], "{ci}": "[%+.1f, %+.1f]" % tuple(p["ci95"]), "{disc}": "%d:%d" % (p["a_only"], p["b_only"]),
        "{p}": "%.4f" % p["mcnemar_p"], "{d}": "%d/%d" % (s["D"]["solved"], s["D"]["n"]),
        "{ladiff}": "%+.1f" % A["La_vs_D"]["diff_points"], "{laci}": "[%+.1f, %+.1f]" % tuple(A["La_vs_D"]["ci95"]), "{lap}": "%.2f" % A["La_vs_D"]["mcnemar_p"],
    }
    page = (ROOT / "site" / "page.html").read_text(encoding="utf-8")
    for k, v in fill.items():
        page = page.replace(k, v)
    out = ROOT / "site" / "index.html"
    if "--check" in sys.argv:
        ok = out.exists() and out.read_text(encoding="utf-8") == page
        print("current" if ok else "stale: run python3 site/build.py"); return 0 if ok else 1
    out.write_text(page, encoding="utf-8"); print("wrote", out.relative_to(ROOT))


if __name__ == "__main__":
    sys.exit(main())
