#!/usr/bin/env python3
"""Build the LinkedIn carousel from site/data.js.

Every number on the slides is computed from the same data the dashboard uses,
so re-scoring a process and re-running this keeps the carousel in sync.

Writes linkedin/carousel.html (1080x1350 slides). With --pdf it prints
linkedin/carousel.pdf (upload this as a LinkedIn document post); with --png it
also saves linkedin/slides/slide-NN.png. Both need Chrome, Brave or Chromium.
The type is Charter and Avenir Next, which ship with macOS; elsewhere it falls
back to Georgia / Helvetica.

Usage: python3 -I scripts/build_carousel.py --pdf [--png]
"""

import argparse
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_JS = ROOT / "site" / "data.js"
OUT_DIR = ROOT / "linkedin"

AUTHOR = "Sachet Mulimani"
EDITION = "October 2026"
HIGH_CAPABILITY = 7  # same threshold as site/app.js
LOW_ADOPTION = 3  # adoption 3 or less: use is still mostly pilots
W, H = 1080, 1350
PAD = 84
INNER = W - 2 * PAD

# A plain research-report palette: white page, near-black text, one dark blue accent.
C = {
    "paper": "#ffffff", "ink": "#16191d", "ink2": "#3f444b", "muted": "#6b717a",
    "rule": "#d9dce1", "track": "#eef0f3",
    "accent": "#1f4e8c", "accent_mid": "#7f9cc4", "accent_light": "#c6d3e6",
    "light": "#e2e5ea", "data2": "#8a9099",  # adoption: grey, 3.2:1 on white
}
# Ordered from desk to floor, so a light-to-dark ramp of the accent reads naturally.
WORK_TYPES = [("digital", "Digital work", C["accent"]), ("mixed", "Mixed", C["accent_mid"]), ("physical", "Physical work", C["light"])]
# Capability bins: dark blue where AI can largely do the work, light grey where it barely can.
CAP_BINS = [(HIGH_CAPABILITY, C["accent"], f"AI could do {HIGH_CAPABILITY * 10}–100% ({HIGH_CAPABILITY}–10)"),
            (4, C["accent_mid"], "40–60% (4–6)"), (0, C["light"], "0–30% (0–3)")]

GROUP_PROSE = {
    "IBP": "demand and supply planning", "PP": "production planning", "SRC": "procurement",
    "MFG": "manufacturing", "QM": "quality", "EAM": "maintenance", "EWM": "warehousing",
    "TM": "freight planning", "FX": "moving freight", "VIS": "shipment visibility",
    "O2C": "order to cash", "GTS": "customs", "RET": "returns",
}
# Shorter process names for the dumbbell rows.
PROCESS_LABEL = {
    "SRC-07": "PO follow-up with suppliers",
    "TM-09": "Pickup & delivery appointments",
    "GTS-05": "Trade documentation",
    "VIS-04": "Freight claims (OS&D)",
    "RET-03": "Returns disposition",
    "MFG-07": "Production confirmations",
    "EWM-07": "Cycle counting",
    "O2C-01": "Order capture & entry",
    "IBP-01": "Statistical demand forecasting",
    "VIS-01": "Shipment tracking & ETAs",
    "TM-06": "Route optimization",
    "SRC-09": "Invoice matching",
    "GTS-03": "Restricted party screening",
}
# The use cases that headline most AI-in-supply-chain talks.
SHOWCASE = ["VIS-01", "IBP-01", "TM-06", "SRC-09", "GTS-03"]
# (SOC, alias shown) — full-scope roles only, so the numbers describe the whole job.
ROLES = [
    ("43-5011", "Freight broker"), ("13-1081", "Demand planner"), ("43-5061", "Production planner"),
    ("13-1020", "Buyer"), ("11-3071", "Supply chain manager"), ("43-5032", "Dispatcher"),
    ("53-7062", "Warehouse associate"), ("53-3032", "Truck driver"),
]
N_SLIDES = 9
METHOD_SLIDE = 8

esc = html.escape


# ---------- data ----------
def load():
    s = DATA_JS.read_text(encoding="utf-8")
    return json.loads(s[s.index("{"): s.rindex("}") + 1])


def wages(p, c="NA"):
    return p["metrics"][c]["wages"]


def workers(p, c="NA"):
    return p["metrics"][c]["workers"]


def index_of(ps, field):
    w = sum(wages(p) for p in ps)
    return sum(p[field] * wages(p) for p in ps) / w * 10 if w else 0


def fmt_money(v):
    if v >= 1e12:
        return f"${v / 1e12:.2f}T"
    if v >= 1e9:
        return f"${v / 1e9:.0f}B" if v >= 1e11 else f"${v / 1e9:.1f}B"
    return f"${v / 1e6:.0f}M"


def fmt_count(v):
    return f"{v / 1e6:.1f}M" if v >= 1e6 else f"{v / 1e3:.0f}K"


def num(v):
    return f"{v:g}"


def cap_bin(cap):
    return next(i for i, (floor, _, _) in enumerate(CAP_BINS) if cap >= floor)


