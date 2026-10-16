/* global d3 */
(() => {
  const DATA = window.SCAI_DATA;

  const METRICS = {
    capability: { label: "AI capability (0–10)", domain: [0, 10], kind: "seq" },
    adoption: { label: "Adoption (0–10)", domain: [0, 10], kind: "seq" },
    gap: { label: "Gap: capability − adoption", domain: [-6, 6], kind: "div" },
  };
  // Fixed categorical order -> --series-1..3. Never re-ordered by filters.
  const WORK_TYPES = [
    { id: "digital", label: "Digital work", color: "--series-1" },
    { id: "mixed", label: "Mixed", color: "--series-2" },
    { id: "physical", label: "Physical work", color: "--series-3" },
  ];
  const HIGH_CAPABILITY = 7;
  // Launch-update signups go to Supabase (see supabase/interest_contacts.sql). The publishable key is
  // public by design: it can only add a signup. Leave url empty to hide the form.
  const SIGNUP = { url: "https://cspoisgdxaeczbkngmjz.supabase.co", key: "sb_publishable_VHslLuMB3Mf6oqFZxTU8kA_YroJ4mMP" };

  const state = { country: "NA", colorBy: "capability", sizeBy: "wages", selected: null, module: null, brush: null, hover: null, role: null, roleAlias: null };

  const modulesById = new Map(DATA.modules.map((m) => [m.id, m]));
  const procs = DATA.processes.map((p) => ({ ...p, gap: Math.round((p.capability - p.adoption) * 10) / 10 }));
  const byId = new Map(procs.map((p) => [p.id, p]));
  const rolesBySoc = new Map(DATA.roles.map((r) => [r.soc, r]));
  const aliasAlloc = DATA.alias_alloc || {};
  // The selected role's time split: the job title's own where it has one, else the official category's.
  const roleAlloc = () => (state.roleAlias && aliasAlloc[state.roleAlias]) || rolesBySoc.get(state.role).alloc;

  // ---------- helpers ----------
  const $ = (id) => document.getElementById(id);
  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  const fmtMoney = (v) => {
    if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
    if (v >= 1e9) return `$${(v / 1e9).toFixed(v >= 1e11 ? 0 : 1)}B`;
    if (v >= 1e6) return `$${Math.round(v / 1e6)}M`;
    return `$${Math.round(v / 1e3)}K`;
  };
  const fmtCount = (v) => (v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${Math.round(v / 1e3)}K` : `${Math.round(v)}`);
  const fmtWage = (v) => `$${Math.round(v / 1e3)}K`;
  const fmtScore = (v) => v.toFixed(1);
  const fmtGap = (v) => (v > 0 ? `+${v.toFixed(1)}` : v.toFixed(1));

  const metricsOf = (p) => p.metrics[state.country];
  const sizeOf = (p) => (state.sizeBy === "wages" ? metricsOf(p).wages : metricsOf(p).workers);
  const avgWage = (p) => (metricsOf(p).workers ? metricsOf(p).wages / metricsOf(p).workers : 0);

  function activeIds() {
    let ids = null;
    const narrow = (set) => { ids = ids ? new Set([...ids].filter((id) => set.has(id))) : new Set(set); };
    if (state.role) narrow(new Set(roleAlloc().map(([pid]) => pid)));
    if (state.module) narrow(new Set(procs.filter((p) => p.module === state.module).map((p) => p.id)));
    if (state.brush) narrow(state.brush);
    return ids;
  }

  function colorScale() {
    const spec = METRICS[state.colorBy];
    if (spec.kind === "seq") {
      return d3.scaleSequential(d3.interpolateLab(cssVar("--seq-lo"), cssVar("--seq-hi"))).domain(spec.domain).clamp(true);
    }
    const neg = d3.interpolateLab(cssVar("--div-mid"), cssVar("--div-neg"));
    const pos = d3.interpolateLab(cssVar("--div-mid"), cssVar("--div-pos"));
    return d3
      .scaleDiverging((t) => (t < 0.5 ? neg(1 - 2 * t) : pos(2 * t - 1)))
      .domain([spec.domain[0], 0, spec.domain[1]])
      .clamp(true);
  }

  // Text measurement, so labels are only drawn where they fit whole.
  const FONT_STACK = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  const NAME_FONT = `600 12px ${FONT_STACK}`;
  const VALUE_FONT = `400 11px ${FONT_STACK}`;
  const HEADER_SMALL_FONT = `600 11px ${FONT_STACK}`;
  const measureCtx = document.createElement("canvas").getContext("2d");
  const textWidth = (text, font) => {
    measureCtx.font = font;
    return measureCtx.measureText(text).width;
  };
  // Greedy word wrap: the number of lines needed, or Infinity if one word is wider than the box.
  function wrapCount(text, font, maxWidth) {
    let lines = 1;
    let line = "";
    for (const word of text.split(/\s+/)) {
      if (textWidth(word, font) > maxWidth) return Infinity;
      const next = line ? `${line} ${word}` : word;
      if (textWidth(next, font) > maxWidth) {
        lines += 1;
        line = word;
      } else {
        line = next;
      }
    }
    return lines;
  }

  // White or ink text, whichever has more contrast on the fill.
  function inkOn(fill) {
    const c = d3.rgb(fill);
    const lin = (ch) => {
      const s = ch / 255;
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    };
    const L = 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b);
    return L > 0.179 ? "#0b0b0b" : "#ffffff";
  }

  const MATURITY = { ga: "In production", pilot: "Pilot / limited", announced: "Announced" };

  // A labelled 0–10 bar, used in the hover card and the detail panel.
  function scoreBar(label, value, max = 10) {
    const row = el("div", "score-row");
    const bar = el("div", "meter");
    const fill = el("span");
    fill.style.width = `${Math.max(0, Math.min(100, (value / max) * 100))}%`;
    bar.append(fill);
    row.append(el("span", "score-label", label), bar, el("span", "score-value", max === 100 ? String(Math.round(value)) : fmtScore(value)));
    return row;
  }

  // ---------- hover card ----------
  const tip = $("tooltip");
  let tipFor = null;
  function buildTip(p) {
    const m = metricsOf(p);
    const mod = modulesById.get(p.module);
    const stats = el("div", "tip-stats");
    [["Wages", fmtMoney(m.wages)], ["Workers", fmtCount(m.workers)], ["Avg wage", fmtWage(avgWage(p))]].forEach(([k, v]) => {
      const s = el("div");
      s.append(el("div", "tip-stat-value", v), el("div", "tip-stat-label", k));
      stats.append(s);
    });
    const chips = el("div", "chips");
    p.ai_type.forEach((t) => chips.append(el("span", "chip", t)));

    const products = el("div", "tip-products");
    if (p.products.length) {
      const names = p.products.slice(0, 3).map((x) => x.vendor).join(", ");
      const more = p.products.length > 3 ? ` +${p.products.length - 3} more` : "";
      products.append(el("span", "tip-k", "AI products: "), document.createTextNode(names + more));
    } else {
      products.append(el("span", "tip-k", "AI products: "), document.createTextNode("none mapped yet"));
    }

    const share = state.role && roleAlloc().find(([pid]) => pid === p.id);
    const foot = el("div", "tip-foot", [
      share ? `${Math.round(share[1] * 100)}% of the selected role's time` : "",
      p.scored_by === "llm" ? "Scored by Claude Opus 5.5" : p.scored_by === "placeholder" ? "Placeholder scores" : "",
      "Click for details",
    ].filter(Boolean).join(" · "));
    tip.replaceChildren(
      el("div", "tip-group", mod.short),
      el("div", "tip-title", p.name),
      el("div", "tip-desc", p.description),
      stats,
      scoreBar("AI capability", p.capability),
      scoreBar("Adoption", p.adoption),
      chips,
      products,
      foot,
    );
    tipFor = p.id;
  }
  function showTip(p, x, y) {
    if (tipFor !== p.id) buildTip(p);
    tip.hidden = false;
    // Right of the pointer, flipped left near the edge, clamped inside the viewport.
    const r = tip.getBoundingClientRect();
    const left = x + 18 + r.width > window.innerWidth - 8 ? x - r.width - 18 : x + 18;
    const top = Math.min(Math.max(8, y - 24), window.innerHeight - r.height - 8);
    tip.style.left = `${Math.max(8, left)}px`;
    tip.style.top = `${Math.max(8, top)}px`;
  }
  const hideTip = () => { tip.hidden = true; };

  function setHover(id) {
    state.hover = id;
    applyHighlight();
  }

  function select(id) {
    if (window.matchMedia("(hover: none)").matches) hideTip(); // touch: the card came from the tap
    state.selected = state.selected === id ? null : id;
    // On one-column layouts, details open in a bottom sheet over the map instead of scrolling the page.
    // Open it before rendering so the sidebar placeholder keeps the empty panel's height.
    if (isCompact()) {
      if (state.selected) openSheet();
      else closeSheet();
    }
    applyHighlight();
    renderDetail();
    syncHash();
  }

  // ---------- index (0–100) ----------
  // Wage-weighted mean score × 10 over a set of processes.
  function indexOf(set, field) {
    const wages = d3.sum(set, (p) => metricsOf(p).wages);
    return wages ? (d3.sum(set, (p) => p[field] * metricsOf(p).wages) / wages) * 10 : 0;
  }

  // ---------- headline estimates ----------
  const COUNTRY_LABEL = { NA: "North America", US: "United States", CA: "Canada" };
  function renderSummary() {
    const ids = activeIds();
    const set = ids ? procs.filter((p) => ids.has(p.id)) : procs;
    const wages = d3.sum(set, (p) => metricsOf(p).wages);
    const workers = d3.sum(set, (p) => metricsOf(p).workers);
    const exposed = d3.sum(set.filter((p) => p.capability >= HIGH_CAPABILITY), (p) => metricsOf(p).wages);
    const pct = wages ? Math.round((exposed / wages) * 100) : 0;

    const est = (value, label, hero) => {
      const d = el("div", hero ? "est hero" : "est");
      d.append(el("div", "est-value", value), el("div", "est-label", label));
      return d;
    };
    const expIdx = Math.round(indexOf(set, "capability"));
    const adoIdx = Math.round(indexOf(set, "adoption"));
    $("summary").replaceChildren(
      est(fmtMoney(exposed), `in wages sit in processes where AI could do ${HIGH_CAPABILITY * 10}% or more of the work. That's ${pct}% of the total.`, true),
      est(`${expIdx}/100`, "AI exposure index: the share of all the work AI could do, weighted by wages"),
      est(`${adoIdx}/100`, "AI adoption index: how far use has spread (20 = pilots, 40 = leading firms, 60 = common)"),
      est(fmtMoney(wages), "total supply chain wages"),
      est(fmtCount(workers), "supply chain workers"),
      el("div", "scope", `${COUNTRY_LABEL[state.country]} · ${ids ? `${set.length} selected processes` : "all processes"}`),
    );
    $("export-stat").textContent = state.role
      ? roleExportLine()
      : `${COUNTRY_LABEL[state.country]} · ${fmtMoney(exposed)} of ${fmtMoney(wages)} in wages (${pct}%) sit in processes AI can largely do · Exposure index ${expIdx}/100 · Adoption ${adoIdx}/100`;
  }

  // ---------- role search ----------
  const norm = (s) => s.toLowerCase().replace(/[^a-z0-9&]+/g, " ").trim();
  // One searchable entry per alias and per official title.
  const roleIndex = DATA.roles.flatMap((r) => [
    { soc: r.soc, label: r.title, alias: null, key: norm(r.title) },
    ...r.aliases.map((a) => ({ soc: r.soc, label: a, alias: a, key: norm(a) })),
  ]);
  let suggestions = [];
  let activeSuggestion = -1;

  function searchRoles(query) {
    const q = norm(query);
    if (!q) return [];
    // Prefix matches first, then shorter (more specific) labels.
    const scored = roleIndex
      .map((e) => ({ e, i: e.key.indexOf(q) }))
      .filter((x) => x.i >= 0)
      .sort((a, b) => (b.i === 0) - (a.i === 0) || a.e.label.length - b.e.label.length);
    const seen = new Set();
    return scored.map((x) => x.e).filter((e) => !seen.has(e.label) && seen.add(e.label)).slice(0, 8);
  }

  function renderSuggestions() {
    const list = $("role-suggestions");
    list.replaceChildren(...suggestions.map((s, i) => {
      const li = el("li", i === activeSuggestion ? "active" : null);
      li.setAttribute("role", "option");
      li.id = `role-opt-${i}`;
      li.append(el("span", "sugg-label", s.label));
      if (s.alias) li.append(el("span", "sugg-meta", `→ ${rolesBySoc.get(s.soc).title}`));
      li.addEventListener("mousedown", (e) => { e.preventDefault(); pickRole(s); });
      return li;
    }));
    list.hidden = suggestions.length === 0;
    $("role-input").setAttribute("aria-expanded", String(suggestions.length > 0));
    $("role-input").setAttribute("aria-activedescendant", activeSuggestion >= 0 ? `role-opt-${activeSuggestion}` : "");
  }

  function pickRole(s) {
    tipFor = null;
    state.role = s.soc;
    state.roleAlias = s.alias;
    $("role-input").value = s.label;
    suggestions = [];
    renderSuggestions();
    onSelectionChange();
    renderRole();
  }

  function clearRole() {
    tipFor = null;
    state.role = null;
    state.roleAlias = null;
    $("role-input").value = "";
    onSelectionChange();
    renderRole();
  }

  $("role-input").addEventListener("input", (e) => {
    suggestions = searchRoles(e.target.value);
    activeSuggestion = suggestions.length ? 0 : -1;
    renderSuggestions();
  });
  $("role-input").addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!suggestions.length) return;
      activeSuggestion = (activeSuggestion + (e.key === "ArrowDown" ? 1 : -1) + suggestions.length) % suggestions.length;
      renderSuggestions();
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (suggestions[activeSuggestion]) pickRole(suggestions[activeSuggestion]);
    } else if (e.key === "Escape") {
      e.stopPropagation();
      suggestions = [];
      renderSuggestions();
    }
  });
  $("role-input").addEventListener("blur", () => { suggestions = []; renderSuggestions(); });
  document.querySelectorAll("[data-role-example]").forEach((b) => b.addEventListener("click", () => {
    const hit = searchRoles(b.dataset.roleExample)[0];
    if (hit) pickRole(hit);
  }));

  // Role-level numbers, shared by the role card and the exported image caption.
  function roleStats(r, alloc) {
    const total = d3.sum(alloc, (a) => a[1]) || 1;
    return {
      m: r.metrics && r.metrics[state.country],
      exposure: (d3.sum(alloc, ([pid, s]) => s * byId.get(pid).capability) / total) * 10,
      adopted: (d3.sum(alloc, ([pid, s]) => s * byId.get(pid).adoption) / total) * 10,
      highShare: d3.sum(alloc.filter(([pid]) => byId.get(pid).capability >= HIGH_CAPABILITY), (a) => a[1]) / total,
    };
  }
  function roleExportLine() {
    const r = rolesBySoc.get(state.role);
    const { m, exposure, adopted, highShare } = roleStats(r, roleAlloc());
    const name = state.roleAlias ? `${state.roleAlias} (counted as ${r.title})` : r.title;
    return `${COUNTRY_LABEL[state.country]} · ${name} · ${m ? `${fmtCount(m.workers)} workers · ` : ""}${Math.round(highShare * 100)}% of their time is in processes AI can largely do · Exposure index ${Math.round(exposure)}/100 · Adoption ${Math.round(adopted)}/100`;
  }

  // The role card: how this job's time splits across processes, how exposed that time is, and what it does.
  function renderRole() {
    const box = $("role-card");
    const r = state.role && rolesBySoc.get(state.role);
    box.hidden = !r;
    if (!r) return;
    const alloc = roleAlloc();
    const { m, exposure, adopted, highShare } = roleStats(r, alloc);

    const head = el("div", "role-head");
    const titleWrap = el("div");
    titleWrap.append(el("div", "role-kicker", state.roleAlias ? `${state.roleAlias} · counted as` : "Your role"), el("h2", null, r.title));
    const close = el("button", "ghost-btn", "Clear");
    close.type = "button";
    close.addEventListener("click", clearRole);
    head.append(titleWrap, close);

    const stats = el("div", "detail-grid");
    const stat = (label, value) => {
      const s = el("div");
      s.append(el("div", "stat-label", label), el("div", "stat-value", value));
      return s;
    };
    stats.append(
      stat(`Workers (${COUNTRY_LABEL[state.country]})`, m ? fmtCount(m.workers) : "n/a"),
      stat("Average wage", m && m.workers ? fmtWage(m.wages / m.workers) : "n/a"),
      stat("Time AI can largely do", `${Math.round(highShare * 100)}%`),
    );
    const bars = el("div", "role-bars");
    bars.append(scoreBar("Exposure index", exposure, 100), scoreBar("Adoption index", adopted, 100));

    const split = el("ol", "role-split");
    for (const [pid, s] of alloc.slice(0, 8)) {
      const p = byId.get(pid);
      const li = el("li");
      const btn = el("button", "split-row");
      btn.type = "button";
      const bar = el("span", "split-bar");
      const fill = el("span");
      fill.style.width = `${Math.round(s * 100)}%`;
      bar.append(fill);
      btn.append(el("span", "split-pct", `${Math.round(s * 100)}%`), el("span", "split-name", p.name), el("span", "split-cap", fmtScore(p.capability)), bar);
      btn.title = `${p.name}: ${Math.round(s * 100)}% of this role's time, AI capability ${fmtScore(p.capability)}`;
      btn.addEventListener("click", () => select(pid));
      li.append(btn);
      split.append(li);
    }
    if (alloc.length > 8) split.append(el("li", "muted", `+${alloc.length - 8} smaller processes`));

    const tasks = el("ul", "role-tasks");
    r.tasks.forEach((t) => tasks.append(el("li", null, t)));

    // Vendors across this role's processes, weighted by time share.
    const vendorWeight = new Map();
    for (const [pid, s] of alloc) for (const x of byId.get(pid).products) vendorWeight.set(x.vendor, (vendorWeight.get(x.vendor) || 0) + s);
    const vendors = [...vendorWeight.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([v]) => v);
    const chips = el("div", "chips");
    vendors.forEach((v) => chips.append(el("span", "chip", v)));

    const section = (title, ...children) => {
      const s = el("div", "role-section");
      s.append(el("h3", null, title), ...children);
      return s;
    };
    const parts = [head];
    const aliasNote = state.roleAlias && (DATA.alias_notes || {})[state.roleAlias];
    if (aliasNote) {
      const ownSplit = aliasAlloc[state.roleAlias]
        ? `Worker numbers are for all ${r.title.toLowerCase()}; the time split below is for a typical ${state.roleAlias.toLowerCase()}.`
        : "The time split below is for the whole official category.";
      parts.push(el("p", "muted role-note", `${aliasNote}. ${ownSplit}`));
    }
    parts.push(stats, bars);
    if (r.scope === "partial") parts.push(el("p", "muted role-note", `Counts only the supply chain share of this job: ${r.scope_note}.`));
    parts.push(
      section("Where the time goes", el("p", "muted", "Share of time · AI capability (0–10). Click to open the process."), split),
      section("What the job involves (O*NET)", r.tasks.length ? tasks : el("p", "muted", "O*NET has no task list for this code.")),
    );
    if (vendors.length) parts.push(section("AI products touching this work", chips));
    box.replaceChildren(...parts);
  }

  // ---------- legends ----------
  function renderTreemapLegend() {
    const spec = METRICS[state.colorBy];
    const scale = colorScale();
    const [lo, hi] = spec.domain;
    const stops = d3.range(0, 1.0001, 0.1).map((t) => `${scale(lo + t * (hi - lo))} ${t * 100}%`).join(", ");
    const ramp = el("div", "ramp");
    const bar = el("div", "ramp-bar");
    bar.style.background = `linear-gradient(to right, ${stops})`;
    const ticks = el("div", "ramp-ticks");
    const mid = spec.kind === "div" ? 0 : (lo + hi) / 2;
    ticks.append(el("span", null, String(lo)), el("span", null, String(mid)), el("span", null, String(hi)));
    ramp.append(el("span", null, spec.label), bar, ticks);
    $("tm-legend").replaceChildren(ramp);
  }

  function renderScatterLegend() {
    const items = WORK_TYPES.map((w) => {
      const s = el("span", "swatch");
      const dot = el("i");
      dot.style.background = `var(${w.color})`;
      s.append(dot, document.createTextNode(w.label));
      return s;
    });
    $("sc-legend").replaceChildren(...items, el("span", "muted", "Bubble size = average wage"));
  }

  // ---------- treemap ----------
  const tmEl = $("treemap");
  function renderTreemap() {
    const width = tmEl.clientWidth;
    if (width < 50) return; // not laid out yet
    // Fill most of the viewport height beside the sidebar; fixed height on narrow screens.
    // Phones get a taller map so small groups keep usable boxes.
    const height = width < 640
      ? Math.round(Math.min(Math.max(width * 2, 680), 900))
      : Math.round(Math.min(Math.max(window.innerHeight - 190, 520), 940));
    tmEl.style.height = `${height}px`;
    // Group header text: the short description (when zoomed, a back link plus the longer description),
    // on up to three lines. If nothing fits, the hover title carries it.
    // A label may take at most this share of its group's height; reserving more than the group has
    // squeezes its boxes out of place (seen on phones, where some groups are only ~20px tall).
    const MAX_HEADER_SHARE = 0.45;
    const headerText = (mod, width, groupHeight) => {
      const options = state.module
        ? [`← All groups  ·  ${mod.short}: ${mod.description}`, `← All groups  ·  ${mod.short}`, "← All groups"]
        : [mod.short];
      for (const [font, lineH, small] of [[NAME_FONT, 14, false], [HEADER_SMALL_FONT, 13, true]]) {
        for (const text of options) {
          const lines = wrapCount(text, font, width - 10);
          const height = 6 + lineH * lines;
          if (lines <= 3 && height <= groupHeight * MAX_HEADER_SHARE) return { text, small, height };
        }
      }
      // No room for a label: keep a thin strip (name stays in the hover title and zoom view).
      return { text: "", small: false, height: Math.max(0, Math.min(4, groupHeight * 0.2)) };
    };
    const headerHeight = (node) => headerText(node.data.mod, node.x1 - node.x0, node.y1 - node.y0).height;

    // A focused module zooms to fill the whole map, so small modules (TM, IBP) are readable.
    const shown = state.module ? DATA.modules.filter((mod) => mod.id === state.module) : DATA.modules;
    const root = d3
      .hierarchy({ children: shown.map((mod) => ({ mod, children: procs.filter((p) => p.module === mod.id) })) })
      .sum((d) => (d.id ? Math.max(sizeOf(d), 0) : 0))
      .sort((a, b) => b.value - a.value);
    d3.treemap()
      .size([width, height])
      .paddingInner((d) => (d.depth === 0 ? 5 : 2))
      .paddingTop((d) => (d.depth === 1 ? headerHeight(d) + 2 : 0))
      .round(true)(root);

    const color = colorScale();
    const nodes = [];
    for (const modNode of root.children || []) {
      const mod = modNode.data.mod;
      const w = modNode.x1 - modNode.x0;
      const head = el("button", "tm-header");
      head.type = "button";
      head.dataset.module = mod.id;
      const header = headerText(mod, w, modNode.y1 - modNode.y0);
      Object.assign(head.style, { left: `${modNode.x0}px`, top: `${modNode.y0}px`, width: `${w}px`, height: `${header.height}px` });
      const groupWages = fmtMoney(d3.sum(modNode.leaves(), (l) => metricsOf(l.data).wages));
      head.title = state.module ? "Back to all groups" : `${mod.short}: ${groupWages} wages. Click to zoom in.`;
      if (header.small) head.classList.add("small");
      if (header.text) head.append(el("span", null, header.text));
      head.addEventListener("click", () => {
        state.module = state.module === mod.id ? null : mod.id;
        renderTreemap();
        onSelectionChange();
      });
      nodes.push(head);

      for (const leaf of modNode.children || []) {
        const p = leaf.data;
        const tw = leaf.x1 - leaf.x0;
        const th = leaf.y1 - leaf.y0;
        if (tw < 1 || th < 1) continue;
        const fill = color(p[state.colorBy]);
        const tile = el("button", "tm-tile");
        tile.type = "button";
        tile.dataset.id = p.id;
        tile.setAttribute("aria-label", `${p.name}, ${fmtMoney(metricsOf(p).wages)} wages, capability ${fmtScore(p.capability)}, adoption ${fmtScore(p.adoption)}`);
        Object.assign(tile.style, {
          left: `${leaf.x0}px`, top: `${leaf.y0}px`, width: `${tw}px`, height: `${th}px`,
          background: fill, color: inkOn(fill),
        });
        // Labels only where the whole name fits; tooltip and table carry the rest.
        const innerW = tw - 14;
        const valText = state.sizeBy === "wages" ? fmtMoney(metricsOf(p).wages) : fmtCount(metricsOf(p).workers);
        const showVal = th >= 48 && textWidth(valText, VALUE_FONT) <= innerW;
        const maxLines = Math.floor((th - 10 - (showVal ? 15 : 0)) / 14);
        if (maxLines >= 1 && wrapCount(p.name, NAME_FONT, innerW) <= maxLines) {
          tile.classList.add("has-label");
          tile.append(el("span", "t-name", p.name));
          if (showVal) tile.append(el("span", "t-val", valText));
        }
        tile.addEventListener("pointerenter", (e) => { setHover(p.id); showTip(p, e.clientX, e.clientY); });
        tile.addEventListener("pointermove", (e) => showTip(p, e.clientX, e.clientY));
        tile.addEventListener("pointerleave", () => { setHover(null); hideTip(); });
        tile.addEventListener("focus", () => {
          const r = tile.getBoundingClientRect();
          setHover(p.id);
          showTip(p, r.left + r.width / 2, r.bottom);
        });
        tile.addEventListener("blur", () => { setHover(null); hideTip(); });
        tile.addEventListener("click", () => select(p.id));
        nodes.push(tile);
      }
    }
    tmEl.replaceChildren(...nodes);
    renderTreemapLegend();
    applyHighlight();
  }

  // ---------- scatter ----------
  const scEl = $("scatter");
  let scatter = null; // { brushG, brush, plot, points }
  function renderScatter() {
    const width = scEl.clientWidth;
    if (width < 200) return; // not laid out yet
    const height = Math.round(Math.min(Math.max(width * 0.6, 380), 600));
    const margin = { top: 12, right: 16, bottom: 44, left: 44 };
    const iw = width - margin.left - margin.right;
    const ih = height - margin.top - margin.bottom;
    const x = d3.scaleLinear([0, 10], [0, iw]);
    const y = d3.scaleLinear([0, 10], [ih, 0]);
    const r = d3.scaleSqrt(d3.extent(procs, avgWage), width < 480 ? [4, 10] : [4, 13]);

    const svg = d3.create("svg").attr("viewBox", `0 0 ${width} ${height}`).attr("height", height)
      .attr("role", "img").attr("aria-label", "Scatter of AI capability against adoption for each process");
    const plot = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    const ticks = d3.range(0, 11, 2);
    const grid = plot.append("g").attr("class", "grid");
    grid.selectAll(".gx").data(ticks).join("line").attr("x1", x).attr("x2", x).attr("y1", 0).attr("y2", ih);
    grid.selectAll(".gy").data(ticks).join("line").attr("y1", y).attr("y2", y).attr("x1", 0).attr("x2", iw);
    plot.selectAll(".tx").data(ticks).join("text").attr("class", "axis-label")
      .attr("x", x).attr("y", ih + 16).attr("text-anchor", "middle").text((d) => d);
    plot.selectAll(".ty").data(ticks).join("text").attr("class", "axis-label")
      .attr("x", -8).attr("y", (d) => y(d) + 4).attr("text-anchor", "end").text((d) => d);
    plot.append("text").attr("class", "axis-title").attr("x", iw).attr("y", ih + 36).attr("text-anchor", "end")
      .text("AI capability: what AI can do today →");
    plot.append("text").attr("class", "axis-title").attr("transform", `translate(${-32},0) rotate(-90)`)
      .attr("text-anchor", "end").text("Adoption: how far use has spread →");

    plot.append("line").attr("class", "diag").attr("x1", x(0)).attr("y1", y(0)).attr("x2", x(10)).attr("y2", y(10));

    const quads = [
      { t: "Mainstream", x: iw - 6, y: 14, a: "end" },
      { t: "Untapped", x: iw - 6, y: ih - 8, a: "end" },
      { t: "Human-led", x: 6, y: ih - 8, a: "start" },
      { t: "Ahead of the tech", x: 6, y: 14, a: "start" },
    ];
    plot.selectAll(".quad").data(quads).join("text").attr("class", "quad")
      .attr("x", (d) => d.x).attr("y", (d) => d.y).attr("text-anchor", (d) => d.a).text((d) => d.t);

    // Scores are whole numbers, so many processes share a spot; a small fixed nudge per process keeps them visible.
    const nudge = (id, salt) => {
      let h = 2166136261;
      for (const ch of id + salt) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
      return ((h >>> 0) / 4294967295 - 0.5) * 0.44;
    };
    const points = procs.map((p) => ({
      p,
      cx: x(Math.min(10, Math.max(0, p.capability + nudge(p.id, "x")))),
      cy: y(Math.min(10, Math.max(0, p.adoption + nudge(p.id, "y")))),
      r: r(avgWage(p)),
    }));
    const typeColor = new Map(WORK_TYPES.map((w) => [w.id, `var(${w.color})`]));
    plot.append("g").selectAll("circle")
      .data([...points].sort((a, b) => b.r - a.r))
      .join("circle")
      .attr("class", "dot").attr("data-id", (d) => d.p.id)
      .attr("cx", (d) => d.cx).attr("cy", (d) => d.cy).attr("r", (d) => d.r)
      .attr("fill", (d) => typeColor.get(d.p.work_type));

    // Hover and click go through the brush overlay; the nearest point within 24px wins.
    const delaunay = d3.Delaunay.from(points, (d) => d.cx, (d) => d.cy);
    const nearest = (mx, my) => {
      const i = delaunay.find(mx, my);
      const d = points[i];
      return d && Math.hypot(d.cx - mx, d.cy - my) <= Math.max(24, d.r + 6) ? d.p : null;
    };

    const brush = d3.brush().extent([[0, 0], [iw, ih]]).on("end", (event) => {
      if (!event.sourceEvent) return; // programmatic clear
      if (!event.selection) {
        const [mx, my] = d3.pointer(event.sourceEvent, plot.node());
        const p = nearest(mx, my);
        if (state.brush) { state.brush = null; onSelectionChange(); }
        if (p) select(p.id);
        return;
      }
      const [[x0, y0], [x1, y1]] = event.selection;
      state.brush = new Set(points.filter((d) => d.cx >= x0 && d.cx <= x1 && d.cy >= y0 && d.cy <= y1).map((d) => d.p.id));
      onSelectionChange();
    });
    const brushG = plot.append("g").attr("class", "brush").call(brush);
    brushG.on("pointermove", (event) => {
      const [mx, my] = d3.pointer(event, plot.node());
      const p = nearest(mx, my);
      if (p) { setHover(p.id); showTip(p, event.clientX, event.clientY); } else if (state.hover) { setHover(null); hideTip(); }
      brushG.select(".overlay").style("cursor", p ? "pointer" : "crosshair");
    });
    brushG.on("pointerleave", () => { setHover(null); hideTip(); });

    scEl.replaceChildren(svg.node());
    scatter = { brushG, brush };
    applyHighlight();
  }

  // ---------- detail panel ----------
  function renderDetail() {
    const box = $("detail");
    const p = state.selected && byId.get(state.selected);
    if (!p) {
      box.replaceChildren(
        el("h2", null, "Process details"),
        el("p", "empty", "Click a box in the process map, a dot in the scatter, or a row in the data table."),
      );
      return;
    }
    const mod = modulesById.get(p.module);
    const m = metricsOf(p);
    const isPlaceholder = p.scored_by === "placeholder";
    const isExpert = p.scored_by === "expert" || p.scored_by === "llm+expert";

    const head = el("div", "detail-head");
    head.append(el("h2", null, p.name), el("span", "badge", mod.short), el("span", "badge", `${p.work_type} work`));
    if (isExpert) head.append(el("span", "badge", "Hand-scored"));
    else if (p.hand_score && scoring.enabled) head.append(el("span", "badge", "To be hand-scored"));
    if (p.scored_by === "llm") head.append(el("span", "badge", "Scored by Claude Opus 5.5"));
    if (isPlaceholder) head.append(el("span", "badge", "Placeholder score"));

    const stat = (label, value, meter) => {
      const s = el("div");
      s.append(el("div", "stat-label", label), el("div", "stat-value", value));
      if (meter != null) {
        const bar = el("div", "meter");
        const fill = el("span");
        fill.style.width = `${Math.max(0, Math.min(100, meter * 10))}%`;
        bar.append(fill);
        s.append(bar);
      }
      return s;
    };
    const grid = el("div", "detail-grid");
    grid.append(
      stat("Workers", fmtCount(m.workers)),
      stat("Total wages", fmtMoney(m.wages)),
      stat("Average wage", fmtWage(avgWage(p))),
      stat("AI capability", fmtScore(p.capability), p.capability),
      stat("Adoption", fmtScore(p.adoption), p.adoption),
      stat("Gap", fmtGap(p.gap)),
    );

    const col = (title, ...children) => {
      const c = el("div");
      c.append(el("h3", null, title), ...children);
      return c;
    };
    const chips = el("div", "chips");
    p.ai_type.forEach((t) => chips.append(el("span", "chip", t)));
    const why = el("p", "muted", p.rationale || "No rationale yet. It is written when the process is scored.");

    // Who does this work (North America), each opening that role.
    const jobList = el("ul", "job-list");
    p.jobs.forEach((j) => {
      const li = el("li");
      const btn = el("button", "link-btn", j.title);
      btn.type = "button";
      btn.addEventListener("click", () => {
        const fromSheet = sheet.open;
        closeSheet();
        pickRole({ soc: j.soc, label: rolesBySoc.get(j.soc).title, alias: null });
        if (fromSheet) $("role-card").scrollIntoView({ behavior: "smooth", block: "start" });
      });
      li.append(btn, el("span", "muted", ` · ${fmtCount(j.workers)} full-time equivalents`));
      jobList.append(li);
    });

    const cols = el("div", "detail-cols");
    if (scoring.enabled) cols.append(scoreEditor(p));
    cols.append(
      col(`AI products doing this (${p.products.length})`, productList(p)),
      col(`Evidence (${(p.evidence || []).length})`, evidenceList(p)),
      col("AI type", chips, why),
      col("Who does this work", p.jobs.length ? jobList : el("p", "muted", "No workers allocated yet.")),
    );

    const module = el("p", "detail-module",
      mod.has_sap ? `${mod.name}, modelled on ${mod.sap}` : `${mod.name}: carrier operations, no SAP module`);
    box.replaceChildren(head, module, el("p", "detail-desc", p.description), grid, cols);
    if (SIGNUP.url) box.append(signupForm);
  }

  // ---------- launch updates signup (end of the detail panel) ----------
  // Built once and re-attached on every render, so a half-typed email or the thank-you survives.
  // Saves the email with the process that was open, plus the country and role in view.
  const signupForm = buildSignup();
  function buildSignup() {
    const form = el("form", "signup");
    const input = el("input");
    Object.assign(input, { type: "email", name: "email", required: true, maxLength: 254, autocomplete: "email", placeholder: "you@company.com" });
    input.setAttribute("aria-label", "Email address");
    // Hidden from people; form-filling bots fill it in.
    const trap = el("input", "signup-trap");
    Object.assign(trap, { type: "text", name: "website", tabIndex: -1, autocomplete: "off" });
    trap.setAttribute("aria-hidden", "true");
    const send = el("button", "primary-btn", "Sign up");
    send.type = "submit";
    const row = el("div", "signup-row");
    row.append(input, send);
    const status = el("p", "signup-status");
    status.setAttribute("role", "status");
    form.append(
      el("h3", null, "Get email updates on the latest AI developments in your domain"),
      row, trap, status,
    );

    const thank = () => form.replaceChildren(el("h3", null, "You're signed up"), el("p", "muted", "You'll get email updates on the latest AI developments in your domain."));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const p = state.selected && byId.get(state.selected);
      if (!p) return;
      if (trap.value) { thank(); return; }
      send.disabled = true;
      status.textContent = "Saving…";
      try {
        const r = await fetch(`${SIGNUP.url}/rest/v1/rpc/subscribe_interest`, {
          method: "POST",
          headers: { apikey: SIGNUP.key, "Content-Type": "application/json" },
          body: JSON.stringify({
            p_email: input.value.trim(),
            p_process_id: p.id,
            p_process_name: p.name,
            p_process_group: modulesById.get(p.module).short,
            p_country: state.country,
            p_role: state.role ? state.roleAlias || rolesBySoc.get(state.role).title : null,
          }),
        });
        if (r.ok) { thank(); return; }
        status.textContent = r.status === 429 ? "Too many signups right now. Try again later."
          : r.status === 400 ? "That email address doesn't look right."
          : "Couldn't save that. Try again in a moment.";
      } catch (_) {
        status.textContent = "Couldn't reach the server. Try again in a moment.";
      }
      send.disabled = false;
    });
    return form;
  }

  const SOURCE_LABEL = { independent: "Independent study", news: "News report", vendor_claimed: "Company-reported", analyst: "Analyst" };
  function evidenceList(p) {
    const ev = p.evidence || [];
    if (!ev.length) return el("p", "muted", "No sourced evidence collected yet.");
    const wrap = el("div", "products");
    for (const x of ev) {
      const card = el("a", "product evidence");
      Object.assign(card, { href: x.url, target: "_blank", rel: "noopener noreferrer" });
      const head = el("div", "product-head");
      head.append(el("strong", null, x.company), el("span", `badge source-${x.source_type}`, SOURCE_LABEL[x.source_type] || x.source_type));
      const metric = el("div", "evidence-metric");
      metric.append(el("span", "muted", `${x.metric}: `), el("strong", null, x.value));
      card.append(head, el("div", "product-note", x.claim), metric, el("div", "product-hq", `${x.year} · Source ↗`));
      wrap.append(card);
    }
    return wrap;
  }

  // Product cards: vendor, what it does here, maturity, HQ, and a link out when there is one.
  function productList(p) {
    const wrap = el("div", "products");
    if (!p.products.length) {
      wrap.append(el("p", "muted", "No AI-specialized product mapped yet. Know one? It's worth adding."));
      return wrap;
    }
    for (const x of p.products) {
      const card = el(x.url ? "a" : "div", "product");
      if (x.url) {
        card.href = x.url;
        card.target = "_blank";
        card.rel = "noopener noreferrer";
      }
      const head = el("div", "product-head");
      head.append(el("strong", null, x.vendor), el("span", "product-name", x.product), el("span", `badge maturity-${x.maturity}`, MATURITY[x.maturity] || x.maturity));
      card.append(head, el("div", "product-note", x.note));
      if (x.hq || x.url) card.append(el("div", "product-hq", [x.hq, x.url ? "Visit site ↗" : ""].filter(Boolean).join("  ·  ")));
      wrap.append(card);
    }
    wrap.append(el("p", "product-disclaimer", "Examples, not endorsements. Capabilities are as the vendors describe them; checked October 2026."));
    return wrap;
  }

  // ---------- exposure index by group ----------
  function renderGroupBars() {
    const box = $("group-bars");
    const ids = activeIds();
    const rows = DATA.modules.map((mod) => {
      const set = procs.filter((p) => p.module === mod.id);
      return { mod, exp: indexOf(set, "capability"), ado: indexOf(set, "adoption"), wages: d3.sum(set, (p) => metricsOf(p).wages), active: !ids || set.some((p) => ids.has(p.id)) };
    }).sort((a, b) => b.exp - a.exp);
    box.replaceChildren(...rows.map((r) => {
      const row = el("button", `gb-row${r.active ? "" : " dim"}${state.module === r.mod.id ? " active" : ""}`);
      row.type = "button";
      row.title = `${r.mod.short}: exposure ${Math.round(r.exp)}, adoption ${Math.round(r.ado)}, ${fmtMoney(r.wages)} wages. Click to zoom the map.`;
      const track = el("span", "gb-track");
      const bar = el("span", "gb-bar");
      bar.style.width = `${r.exp}%`;
      const tick = el("span", "gb-tick");
      tick.style.left = `${r.ado}%`;
      track.append(bar, tick);
      row.append(el("span", "gb-label", r.mod.short), track, el("span", "gb-value", String(Math.round(r.exp))));
      row.addEventListener("click", () => {
        state.module = state.module === r.mod.id ? null : r.mod.id;
        renderTreemap();
        onSelectionChange();
      });
      return row;
    }));
    const key = (cls, text) => {
      const s = el("span", "swatch");
      s.append(el("i", cls), document.createTextNode(text));
      return s;
    };
    $("gb-legend").replaceChildren(key("key-bar", "Exposure"), key("key-tick", "Adoption"));
  }

  // ---------- table ----------
  const COLUMNS = [
    { key: "name", label: "Process", get: (p) => p.name },
    { key: "module", label: "Group", get: (p) => modulesById.get(p.module).short },
    { key: "workers", label: "Workers", num: true, get: (p) => metricsOf(p).workers, fmt: fmtCount },
    { key: "wages", label: "Total wages", num: true, get: (p) => metricsOf(p).wages, fmt: fmtMoney },
    { key: "avg", label: "Avg wage", num: true, get: avgWage, fmt: fmtWage },
    { key: "capability", label: "Capability", num: true, get: (p) => p.capability, fmt: fmtScore },
    { key: "adoption", label: "Adoption", num: true, get: (p) => p.adoption, fmt: fmtScore },
    { key: "gap", label: "Gap", num: true, get: (p) => p.gap, fmt: fmtGap },
    { key: "products", label: "AI products", num: true, get: (p) => p.products.length },
  ];
  let sort = { key: "wages", dir: -1 };
  function renderTable() {
    const table = $("data-table");
    const tr = el("tr");
    COLUMNS.forEach((c) => {
      const th = el("th", c.num ? "num" : null, c.label + (sort.key === c.key ? (sort.dir < 0 ? " ↓" : " ↑") : ""));
      th.addEventListener("click", () => {
        sort = { key: c.key, dir: sort.key === c.key ? -sort.dir : c.num ? -1 : 1 };
        renderTable();
      });
      tr.append(th);
    });
    table.tHead.replaceChildren(tr);

    const col = COLUMNS.find((c) => c.key === sort.key);
    const rows = [...procs].sort((a, b) => {
      const va = col.get(a), vb = col.get(b);
      return (va < vb ? -1 : va > vb ? 1 : 0) * sort.dir;
    });
    table.tBodies[0].replaceChildren(...rows.map((p) => {
      const row = el("tr");
      row.dataset.id = p.id;
      COLUMNS.forEach((c) => row.append(el("td", c.num ? "num" : null, c.fmt ? c.fmt(c.get(p)) : c.get(p))));
      row.addEventListener("click", () => select(p.id));
      return row;
    }));
    applyHighlight();
  }

  // ---------- linking ----------
  function applyHighlight() {
    const ids = activeIds();
    const isDim = (id) => ids && !ids.has(id);
    tmEl.querySelectorAll(".tm-tile").forEach((t) => {
      const id = t.dataset.id;
      t.classList.toggle("dim", Boolean(isDim(id)));
      t.classList.toggle("hover", state.hover === id);
      t.classList.toggle("selected", state.selected === id);
    });
    tmEl.querySelectorAll(".tm-header").forEach((h) => {
      h.classList.toggle("active", state.module === h.dataset.module);
      h.classList.toggle("dim", Boolean(state.module && state.module !== h.dataset.module));
    });
    scEl.querySelectorAll(".dot").forEach((d) => {
      const id = d.dataset.id;
      d.classList.toggle("dim", Boolean(isDim(id)));
      d.classList.toggle("hover", state.hover === id);
      d.classList.toggle("selected", state.selected === id);
      if (state.selected === id || state.hover === id) d.parentNode.appendChild(d); // draw on top
    });
    $("data-table").querySelectorAll("tbody tr").forEach((r) => {
      r.classList.toggle("dim", Boolean(isDim(r.dataset.id)));
      r.classList.toggle("selected", state.selected === r.dataset.id);
    });
  }

  function onSelectionChange() {
    const ids = activeIds();
    const parts = [];
    if (state.role) parts.push(`${rolesBySoc.get(state.role).title} (role)`);
    if (state.module) parts.push(modulesById.get(state.module).short);
    if (state.brush) parts.push(`${state.brush.size} processes in scatter selection`);
    $("selection-note").textContent = ids ? `Showing: ${parts.join(" + ")}` : "";
    $("f-clear").hidden = !ids && !state.selected;
    renderSummary();
    renderGroupBars();
    applyHighlight();
    syncHash();
  }

  function clearAll() {
    const wasZoomed = Boolean(state.module);
    state.module = null;
    state.brush = null;
    state.selected = null;
    state.role = null;
    state.roleAlias = null;
    $("role-input").value = "";
    if (scatter) scatter.brushG.call(scatter.brush.move, null);
    if (wasZoomed) renderTreemap();
    onSelectionChange();
    renderRole();
    renderDetail();
  }

  function renderAll() {
    tipFor = null; // country change alters the numbers in the hover card
    renderSummary();
    renderTreemap();
    renderScatter();
    renderScatterLegend();
    renderTable();
    renderGroupBars();
    renderDetail();
  }

  // ---------- detail sheet (phones and tablets) ----------
  // The sidebar's detail panel moves into a modal dialog while a process is open, then moves back.
  const sheet = $("detail-sheet");
  const sheetBody = $("sheet-body");
  const detailEl = $("detail");
  // Holds the panel's height in the sidebar while it is in the sheet, so the page never shifts
  // (iOS Safari has no scroll anchoring to hide a shift).
  const detailSpacer = el("div", "detail-spacer");
  function isCompact() {
    return window.matchMedia("(max-width: 1000px)").matches;
  }
  function openSheet() {
    if (!sheet.open) {
      detailSpacer.style.height = `${detailEl.offsetHeight}px`;
      detailEl.replaceWith(detailSpacer);
      sheetBody.append(detailEl);
      document.documentElement.classList.add("sheet-open");
      sheet.showModal();
    }
    sheetBody.scrollTop = 0;
  }
  // Puts the panel back in the sidebar and clears the selection. Safe to call more than once.
  function restoreDetail() {
    if (detailSpacer.isConnected) detailSpacer.replaceWith(detailEl);
    document.documentElement.classList.remove("sheet-open");
    if (state.selected) {
      state.selected = null;
      applyHighlight();
      renderDetail();
      syncHash();
    }
  }
  // Clean up synchronously rather than waiting for the dialog's "close" event, which is not
  // dispatched reliably in every browser; the event listener below is only a backstop.
  function closeSheet() {
    if (!sheet.open && !detailSpacer.isConnected) return; // sheet not in use (e.g. desktop resize)
    if (sheet.open) sheet.close();
    restoreDetail();
  }
  // Opens the sheet for a process chosen by a link, leaving the empty panel's height in the sidebar.
  function openSheetFor(processId) {
    state.selected = null;
    renderDetail();
    state.selected = processId;
    openSheet();
  }
  sheet.addEventListener("cancel", (e) => { e.preventDefault(); closeSheet(); }); // Esc
  sheet.addEventListener("close", () => { if (detailSpacer.isConnected) restoreDetail(); });
  // A tap on the dimmed backdrop lands on the dialog element itself.
  sheet.addEventListener("click", (e) => { if (e.target === sheet) closeSheet(); });
  sheet.querySelector(".sheet-close").addEventListener("click", closeSheet);

  // ---------- controls (segmented slicers above the map) ----------
  const SEG_ACTIONS = {
    country: () => renderAll(),
    colorBy: () => renderTreemap(),
    sizeBy: () => {
      $("tm-size-label").textContent = state.sizeBy === "wages" ? "total wages" : "number of workers";
      renderTreemap();
    },
  };
  function syncSegments() {
    document.querySelectorAll(".seg").forEach((seg) => {
      seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(state[seg.dataset.key] === b.dataset.value)));
    });
  }
  document.querySelectorAll(".seg").forEach((seg) => {
    seg.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      if (state[seg.dataset.key] === b.dataset.value) return;
      state[seg.dataset.key] = b.dataset.value;
      syncSegments();
      SEG_ACTIONS[seg.dataset.key]();
      syncHash();
    }));
  });
  $("f-clear").addEventListener("click", clearAll);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !sheet.open) clearAll(); });

  // ---------- shareable links: state lives in the URL hash ----------
  function syncHash() {
    const params = new URLSearchParams();
    if (state.country !== "NA") params.set("c", state.country);
    if (state.colorBy !== "capability") params.set("colour", state.colorBy);
    if (state.sizeBy !== "wages") params.set("size", state.sizeBy);
    if (state.role) params.set("role", state.role);
    if (state.roleAlias) params.set("as", state.roleAlias);
    if (state.module) params.set("group", state.module);
    if (state.selected) params.set("p", state.selected);
    const hash = params.toString();
    history.replaceState(null, "", hash ? `#${hash}` : location.pathname + location.search);
  }
  function readHash() {
    const params = new URLSearchParams(location.hash.slice(1));
    const pick = (key, allowed, field) => { const v = params.get(key); if (v && allowed.includes(v)) state[field] = v; };
    pick("c", ["NA", "US", "CA"], "country");
    pick("colour", Object.keys(METRICS), "colorBy");
    pick("size", ["wages", "workers"], "sizeBy");
    const role = params.get("role");
    if (role && rolesBySoc.has(role)) {
      state.role = role;
      const alias = params.get("as");
      state.roleAlias = alias && rolesBySoc.get(role).aliases.includes(alias) ? alias : null;
      $("role-input").value = state.roleAlias || rolesBySoc.get(role).title;
    }
    const group = params.get("group");
    if (group && modulesById.has(group)) state.module = group;
    const sel = params.get("p");
    if (sel && byId.has(sel)) state.selected = sel;
  }

  // A pasted link that only changes the hash does not reload the page; apply it in place.
  window.addEventListener("hashchange", () => {
    closeSheet();
    Object.assign(state, { country: "NA", colorBy: "capability", sizeBy: "wages", role: null, roleAlias: null, module: null, selected: null, brush: null });
    $("role-input").value = "";
    readHash();
    if (state.selected && isCompact()) openSheetFor(state.selected);
    syncSegments();
    $("tm-size-label").textContent = state.sizeBy === "wages" ? "total wages" : "number of workers";
    if (scatter) scatter.brushG.call(scatter.brush.move, null);
    renderAll();
    renderRole();
    onSelectionChange();
  });

  function toast(message) {
    const t = $("toast");
    t.textContent = message;
    t.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { t.hidden = true; }, 2200);
  }

  $("copy-link").addEventListener("click", async () => {
    syncHash();
    try {
      await navigator.clipboard.writeText(location.href);
      toast("Link copied");
    } catch (_) {
      toast("Copy failed: copy the address bar instead");
    }
  });

  // ---------- image export for posts (html-to-image is loaded on first use) ----------
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error(`could not load ${src}`));
      document.head.append(s);
    });
  }
  $("download-png").addEventListener("click", async () => {
    const card = $("map-card");
    const btn = $("download-png");
    btn.disabled = true;
    try {
      if (!window.htmlToImage) await loadScript("https://cdn.jsdelivr.net/npm/html-to-image@1.11.11/dist/html-to-image.js");
      hideTip();
      card.classList.add("exporting");
      const url = await window.htmlToImage.toPng(card, { pixelRatio: 2, backgroundColor: cssVar("--surface") });
      const a = document.createElement("a");
      a.href = url;
      a.download = `supply-chain-ai-index-${state.country.toLowerCase()}${state.role ? `-${state.role}` : ""}.png`;
      a.click();
      toast("Image downloaded");
    } catch (err) {
      toast(`Image export failed: ${err.message}`);
    } finally {
      card.classList.remove("exporting");
      btn.disabled = false;
    }
  });

  // ---------- local scoring mode (only when served by scripts/score_server.py) ----------
  const scoring = { enabled: false };
  async function detectScoring() {
    if (!window.SCAI_SCORING) return;
    try {
      const r = await fetch("api/scores", { cache: "no-store" });
      scoring.enabled = r.ok && (r.headers.get("content-type") || "").includes("application/json");
    } catch (_) {
      scoring.enabled = false;
    }
    if (scoring.enabled) {
      renderScoringPanel();
      renderDetail();
    }
  }

  function renderScoringPanel() {
    const panel = $("scoring-panel");
    panel.hidden = !scoring.enabled;
    if (!scoring.enabled) return;
    const queue = procs.filter((p) => p.hand_score && !["expert", "llm+expert"].includes(p.scored_by));
    const done = procs.filter((p) => ["expert", "llm+expert"].includes(p.scored_by)).length;
    const list = el("ol", "queue");
    queue.forEach((p) => {
      const li = el("li");
      const b = el("button", "link-btn", `${p.name} · ${modulesById.get(p.module).short}`);
      b.type = "button";
      b.addEventListener("click", () => { state.selected = null; select(p.id); });
      li.append(b);
      list.append(li);
    });
    panel.replaceChildren(
      el("div", "role-kicker", "Scoring mode · local only"),
      el("p", "muted", `${done} of ${procs.length} processes hand-scored. ${queue.length} of your processes still carry the AI first pass. Pick one, then edit its scores in the details below.`),
      queue.length ? list : el("p", "muted", "Your queue is empty."),
    );
  }

  function scoreEditor(p) {
    const form = el("form", "score-editor");
    const field = (label, input) => {
      const l = el("label");
      l.append(el("span", null, label), input);
      return l;
    };
    const num = (name, value) => {
      const i = document.createElement("input");
      Object.assign(i, { type: "number", name, min: 0, max: 10, step: 0.5, value, required: true });
      return i;
    };
    const area = (name, value, placeholder) => {
      const t = document.createElement("textarea");
      Object.assign(t, { name, value, placeholder, rows: 2 });
      return t;
    };
    const rationale = area("rationale", p.rationale, "Why this score, in one line");
    rationale.required = true;
    const status = el("span", "muted");
    const save = el("button", "primary-btn", "Save score");
    save.type = "submit";
    const nums = el("div", "editor-nums");
    nums.append(field("AI capability (0–10)", num("capability", p.capability)), field("Adoption (0–10)", num("adoption", p.adoption)));
    form.append(
      el("h3", null, "Your score"),
      nums,
      field("Reason", rationale),
      field("What you changed from the AI first pass (optional)", area("override_note", "", "e.g. adoption lower: most shippers still tender by email")),
      save,
      status,
    );
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(form));
      save.disabled = true;
      status.textContent = "Saving and rebuilding…";
      try {
        const r = await fetch("api/scores", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ process_id: p.id, ...data }),
        });
        const out = await r.json();
        if (!r.ok) throw new Error(out.error || r.statusText);
        syncHash();
        location.reload();
      } catch (err) {
        status.textContent = `Not saved: ${err.message}`;
        save.disabled = false;
      }
    });
    return form;
  }

  // Re-layout when the chart column's width or the window height changes (the map is sized to the viewport).
  let resizeTimer;
  let lastSize = "";
  const onResize = () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      const size = `${tmEl.clientWidth}x${window.innerHeight}`;
      if (size === lastSize) return;
      lastSize = size;
      if (!isCompact()) closeSheet();
      renderTreemap();
      renderScatter();
    }, 120);
  };
  new ResizeObserver(onResize).observe(document.querySelector(".main"));
  window.addEventListener("resize", onResize);

  // ---------- boot ----------
  readHash();
  syncSegments();
  $("tm-size-label").textContent = state.sizeBy === "wages" ? "total wages" : "number of workers";
  const ph = DATA.placeholder;
  const handScored = procs.filter((p) => ["expert", "llm+expert"].includes(p.scored_by)).length;
  // Small credit line under the title, like the original reference; the banner is only for placeholder data.
  $("scored-by").textContent = handScored
    ? `Scored by Claude Opus 5.5, ${handScored} ${handScored === 1 ? "process" : "processes"} reviewed by hand`
    : "Scored by Claude Opus 5.5";
  const banner = $("placeholder-banner");
  if (ph.metrics || ph.scores) {
    banner.replaceChildren(el("strong", null, "Placeholder numbers. "), document.createTextNode("Some wages, worker counts or AI scores are generated stand-ins, not research."));
  }
  banner.hidden = !(ph.metrics || ph.scores);
  const src = DATA.sources || {};
  document.querySelectorAll("[data-src]").forEach((n) => { n.textContent = src[n.dataset.src] || ""; });
  $("generated").textContent = [
    `Data built ${DATA.generated}.`,
    src.US && `US: ${src.US}.`,
    src.CA && `Canada: ${src.CA}.`,
    src.fx && `${src.fx}.`,
    src.tasks && `Job tasks: ${src.tasks}.`,
    "Box area is total wages (in-scope workers × time share × mean wage).",
  ].filter(Boolean).join(" ");
  $("export-src").textContent = `Workers and wages: ${src.US}; ${src.CA}. ${$("scored-by").textContent}. ${location.host.endsWith("github.io") ? location.href.split("#")[0] : "github.com/msachet5/supplychain-ai-index"}`;
  if (state.selected && isCompact()) openSheetFor(state.selected); // shared link to a process
  renderAll();
  renderRole();
  onSelectionChange();
  if (state.selected) applyHighlight();
  detectScoring();
})();