def stats(d):
    P = d["processes"]
    by_id = {p["id"]: p for p in P}
    total_w = sum(wages(p) for p in P)
    exposed = sum(wages(p) for p in P if p["capability"] >= HIGH_CAPABILITY)
    s = {
        "P": P, "by_id": by_id, "modules": d["modules"],
        "wages": total_w, "workers": sum(workers(p) for p in P), "exposed": exposed,
        "exposed_pct": round(exposed / total_w * 100),
        "exp_idx": round(index_of(P, "capability")), "ado_idx": round(index_of(P, "adoption")),
        "n_proc": len(P), "n_groups": len(d["modules"]),
        "hand_scored": sum(1 for p in P if p.get("scored_by") in ("expert", "llm+expert")),
        "n_products": len({(x["vendor"], x["product"]) for p in P for x in p["products"]}),
        "n_proc_products": sum(1 for p in P if p["products"]),
    }
    # Wage share per capability bin as whole percentages adding to 100. The top bin keeps the
    # headline's rounding; the other bins split the rest by largest remainder.
    raw = [0.0] * len(CAP_BINS)
    for p in P:
        raw[cap_bin(p["capability"])] += wages(p) / total_w * 100
    pct = [s["exposed_pct"]] + [int(r) for r in raw[1:]]
    for i in sorted(range(1, len(raw)), key=lambda i: -(raw[i] - pct[i]))[:100 - sum(pct)]:
        pct[i] += 1
    s["bin_pct"] = pct
    s["types"] = []
    for tid, label, color in WORK_TYPES:
        ps = [p for p in P if p["work_type"] == tid]
        tw = sum(wages(p) for p in ps)
        s["types"].append({"id": tid, "label": label, "color": color, "wages": tw,
                           "share": tw / total_w, "exp": index_of(ps, "capability")})
    s["groups"] = []
    for m in d["modules"]:
        ps = [p for p in P if p["module"] == m["id"]]
        s["groups"].append({"id": m["id"], "short": m["short"], "exp": index_of(ps, "capability"),
                            "products": len({(x["vendor"], x["product"]) for p in ps for x in p["products"]})})
    s["biggest"] = sorted(P, key=lambda p: -wages(p))[:4]
    # Capability and adoption are different scales, so pick by thresholds rather than by their difference.
    s["untapped"] = sorted((p for p in P if p["capability"] >= HIGH_CAPABILITY and p["adoption"] <= LOW_ADOPTION),
                           key=lambda p: -wages(p))[:6]
    s["exposed_points"] = sum(p["capability"] * wages(p) for p in P if p["capability"] >= HIGH_CAPABILITY) / total_w * 10
    s["showcase"] = [by_id[i] for i in SHOWCASE]
    roles = {r["soc"]: r for r in d["roles"]}
    alias_alloc = d.get("alias_alloc", {})
    s["roles"] = []
    for soc, alias in ROLES:
        r = roles[soc]
        # A job title's own time split where it has one (demand planner), else the official category's.
        alloc = alias_alloc.get(alias) or r["alloc"]
        tot = sum(a[1] for a in alloc) or 1
        s["roles"].append({
            "alias": alias, "title": r["title"], "workers": r["metrics"]["NA"]["workers"], "own_split": alias in alias_alloc,
            "exp": sum(sh * by_id[pid]["capability"] for pid, sh in alloc) / tot * 10,
            "ado": sum(sh * by_id[pid]["adoption"] for pid, sh in alloc) / tot * 10,
            "high": sum(sh for pid, sh in alloc if by_id[pid]["capability"] >= HIGH_CAPABILITY) / tot,
        })
    s["roles"].sort(key=lambda r: -r["exp"])
    return s


# ---------- treemap ----------
def squarify(items, x, y, w, h):
    """items: [(value, payload)] sorted descending. Returns [(x, y, w, h, payload)]."""
    total = sum(v for v, _ in items)
    if not total or w <= 0 or h <= 0:
        return []
    scale = w * h / total
    queue = [(v * scale, p) for v, p in items if v > 0]
    out = []

    def worst(row, side):
        s = sum(a for a, _ in row)
        return max(max(side * side * a / (s * s), s * s / (side * side * a)) for a, _ in row)

    while queue:
        side = min(w, h)
        row = [queue[0]]
        i = 1
        while i < len(queue) and worst(row + [queue[i]], side) <= worst(row, side):
            row.append(queue[i])
            i += 1
        queue = queue[i:]
        s = sum(a for a, _ in row)
        if w >= h:
            cw = s / h
            yy = y
            for a, p in row:
                out.append((x, yy, cw, a / cw, p))
                yy += a / cw
            x, w = x + cw, w - cw
        else:
            rh = s / w
            xx = x
            for a, p in row:
                out.append((xx, y, a / rh, rh, p))
                xx += a / rh
            y, h = y + rh, h - rh
    return out


def treemap_svg(s, width, height):
    P = s["P"]
    mods = sorted(((sum(wages(p) for p in P if p["module"] == m["id"]), m) for m in s["modules"]), key=lambda t: -t[0])
    cells, labels = [], []
    for mx, my, mw, mh, m in squarify(mods, 0, 0, width, height):
        ps = sorted(((wages(p), p) for p in P if p["module"] == m["id"]), key=lambda t: -t[0])
        for px, py, pw, ph, p in squarify(ps, mx + 2, my + 2, mw - 4, mh - 4):
            if pw > 2 and ph > 2:
                cells.append(f'<rect x="{px + 1:.1f}" y="{py + 1:.1f}" width="{pw - 2:.1f}" height="{ph - 2:.1f}" '
                             f'fill="{CAP_BINS[cap_bin(p["capability"])][1]}"/>')
        # A small map label per group, only where it fits whole.
        tw = len(m["short"]) * 10.4 + 16
        if tw < mw - 12 and mh > 56:
            labels.append(f'<rect x="{mx + 8:.1f}" y="{my + 8:.1f}" width="{tw:.1f}" height="28" fill="{C["paper"]}"/>'
                          f'<text x="{mx + 16:.1f}" y="{my + 28:.1f}" fill="{C["ink"]}" font-size="18" font-weight="600">{esc(m["short"])}</text>')
    return (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="Map of {s["n_proc"]} supply chain processes sized by wages, shaded by how much of each AI can do">'
            + "".join(cells) + "".join(labels) + "</svg>")


# ---------- slide pieces ----------
def slide(i, body, cls=""):
    return f"""
<section class="slide {cls}" id="slide-{i}">
  <header class="run"><span>Supply Chain AI Exposure Index</span><span>North America · {EDITION}</span></header>
  {body}
  <footer class="foot"><span>{esc(AUTHOR)}</span><span>{i} / {N_SLIDES}</span></footer>
</section>"""


def finding(n, title, sub=""):
    return (f'<p class="kicker">Finding {n}</p><h1>{title}</h1>' + (f'<p class="sub">{sub}</p>' if sub else ""))


def figure(n, caption):
    return f'<p class="fig"><b>Figure {n}.</b> {caption}</p>'


SOURCE = f"Sources: BLS OEWS May 2025; ESDC; O*NET 31.0. Scores: see method, slide {METHOD_SLIDE}."


def two_bar_row(label, exp, ado, extra=""):
    return f"""
<div class="tb-row">
  <span class="tb-label">{label}</span>
  <span class="tb-bars"><span class="b exp" style="width:{exp:.1f}%"></span><span class="b ado" style="width:{ado:.1f}%"></span></span>
  <span class="tb-num">{round(exp)}<small>{round(ado)}</small></span>{extra}
</div>"""


TWO_BAR_LEGEND = ('<div class="legend"><span><i class="k-bar exp"></i>Exposure: how much AI could do</span>'
                  '<span><i class="k-bar ado"></i>Adoption: how far use has spread</span><span class="muted">Index, 0–100</span></div>')
ADOPTION_SCALE = "2 = early pilots, 4 = leading firms use it, 6 = common at large firms"
DUMBBELL_NOTE = (f"Capability 8 = AI could do about 80% of the work. Adoption {ADOPTION_SCALE}. "
                 "The two scales differ, so the distance between the dots is not a percentage.")


def dumbbell(ps):
    rows = []
    for p in ps:
        cap, ado = p["capability"], p["adoption"]
        rows.append(f"""
<div class="db-row">
  <div class="db-head"><span>{esc(PROCESS_LABEL.get(p["id"], p["name"]))}</span><span class="db-val">{num(cap)} <i>vs</i> {num(ado)}</span></div>
  <div class="db-track">
    <span class="db-axis"></span>
    <span class="db-gap" style="left:{ado * 10}%;width:{(cap - ado) * 10}%"></span>
    <span class="db-dot ado" style="left:{ado * 10}%"></span>
    <span class="db-dot cap" style="left:{cap * 10}%"></span>
  </div>
</div>""")
    scale = '<div class="db-scale"><span style="left:0%">0</span><span style="left:50%">5</span><span style="left:100%">10</span></div>'
    legend = ('<div class="legend"><span><i class="k-dot cap"></i>Capability: share AI could do</span>'
              '<span><i class="k-dot ado"></i>Adoption: how far use has spread</span><span class="muted">Score, 0–10</span></div>')
    return legend + '<div class="db">' + "".join(rows) + scale + "</div>"


def build_html(s):
    slides = []

    # 1. Cover
    legend = "".join(f'<span><i style="background:{color}"></i>{esc(label)}</span>' for _, color, label in CAP_BINS)
    slides.append(slide(1, f"""
<h1 class="cover-h">I couldn't keep up with AI in supply chain. So I mapped it.</h1>
<p class="sub">An exposure index of {s['n_proc']} processes, {fmt_count(s['workers'])} jobs, {fmt_money(s['wages'])} in wages and {s['n_products']} AI products.</p>
{figure(1, "Every supply chain process, sized by wages and shaded by how much of the work AI can do today")}
<div class="tm">{treemap_svg(s, INNER, 560)}</div>
<div class="legend tm-legend">{legend}<span class="muted">Box size = wages</span></div>
""", "cover"))

    # 2. Product count vs exposure
    g = sorted(s["groups"], key=lambda x: (-x["products"], -x["exp"]))
    top_products = {x["id"] for x in g[:4]}
    low_exposure = {x["id"] for x in sorted(s["groups"], key=lambda x: x["exp"])[:4]}
    both = [x for x in g if x["id"] in top_products & low_exposure]
    names = [GROUP_PROSE[x["id"]] for x in both]
    if len(both) >= 2:
        listed = ", ".join(names[:-1]) + " and " + names[-1]
        words = {2: "two", 3: "three", 4: "all four"}[len(both)]
        sub2 = (f"{listed.capitalize()} have {words} of the four biggest product counts, "
                f"and {words} of the four lowest exposure scores.")
    else:
        sub2 = "Where the products cluster and where AI can actually do the work are two different maps."
    max_p = max(x["products"] for x in g)
    rows2 = "".join(f"""
<div class="pe-row">
  <span class="pe-label">{esc(x['short'])}</span>
  <span class="pe-track"><span class="ink" style="width:{x['products'] / max_p * 100:.1f}%"></span></span><span class="pe-num">{x['products']}</span>
  <span class="pe-track"><span class="acc" style="width:{x['exp']:.1f}%"></span></span><span class="pe-num">{round(x['exp'])}</span>
</div>""" for x in g)
    slides.append(slide(2, f"""
{finding(1, "More AI products doesn't mean more AI exposure.", esc(sub2))}
{figure(2, "AI products found and exposure index, by process group")}
<div class="pe">
  <div class="pe-row pe-head"><span>Group</span><span>AI products found</span><span>Exposure index (0–100)</span></div>
  {rows2}
</div>
<p class="src">A product can cover more than one group. Exposure index = how much of the work AI can do today, weighted by wages. {SOURCE}</p>
"""))

    # 3. Headline number, and how it relates to the exposure index
    slide3_sub = (f"That is, processes where AI could do {HIGH_CAPABILITY * 10}% or more of the work. "
                  f"Counting every part AI could do, it adds up to {s['exp_idx']}% of all the work"
                  + (", most of it in work AI could only partly do." if s["exposed_points"] < s["exp_idx"] / 2 else "."))
    waffle = "".join(f'<i style="background:{CAP_BINS[b][1]}"></i>' for b, n in enumerate(s["bin_pct"]) for _ in range(n))
    wlegend = "".join(f'<span><i style="background:{color}"></i>{esc(label)} <b>{pct}%</b></span>'
                      for (_, color, label), pct in zip(CAP_BINS, s["bin_pct"]))
    slides.append(slide(3, f"""
{finding(2, f"{s['exposed_pct']}% of supply chain pay sits in work AI could mostly do.", esc(slide3_sub))}
<div class="qs">
  <div class="q"><p class="q-text">Exposure index</p><div class="q-num">{s['exp_idx']}<small> / 100</small></div>
    <div class="q-bar"><span class="exp" style="width:{s['exp_idx']}%"></span></div><p class="q-note">Share of all the work AI could do today</p></div>
  <div class="q"><p class="q-text">Adoption index</p><div class="q-num">{s['ado_idx']}<small> / 100</small></div>
    <div class="q-bar"><span class="ado" style="width:{s['ado_idx']}%"></span></div><p class="q-note">How far use has spread</p></div>
</div>
{figure(3, "Share of supply chain wages, by how much of the work AI can do (each square is 1%)")}
<div class="answer">
  <div class="waffle" aria-label="Waffle chart of wage share by capability">{waffle}</div>
  <div><div class="hero">{fmt_money(s['exposed'])}</div>
    <p class="hero-sub">of {fmt_money(s['wages'])} in wages sits in processes where AI could do {HIGH_CAPABILITY * 10}% or more of the work.</p>
    <div class="wlegend">{wlegend}</div></div>
</div>
<p class="src">Both indexes are wage-weighted averages of 0–10 process scores, × 10. Adoption: {ADOPTION_SCALE}. {SOURCE}</p>
"""))

    # 4. Physical vs digital
    t = {x["id"]: x for x in s["types"]}
    phys = t["physical"]
    segs = "".join(f'<span style="flex:{x["share"]:.4f};background:{x["color"]}"></span>' for x in s["types"])
    seg_labels = "".join(
        f'<div style="flex:{x["share"]:.4f}"><span><span class="sw" style="background:{x["color"]}"></span>{esc(x["label"])}</span>'
        f'<b>{round(x["share"] * 100)}%</b><small>{fmt_money(x["wages"])}</small></div>' for x in s["types"])
    type_bars = "".join(
        f'<div class="ty-row"><span>{esc(x["label"])}</span><span class="ty-track"><span style="width:{x["exp"]:.1f}%"></span></span>'
        f'<span class="ty-num">{round(x["exp"])}</span></div>' for x in s["types"])
    big_rows = "".join(f'<tr><td>{esc(p["name"])}</td><td>${wages(p) / 1e9:.0f}B</td><td>{num(p["capability"])} / 10</td></tr>'
                       for p in s["biggest"])
    slides.append(slide(4, f"""
{finding(3, f"{round(phys['share'] * 100)}% of supply chain pay goes to physical work. AI barely touches it.")}
{figure(4, "Share of wages and exposure index, by type of work")}
<div class="stack">{segs}</div>
<div class="stack-labels">{seg_labels}</div>
<p class="label">Exposure index (0–100)</p>
<div class="ty">{type_bars}</div>
<table class="big"><thead><tr><th>Largest processes by wages</th><th>Wages</th><th>AI capability</th></tr></thead><tbody>{big_rows}</tbody></table>
<p class="src">{SOURCE}</p>
"""))

    # 5. Capable but not yet adopted
    un = s["untapped"]
    cap_lo, cap_hi = min(p["capability"] for p in un), max(p["capability"] for p in un)
    slides.append(slide(5, f"""
{finding(4, "The untapped work isn't a moonshot. It's the inbox.",
         f"Chasing POs, booking dock appointments, filing claims. AI could do {num(cap_lo * 10)}–{num(cap_hi * 10)}% of it; use is still mostly pilots.")}
{figure(5, f"The largest processes AI could do {HIGH_CAPABILITY * 10}%+ of, where adoption is {LOW_ADOPTION} or less")}
{dumbbell(un)}
<p class="src">{DUMBBELL_NOTE} {SOURCE}</p>
"""))

    # 6. Showcase
    sc = s["showcase"]
    ado6 = [p["adoption"] for p in sc]
    slides.append(slide(6, f"""
{finding(5, "The conference favourites are already in production.",
         f"Forecasting, ETAs, route optimization and invoice matching have years of products behind them. Use is already common at large firms (adoption {num(min(ado6))}–{num(max(ado6))}).")}
{figure(6, "Capability and adoption for the most talked-about use cases")}
{dumbbell(sc)}
<p class="src">{DUMBBELL_NOTE} {SOURCE}</p>
"""))

    # 7. Roles
    def who(r):
        # A job title with its own time split is part of a bigger official category; say so.
        return f"within {fmt_count(r['workers'])} {esc(r['title'].lower())}" if r["own_split"] else f"{fmt_count(r['workers'])} workers"
    rows7 = "".join(two_bar_row(
        f'{esc(r["alias"])}<small>{who(r)}</small>', r["exp"], r["ado"],
        f'<span class="tb-pct">{round(r["high"] * 100)}%</span>') for r in s["roles"])
    slides.append(slide(7, f"""
{finding(6, "Where does your job land?", "Planners, buyers and brokers sit near the top; drivers and warehouse associates near the bottom.")}
{figure(7, "Exposure and adoption by role")}
{TWO_BAR_LEGEND}
<div class="tb"><div class="tb-row tb-head"><span>Role</span><span></span><span>Exp. / adopt.</span><span>AI-capable time</span></div>{rows7}</div>
<p class="src">AI-capable time = share of the job in processes scoring {HIGH_CAPABILITY}+ on capability. Demand planners have no job code: the worker count is all logisticians; the time split is a typical demand planner’s. {SOURCE}</p>
"""))

    # 8. Method
    scored = "First pass by Claude Opus 5.5." + (f" {s['hand_scored']} processes reviewed by hand." if s["hand_scored"] else "")
    slides.append(slide(METHOD_SLIDE, f"""
<p class="kicker">Method</p>
<h1>How I built it</h1>
<dl class="method">
  <dt>Workers and wages</dt><dd>BLS OEWS May 2025 (US). ESDC COPS and Job Bank 2025 (Canada), converted at the 2025 Bank of Canada rate.</dd>
  <dt>Processes</dt><dd>{s['n_proc']} processes in {s['n_groups']} groups modelled on SAP modules, from forecasting to returns. Line workers and distributors included.</dd>
  <dt>Scores</dt><dd>Capability and adoption, 0–10 each, against a written rubric. Each job's time is split across processes using O*NET 31.0 tasks. {esc(scored)}</dd>
  <dt>AI products</dt><dd>{s['n_products']} products mapped to {s['n_proc_products']} processes. Examples, not endorsements.</dd>
  <dt>How to use it</dt><dd>As a map for navigating the noise: where AI can take on work today, where it's already in use, and where the claims are still ahead of the work.</dd>
</dl>
<p class="src">Data and code: github.com/msachet5/supplychain-ai-index</p>
"""))

    # 9. Close
    dp = next(r for r in s["roles"] if r["alias"] == "Demand planner")
    slides.append(slide(9, f"""
<p class="kicker">Explore the index</p>
<h1 class="cta-h">Find your role.</h1>
<p class="sub">Type your job title. See where your week goes, how exposed it is, and which AI products touch it.</p>
<div class="mock">
  <div class="mock-field">demand planner<i></i></div>
  <div class="mock-result">
    <div class="mock-title">Demand planner <span>a typical week · counted as Logisticians ({fmt_count(dp['workers'])} workers)</span></div>
    <div class="mock-stats"><div><b>{round(dp['exp'])}</b><span>Exposure index</span></div><div><b>{round(dp['ado'])}</b><span>Adoption index</span></div><div><b>{round(dp['high'] * 100)}%</b><span>of the week in AI-capable work</span></div></div>
  </div>
</div>
<p class="cta-line">Link in the first comment.</p>
<p class="cta-quiet">If I scored your work wrong, tell me. I'd rather fix it than defend it.</p>
"""))

    # Typographic apostrophes in the visible text (attributes use double quotes only).
    body = "".join(slides).replace("&#x27;", "’").replace("'", "’")
    return PAGE.format(slides=body, **C, W=W, H=H, PAD=PAD)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Supply Chain AI Carousel</title>
<style>
@page {{ size: {W}px {H}px; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; background: {paper}; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
body {{ font-family: "Avenir Next", Avenir, "Helvetica Neue", Helvetica, sans-serif; color: {ink}; font-variant-numeric: lining-nums; }}
@media screen {{ body:not(.single) {{ display: flex; flex-direction: column; align-items: center; gap: 40px; padding: 40px 0; background: #8a8f96; }} }}
.slide {{ width: {W}px; height: {H}px; position: relative; overflow: hidden; background: {paper}; padding: 150px {PAD}px 0;
  display: flex; flex-direction: column; break-after: page; page-break-after: always; }}
.slide[hidden] {{ display: none; }}
.run {{ position: absolute; top: 52px; left: {PAD}px; right: {PAD}px; display: flex; justify-content: space-between;
  font-size: 20px; font-weight: 500; color: {muted}; padding-bottom: 14px; border-bottom: 1px solid {rule}; }}
.run span:first-child {{ color: {ink}; font-weight: 600; }}
.foot {{ position: absolute; left: {PAD}px; right: {PAD}px; bottom: 44px; display: flex; justify-content: space-between;
  font-size: 20px; font-weight: 500; color: {muted}; padding-top: 14px; border-top: 1px solid {rule}; }}
.kicker {{ font-size: 22px; font-weight: 600; color: {accent}; margin: 0 0 14px; }}
h1 {{ font: 700 58px/1.12 Charter, "Iowan Old Style", Georgia, serif; letter-spacing: -0.01em; margin: 0; text-wrap: balance; }}
.sub {{ font-size: 28px; line-height: 1.42; color: {ink2}; margin: 20px 0 0; text-wrap: pretty; }}
.fig {{ font-size: 21px; line-height: 1.4; color: {ink2}; margin: 40px 0 0; padding-top: 16px; border-top: 2px solid {ink}; }}
.fig b {{ color: {ink}; font-weight: 600; }}
.label {{ font-size: 18px; font-weight: 600; color: {muted}; margin: 30px 0 0; }}
.src {{ font-size: 18px; line-height: 1.45; color: {muted}; margin: 22px 0 0; }}
.muted {{ color: {muted}; }}
.legend {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px 28px; font-size: 21px; font-weight: 500; color: {ink2}; margin-top: 18px; }}
.legend span {{ display: inline-flex; align-items: center; gap: 10px; }}
.legend i {{ display: inline-block; }}
.k-bar {{ width: 28px; height: 12px; }}
.k-bar.exp, .b.exp, .q-bar .exp {{ background: {accent}; }}
.k-bar.ado, .b.ado, .q-bar .ado {{ background: {data2}; }}
.k-dot {{ width: 18px; height: 18px; border-radius: 50%; }}
.k-dot.cap, .db-dot.cap {{ background: {accent}; }}
.k-dot.ado, .db-dot.ado {{ background: {paper}; box-shadow: inset 0 0 0 3px {ink2}; }}

/* cover */
.cover-h {{ font-size: 76px; line-height: 1.06; }}
.tm {{ margin-top: 18px; line-height: 0; }}
.tm-legend {{ font-size: 19px; gap: 8px 22px; }}
.tm-legend i {{ width: 18px; height: 18px; }}
.tm-legend .muted {{ margin-left: auto; }}

/* products vs exposure */
.pe {{ margin-top: 14px; }}
.pe-row {{ display: grid; grid-template-columns: 290px 1fr 48px 1fr 48px; align-items: center; gap: 0 14px; min-height: 46px;
  font-size: 24px; font-weight: 500; border-bottom: 1px solid {track}; }}
.pe-head {{ font-size: 18px; font-weight: 600; color: {muted}; min-height: 34px; border-bottom: 1px solid {rule}; }}
.pe-head span:nth-child(2), .pe-head span:nth-child(3) {{ grid-column: span 2; }}
.pe-track {{ height: 14px; background: {track}; }}
.pe-track span {{ display: block; height: 100%; }}
.pe-track .ink {{ background: {ink2}; }}
.pe-track .acc {{ background: {accent}; }}
.pe-num {{ font-size: 24px; font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; }}

/* two questions */
.qs {{ display: grid; grid-template-columns: 1fr 1fr; gap: 48px; margin-top: 36px; }}
.q-text {{ font-size: 22px; font-weight: 600; color: {ink2}; margin: 0; }}
.q-num {{ font: 700 110px/1 Charter, Georgia, serif; margin-top: 10px; }}
.q-num small {{ font: 500 34px/1 "Avenir Next", sans-serif; color: {muted}; }}
.q-bar {{ height: 14px; background: {track}; margin-top: 14px; }}
.q-bar span {{ display: block; height: 100%; }}
.q-note {{ font-size: 21px; color: {muted}; margin: 10px 0 0; }}
.answer {{ display: grid; grid-template-columns: 290px 1fr; gap: 44px; align-items: center; margin-top: 20px; }}
.waffle {{ display: grid; grid-template-columns: repeat(10, 1fr); gap: 3px; width: 290px; height: 290px; }}
.hero {{ font: 700 120px/1 Charter, Georgia, serif; letter-spacing: -0.01em; }}
.hero-sub {{ font-size: 27px; line-height: 1.38; margin: 12px 0 0; color: {ink2}; }}
.wlegend {{ display: flex; flex-direction: column; gap: 6px; margin-top: 18px; max-width: 420px; font-size: 20px; color: {ink2}; }}
.wlegend span {{ display: flex; align-items: center; gap: 10px; }}
.wlegend i {{ width: 16px; height: 16px; display: inline-block; }}
.wlegend b {{ font-weight: 600; color: {ink}; margin-left: auto; font-variant-numeric: tabular-nums; }}

/* work type */
.stack {{ display: flex; gap: 3px; height: 54px; margin-top: 22px; }}
.stack-labels {{ display: flex; gap: 3px; margin-top: 12px; font-size: 21px; font-weight: 500; color: {ink2}; }}
.stack-labels div {{ display: flex; flex-direction: column; min-width: 0; }}
.stack-labels b {{ font: 700 44px/1.1 Charter, Georgia, serif; color: {ink}; margin-top: 4px; }}
.stack-labels small {{ font-size: 19px; color: {muted}; }}
.sw {{ display: inline-block; width: 14px; height: 14px; margin-right: 8px; vertical-align: -1px; box-shadow: inset 0 0 0 1px rgba(0,0,0,.12); }}
.ty {{ display: flex; flex-direction: column; gap: 12px; margin-top: 12px; }}
.ty-row {{ display: grid; grid-template-columns: 200px 1fr 56px; align-items: center; gap: 16px; font-size: 23px; font-weight: 500; }}
.ty-track {{ height: 18px; background: {track}; }}
.ty-track span {{ display: block; height: 100%; background: {accent}; }}
.ty-num {{ font-size: 24px; font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; }}
.big {{ width: 100%; border-collapse: collapse; margin-top: 34px; font-size: 24px; }}
.big th {{ font-size: 18px; font-weight: 600; color: {muted}; text-align: left; padding: 0 0 8px; border-bottom: 1px solid {rule}; }}
.big td {{ padding: 11px 0; border-bottom: 1px solid {track}; font-weight: 500; }}
.big th:nth-child(n+2), .big td:nth-child(n+2) {{ text-align: right; width: 150px; font-variant-numeric: tabular-nums; }}

/* exposure + adoption rows */
.tb {{ display: flex; flex-direction: column; margin-top: 14px; }}
.tb-row {{ display: grid; grid-template-columns: 280px 1fr 120px 150px; align-items: center; gap: 0 18px; min-height: 66px;
  font-size: 25px; font-weight: 600; border-bottom: 1px solid {track}; }}
.tb-head {{ min-height: 32px; font-size: 18px; color: {muted}; border-bottom: 1px solid {rule}; }}
.tb-head span:nth-child(n+3) {{ text-align: right; white-space: nowrap; }}
.tb-label small {{ display: block; font-size: 19px; font-weight: 500; color: {muted}; }}
.tb-bars {{ display: flex; flex-direction: column; gap: 3px; }}
.tb-bars .b {{ display: block; height: 12px; }}
.tb-num {{ text-align: right; font-size: 27px; font-variant-numeric: tabular-nums; }}
.tb-num small {{ font-size: 22px; font-weight: 500; color: {muted}; margin-left: 10px; }}
.tb-pct {{ text-align: right; font-size: 27px; font-variant-numeric: tabular-nums; }}

/* dumbbell */
.db {{ margin-top: 16px; display: flex; flex-direction: column; gap: 14px; }}
.db-head {{ display: flex; justify-content: space-between; align-items: baseline; font-size: 26px; font-weight: 600; }}
.db-val {{ font-size: 26px; font-weight: 600; font-variant-numeric: tabular-nums; }}
.db-val i {{ font-style: normal; font-weight: 500; color: {muted}; font-size: 21px; }}
.db-track {{ position: relative; height: 34px; margin: 2px 12px 0; }}
.db-axis {{ position: absolute; left: 0; right: 0; top: 16px; height: 2px; background: {track}; }}
.db-gap {{ position: absolute; top: 13px; height: 8px; background: {accent_light}; }}
.db-dot {{ position: absolute; top: 5px; width: 24px; height: 24px; margin-left: -12px; border-radius: 50%; }}
.db-scale {{ position: relative; height: 26px; margin: 0 12px; font-size: 19px; color: {muted}; }}
.db-scale span {{ position: absolute; transform: translateX(-50%); }}

/* method */
.method {{ display: grid; grid-template-columns: 250px 1fr; column-gap: 20px; margin: 36px 0 0; font-size: 25px; line-height: 1.45; }}
.method dt, .method dd {{ border-top: 1px solid {rule}; padding: 18px 0 22px; margin: 0; }}
.method dt {{ font-weight: 600; color: {ink}; }}
.method dd {{ color: {ink2}; }}
.method dt:first-of-type, .method dd:first-of-type {{ border-top: 2px solid {ink}; }}

/* close */
.cta-h {{ font-size: 96px; line-height: 1; }}
.mock {{ margin-top: 44px; border: 1px solid {rule}; }}
.mock-field {{ font-size: 30px; font-weight: 500; padding: 22px 26px; border-bottom: 1px solid {rule}; box-shadow: inset 0 0 0 2px {accent}; }}
.mock-field i {{ display: inline-block; width: 2px; height: 32px; background: {ink}; vertical-align: -6px; margin-left: 4px; }}
.mock-result {{ padding: 24px 26px 28px; background: #f6f7f9; }}
.mock-title {{ font-size: 29px; font-weight: 600; }}
.mock-title span {{ display: block; font-size: 20px; font-weight: 500; color: {muted}; margin-top: 2px; }}
.mock-stats {{ display: grid; grid-template-columns: 1fr 1fr 1.5fr; gap: 20px; margin-top: 16px; }}
.mock-stats b {{ display: block; font: 700 70px/1.05 Charter, Georgia, serif; }}
.mock-stats span {{ font-size: 20px; font-weight: 500; color: {ink2}; }}
.cta-line {{ font: 700 44px/1.1 Charter, Georgia, serif; margin: 52px 0 0; }}
.cta-quiet {{ font-size: 27px; line-height: 1.4; color: {ink2}; margin: 14px 0 0; }}
</style>
</head>
<body>
{slides}
<script>
  // #slide-N shows a single slide (used for PNG export).
  const m = location.hash.match(/^#slide-(\\d+)$/);
  if (m) {{
    document.body.classList.add("single");
    document.querySelectorAll(".slide").forEach((s, i) => {{ s.hidden = i + 1 !== Number(m[1]); }});
  }}
</script>
</body>
</html>
"""


# ---------- export ----------
def find_browser():
    candidates = [os.environ.get("CHROME", ""),
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    candidates += [shutil.which(n) or "" for n in ("google-chrome", "chromium", "chromium-browser")]
    return next((c for c in candidates if c and Path(c).exists()), None)


def run_browser(browser, args):
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                        f"--user-data-dir={profile}", *args], check=True, capture_output=True, timeout=120)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pdf", action="store_true", help="also print linkedin/carousel.pdf")
    ap.add_argument("--png", action="store_true", help="also save one PNG per slide in linkedin/slides/")
    args = ap.parse_args()

    s = stats(load())
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / "carousel.html"
    out.write_text(build_html(s), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")

    if args.pdf or args.png:
        browser = find_browser()
        if not browser:
            sys.exit("No Chrome, Brave or Chromium found; set CHROME=/path/to/browser")
        url = out.resolve().as_uri()
        if args.pdf:
            pdf = OUT_DIR / "carousel.pdf"
            run_browser(browser, ["--no-pdf-header-footer", f"--print-to-pdf={pdf}", url])
            print(f"wrote {pdf.relative_to(ROOT)}")
        if args.png:
            slides_dir = OUT_DIR / "slides"
            slides_dir.mkdir(exist_ok=True)
            for old in slides_dir.glob("slide-*.png"):
                old.unlink()
            for i in range(1, N_SLIDES + 1):
                run_browser(browser, [f"--window-size={W},{H}", "--force-device-scale-factor=1",
                                      f"--screenshot={slides_dir / f'slide-{i:02d}.png'}", f"{url}#slide-{i}"])
            print(f"wrote {slides_dir.relative_to(ROOT)}/slide-01..{N_SLIDES:02d}.png")

    # The numbers the post text quotes, so it can be checked against the slides.
    t = {x["id"]: x for x in s["types"]}
    print(f"\nPost numbers: {fmt_count(s['workers'])} workers · {fmt_money(s['wages'])} wages · "
          f"{fmt_money(s['exposed'])} ({s['exposed_pct']}%) in capability {HIGH_CAPABILITY}+ · exposure {s['exp_idx']} · "
          f"adoption {s['ado_idx']} · physical {round(t['physical']['share'] * 100)}% of wages (exposure {round(t['physical']['exp'])}) · "
          f"digital exposure {round(t['digital']['exp'])} · {s['n_products']} products · hand-scored {s['hand_scored']}")
    for r in s["roles"]:
        print(f"  {r['alias']}: exposure {round(r['exp'])}, adoption {round(r['ado'])}, {round(r['high'] * 100)}% of time AI-capable")
    print(f"Untapped (capability {HIGH_CAPABILITY}+, adoption {LOW_ADOPTION} or less): "
          + "; ".join(f"{PROCESS_LABEL.get(p['id'], p['name'])} {num(p['capability'])}/{num(p['adoption'])}" for p in s["untapped"]))
    print("Showcase adoption: " + ", ".join(f"{PROCESS_LABEL.get(p['id'], p['name'])} {num(p['adoption'])}" for p in s["showcase"]))


if __name__ == "__main__":
    main()
