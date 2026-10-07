/* Explore, What-if, Policy and Priorities views. Data comes from /api/whatif/*. */
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v) => v !== null && v !== undefined && Number.isFinite(Number(v));
  const fmt = (v, d = 1) => (num(v) ? Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: 0 }) : "n/a");
  const sign = (v, d = 1) => (num(v) ? (v > 0 ? "+" : v < 0 ? "−" : "") + fmt(Math.abs(v), d) : "n/a");

  async function api(path, body) {
    const response = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || response.statusText);
    return data;
  }

  const state = { meta: null, geometry: null, scen: null, ready: null };
  const FLEET_COLORS = { electric: "#2563eb", hev_sedan: "#0f8a5f", hev_suv: "#48a868", ice_sedan: "#f59e0b", ice_suv: "#ef4444", "ice_van/pickup": "#7c3aed" };

  // ------------------------------------------------------------------ colour
  const SEQ = [[255, 253, 240], [255, 239, 171], [255, 213, 97], [254, 178, 76], [240, 96, 35], [189, 0, 38]];
  const DIV = [[37, 99, 235], [147, 185, 247], [250, 250, 250], [253, 186, 116], [220, 70, 20]];
  const SEQ_BLUE = [[247, 251, 255], [198, 219, 239], [107, 174, 214], [33, 113, 181], [8, 48, 107]];
  function ramp(stops, t) {
    t = Math.min(1, Math.max(0, t));
    const scaled = t * (stops.length - 1);
    const i = Math.min(stops.length - 2, Math.floor(scaled));
    const f = scaled - i;
    return `rgb(${stops[i].map((c, k) => Math.round(c + (stops[i + 1][k] - c) * f)).join(",")})`;
  }
  function makeScale(min, max, diverging, stops = SEQ) {
    if (diverging) {
      const m = Math.max(Math.abs(min), Math.abs(max)) || 1;
      return { min: -m, max: m, stops: DIV, color: (v) => ramp(DIV, (v + m) / (2 * m)) };
    }
    const span = max - min || 1;
    return { min, max, stops, color: (v) => ramp(stops, Math.pow(Math.max(0, (v - min) / span), 0.8)) };
  }
  function drawLegend(el, scale, unit) {
    const gradient = Array.from({ length: 9 }, (_, i) => scale.color(scale.min + ((scale.max - scale.min) * i) / 8)).join(",");
    el.innerHTML = `<span>${fmt(scale.min, 2)}</span><div class="legend-bar" style="background:linear-gradient(90deg,${gradient})"></div><span>${fmt(scale.max, 2)} ${esc(unit)}</span><span>· hatched grey = no value</span>`;
  }

  // --------------------------------------------------------------------- map
  class MapView {
    constructor(root, opts = {}) {
      this.root = root;
      this.canvas = root.querySelector("canvas");
      this.tip = root.querySelector(".map-tip");
      this.ctx = this.canvas.getContext("2d");
      this.opts = opts;
      this.fill = () => null;
      this.outline = () => null;
      this.tipHtml = () => "";
      this.selected = null;
      this.paths = [];
      this.view = { z: 1, x: 0, y: 0 };
      this.frame = 0;
      const controls = document.createElement("div");
      controls.className = "wmap-controls";
      controls.innerHTML = '<button type="button" data-z="in" aria-label="Zoom in">+</button><button type="button" data-z="out" aria-label="Zoom out">−</button><button type="button" data-z="reset" aria-label="Reset view">⟲</button>';
      root.append(controls);
      controls.addEventListener("click", (e) => {
        const z = e.target.dataset.z;
        if (z === "reset") this.view = { z: 1, x: 0, y: 0 };
        else this.zoomAt(this.w / 2, this.h / 2, z === "in" ? 1.3 : 1 / 1.3);
        this.schedule();
      });
      let drag = null;
      root.addEventListener("mousedown", (e) => { if (e.target.closest(".wmap-controls")) return; drag = { x: e.clientX, y: e.clientY, moved: false }; root.classList.add("dragging"); });
      window.addEventListener("mousemove", (e) => {
        if (drag) {
          const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
          if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
          this.view.x += dx; this.view.y += dy; drag.x = e.clientX; drag.y = e.clientY;
          this.schedule();
        }
      });
      window.addEventListener("mouseup", () => { root.classList.remove("dragging"); setTimeout(() => { drag = null; }, 0); });
      this.canvas.addEventListener("click", (e) => {
        if (drag && drag.moved) return;
        const fsa = this.hit(e);
        this.selected = fsa;
        this.schedule();
        if (this.opts.onSelect) this.opts.onSelect(fsa);
      });
      this.canvas.addEventListener("mousemove", (e) => {
        if (drag) return;
        const fsa = this.hit(e);
        if (!fsa) { this.tip.style.display = "none"; return; }
        const r = root.getBoundingClientRect();
        this.tip.innerHTML = this.tipHtml(fsa);
        this.tip.style.display = "block";
        this.tip.style.left = `${Math.min(e.clientX - r.left + 14, r.width - 250)}px`;
        this.tip.style.top = `${Math.min(e.clientY - r.top + 14, r.height - 80)}px`;
      });
      this.canvas.addEventListener("mouseleave", () => { this.tip.style.display = "none"; });
      this.canvas.addEventListener("wheel", (e) => {
        e.preventDefault();
        const r = this.canvas.getBoundingClientRect();
        this.zoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.15 : 1 / 1.15);
        this.schedule();
      }, { passive: false });
      new ResizeObserver(() => this.resize()).observe(root);
    }
    setGeometry(g) { this.features = g.features; this.bounds = g.bounds; this.resize(); }
    resize() {
      const r = this.canvas.getBoundingClientRect();
      if (!r.width || !this.bounds) return;
      this.w = r.width; this.h = r.height; this.dpr = window.devicePixelRatio || 1;
      this.canvas.width = Math.round(r.width * this.dpr); this.canvas.height = Math.round(r.height * this.dpr);
      const [minx, miny, maxx, maxy] = this.bounds;
      const scale = Math.min(this.w / (maxx - minx), this.h / (maxy - miny));
      this.base = { scale, ox: (this.w - (maxx - minx) * scale) / 2, oy: (this.h - (maxy - miny) * scale) / 2 };
      this.schedule();
    }
    zoomAt(px, py, factor) {
      const z = Math.min(40, Math.max(0.6, this.view.z * factor));
      const k = z / this.view.z;
      this.view.x = px - (px - this.view.x) * k; this.view.y = py - (py - this.view.y) * k; this.view.z = z;
    }
    schedule() { if (!this.frame) this.frame = requestAnimationFrame(() => { this.frame = 0; this.draw(); }); }
    pt(p) {
      const [minx, , , maxy] = this.bounds;
      const s = this.base.scale * this.view.z;
      return [(p[0] - minx) * s + this.base.ox * this.view.z + this.view.x, (maxy - p[1]) * s + this.base.oy * this.view.z + this.view.y];
    }
    draw() {
      if (!this.base || !this.features) return;
      const ctx = this.ctx;
      ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      ctx.clearRect(0, 0, this.w, this.h);
      this.paths = [];
      const hatch = this.hatch || (this.hatch = (() => {
        const c = document.createElement("canvas"); c.width = c.height = 8;
        const g = c.getContext("2d"); g.fillStyle = "#eeeeee"; g.fillRect(0, 0, 8, 8); g.strokeStyle = "#b2b2b2"; g.lineWidth = 1.5;
        g.beginPath(); g.moveTo(0, 8); g.lineTo(8, 0); g.stroke();
        return ctx.createPattern(c, "repeat");
      })());
      for (const f of this.features) {
        const path = new Path2D();
        for (const part of f.parts) {
          part.forEach((p, i) => { const [x, y] = this.pt(p); if (i) path.lineTo(x, y); else path.moveTo(x, y); });
          path.closePath();
        }
        this.paths.push([f.fsa, path]);
        const color = f.has_data ? this.fill(f.fsa) : null;
        ctx.fillStyle = color || hatch;
        ctx.fill(path);
        ctx.lineWidth = 0.6; ctx.strokeStyle = "rgba(60,72,88,0.55)"; ctx.stroke(path);
      }
      for (const [fsa, path] of this.paths) {
        const o = this.outline(fsa);
        if (o) { ctx.lineWidth = o.width || 2.4; ctx.strokeStyle = o.color; ctx.stroke(path); }
      }
      const sel = this.paths.find(([fsa]) => fsa === this.selected);
      if (sel) { ctx.lineWidth = 3; ctx.strokeStyle = "#111827"; ctx.stroke(sel[1]); }
    }
    hit(e) {
      const r = this.canvas.getBoundingClientRect();
      const x = e.clientX - r.left, y = e.clientY - r.top;
      this.ctx.setTransform(1, 0, 0, 1, 0, 0);
      let found = null;
      for (let i = this.paths.length - 1; i >= 0; i--) {
        if (this.ctx.isPointInPath(this.paths[i][1], x * this.dpr, y * this.dpr)) { found = this.paths[i][0]; break; }
      }
      return found;
    }
  }

  // ------------------------------------------------------------------ charts
  function niceTicks(min, max, n = 5) {
    const span = max - min || 1;
    const step = Math.pow(10, Math.floor(Math.log10(span / n)));
    const err = (span / n) / step;
    const f = err >= 7 ? 10 : err >= 3 ? 5 : err >= 1.5 ? 2 : 1;
    const s = f * step;
    const out = [];
    for (let v = Math.ceil(min / s) * s; v <= max + s * 1e-9; v += s) out.push(Number(v.toFixed(10)));
    return out;
  }
  function chart({ w = 520, h = 300, xr, yr, xlabel, ylabel, body, xfmt = (v) => fmt(v, 2), yfmt = (v) => fmt(v, 2) }) {
    const pad = { l: 50, r: 14, t: 10, b: 38 };
    const X = (v) => pad.l + ((v - xr[0]) / (xr[1] - xr[0] || 1)) * (w - pad.l - pad.r);
    const Y = (v) => h - pad.b - ((v - yr[0]) / (yr[1] - yr[0] || 1)) * (h - pad.t - pad.b);
    let g = "";
    niceTicks(yr[0], yr[1]).forEach((t) => { g += `<line class="grid-line" x1="${pad.l}" x2="${w - pad.r}" y1="${Y(t)}" y2="${Y(t)}"/><text x="${pad.l - 6}" y="${Y(t) + 4}" text-anchor="end">${yfmt(t)}</text>`; });
    niceTicks(xr[0], xr[1]).forEach((t) => { g += `<text x="${X(t)}" y="${h - pad.b + 15}" text-anchor="middle">${xfmt(t)}</text>`; });
    g += `<line class="axis-line" x1="${pad.l}" x2="${w - pad.r}" y1="${h - pad.b}" y2="${h - pad.b}"/><line class="axis-line" x1="${pad.l}" x2="${pad.l}" y1="${pad.t}" y2="${h - pad.b}"/>`;
    g += `<text x="${(pad.l + w - pad.r) / 2}" y="${h - 4}" text-anchor="middle">${esc(xlabel)}</text>`;
    g += `<text transform="translate(12 ${(pad.t + h - pad.b) / 2}) rotate(-90)" text-anchor="middle">${esc(ylabel)}</text>`;
    return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(ylabel)} against ${esc(xlabel)}">${g}${body(X, Y)}</svg>`;
  }
  function lineChart(el, series, o) {
    const pts = series.flatMap((s) => s.points);
    const xr = [Math.min(...pts.map((p) => p[0])), Math.max(...pts.map((p) => p[0]))];
    const ymax = Math.max(...pts.map((p) => p[1])) * 1.08 || 1;
    el.innerHTML = chart({
      xr, yr: [0, ymax], xlabel: o.xlabel, ylabel: o.ylabel, xfmt: o.xfmt,
      body: (X, Y) => series.map((s) => `<polyline fill="none" stroke="${s.color}" stroke-width="2" ${s.dash ? 'stroke-dasharray="5 4"' : ""} points="${s.points.map((p) => `${X(p[0])},${Y(p[1])}`).join(" ")}"/>${s.points.map((p) => `<circle cx="${X(p[0])}" cy="${Y(p[1])}" r="3" fill="${s.color}"/>`).join("")}`).join(""),
    }) + `<div class="chart-legend">${series.map((s) => `<span><span class="swatch" style="background:${s.color}"></span>${esc(s.name)}</span>`).join("")}</div>`;
  }
  function pearson(x, y) {
    const n = x.length;
    const mx = x.reduce((a, b) => a + b, 0) / n, my = y.reduce((a, b) => a + b, 0) / n;
    let sxy = 0, sxx = 0, syy = 0;
    for (let i = 0; i < n; i++) { sxy += (x[i] - mx) * (y[i] - my); sxx += (x[i] - mx) ** 2; syy += (y[i] - my) ** 2; }
    const r = sxy / Math.sqrt(sxx * syy);
    const z = Math.atanh(Math.max(-0.999999, Math.min(0.999999, r))), se = 1 / Math.sqrt(n - 3);
    const erfc = (v) => { const a = Math.abs(v), t = 1 / (1 + 0.5 * a); const q = t * Math.exp(-a * a - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277))))))))); return v >= 0 ? q : 2 - q; };
    return { r, lo: Math.tanh(z - 1.96 * se), hi: Math.tanh(z + 1.96 * se), p: erfc(Math.abs(z) / se / Math.SQRT2), n };
  }

  // ------------------------------------------------------------------- setup
  function ensure() {
    if (state.ready) return state.ready;
    state.ready = (async () => {
      const [meta, geometry, scen] = await Promise.all([api("/api/whatif/meta"), api("/api/whatif/geometry"), api("/api/whatif/scenarios")]);
      Object.assign(state, { meta, geometry, scen });
      $("mockBanner").classList.toggle("hidden", !meta.mock);
      state.byScen = {};
      for (const [key, t] of Object.entries(scen.tables)) state.byScen[key] = Object.fromEntries(t.rows.map((r) => [r.fsa, r]));
      const options = meta.scenarios.map((s) => `<option value="${esc(s.key)}">${esc(s.label)}</option>`).join("");
      ["exScenario"].forEach((id) => { $(id).innerHTML = options; });
      const predicted = meta.scenarios.filter((s) => s.source === "predicted").map((s) => `<option value="${esc(s.key)}">${esc(s.label)}</option>`).join("");
      ["wiBase", "poBase", "prBase"].forEach((id) => { $(id).innerHTML = predicted; $(id).value = meta.base_key; });
      $("exScenario").value = meta.base_key;
      views.explore.init(); views.whatif.init(); views.policy.init(); views.priorities.init();
    })();
    state.ready.catch((e) => { state.ready = null; const s = $("status"); if (s) { s.textContent = e.message; s.className = "status error"; } });
    return state.ready;
  }
  const mapOf = (id, onSelect) => { const m = new MapView($(id), { onSelect }); m.setGeometry(state.geometry); return m; };
  const rowsBy = (rows) => Object.fromEntries(rows.map((r) => [r.fsa, r]));

  // ----------------------------------------------------------------- Explore
  const IND = {
    ev_share: { label: "EV fleet share", unit: "%", get: (r) => r.ev_share * 100, d: 1, change: true },
    co2_kg_per_agent: { label: "Tailpipe CO2 per automobile agent", unit: "kg/yr", get: (r) => r.co2_kg_per_agent, d: 0, change: true },
    co2_kt: { label: "Tailpipe CO2", unit: "kt/yr", get: (r) => r.co2_kt, d: 2, change: true },
    electricity_kwh_per_agent: { label: "EV electricity per agent", unit: "kWh/yr", get: (r) => r.electricity_kwh_per_agent, d: 0, change: true },
    electricity_gwh: { label: "EV electricity", unit: "GWh/yr", get: (r) => r.electricity_gwh, d: 2, change: true },
    kappa: { label: "Electrification effectiveness κ (vs 2020)", unit: "g CO2/kWh", get: (r) => r.kappa, d: 0 },
    density_mwh_km2: { label: "Added-demand density (vs 2020)", unit: "MWh/km²/yr", get: (r) => r.density_mwh_km2, d: 1 },
    load: { label: "Added charging load (vs 2020)", unit: "MW", get: (r, w) => r[`load_mw_${w}h`], d: 2 },
    co2_reduction_kt: { label: "CO2 reduction vs 2020", unit: "kt/yr", get: (r) => r.co2_reduction_kt, d: 2 },
  };
  const V = {};
  const views = { explore: {}, whatif: {}, policy: {}, priorities: {} };

  views.explore.init = () => {
    const meta = state.meta;
    $("exIndicator").innerHTML = Object.entries(IND).map(([k, v]) => `<option value="${k}">${esc(v.label)}</option>`).join("");
    $("exIndicator").value = "ev_share";
    $("exWindow").innerHTML = meta.windows.map((w) => `<option value="${w}">${w} h</option>`).join("");
    V.exMap = mapOf("exMap", (fsa) => { V.exSel = fsa; views.explore.card(); views.explore.scatter(); });
    ["exScenario", "exIndicator", "exWindow", "exChange"].forEach((id) => $(id).addEventListener("change", () => views.explore.render()));
    $("exCsv").addEventListener("click", views.explore.csv);
    const notes = [];
    notes.push(`${fmt(meta.total_agents, 0)} automobile agents in ${meta.fsas.length} FSAs (MATSim 10% sample times ten). Per-agent values use this denominator, not residents.`);
    if (meta.calibrated) {
      const worst = Math.max(...Object.values(meta.calibration).map((c) => Math.abs(c.engine_kt / c.events_kt - 1)));
      notes.push(`Results are recomputed from an agent table, not read from emission runs. They match the emission events of ${Object.keys(meta.calibration).length} reference runs within ${fmt(worst * 100, 1)}% on total CO2.`);
    }
    Object.entries(meta.fallback_fsas || {}).forEach(([k, v]) => notes.push(`${k}: FSAs without a composition row use another FSA's shares: ${v.join(", ")}.`));
    meta.notes.forEach((n) => notes.push(n));
    notes.push("Density uses shapefile land area, about 5% below the paper's geometry area.");
    $("exNotes").innerHTML = notes.map((n) => `<p class="help" style="margin:0 0 8px">${esc(n)}</p>`).join("");
    views.explore.table();
    views.explore.render();
  };
  views.explore.valueMap = (key, ind, change, w) => {
    const spec = IND[ind], rows = state.byScen[key], ref = state.byScen[state.scen.ref_key];
    const out = {};
    for (const [fsa, r] of Object.entries(rows)) {
      let v = spec.get(r, w);
      if (change && spec.change && num(v)) { const rv = spec.get(ref[fsa], w); v = num(rv) ? v - rv : null; }
      out[fsa] = num(v) ? v : null;
    }
    return out;
  };
  views.explore.render = () => {
    const key = $("exScenario").value, ind = $("exIndicator").value, spec = IND[ind], w = $("exWindow").value;
    const refKey = state.scen.ref_key;
    $("exWindowGroup").classList.toggle("hidden", ind !== "load");
    const canChange = !!spec.change;
    $("exChange").disabled = !canChange;
    const change = canChange && $("exChange").checked && key !== refKey;
    const all = Object.keys(state.byScen).filter((k) => !(change && k === refKey)).flatMap((k) => Object.values(views.explore.valueMap(k, ind, change, w)).filter(num));
    const scale = makeScale(Math.min(0, ...all), Math.max(...all, 1e-9), change);
    const values = views.explore.valueMap(key, ind, change, w);
    V.exVals = values;
    V.exMap.fill = (fsa) => (num(values[fsa]) ? scale.color(values[fsa]) : null);
    V.exMap.tipHtml = (fsa) => `<strong>${esc(fsa)}</strong><br>${esc(spec.label)}${change ? " (change)" : ""}: ${num(values[fsa]) ? fmt(values[fsa], spec.d) + " " + spec.unit : "n/a"}`;
    V.exMap.schedule();
    const label = state.meta.scenarios.find((s) => s.key === key).label;
    $("exMapTitle").textContent = `${spec.label}${change ? ", change vs 2020" : ""}: ${label}`;
    drawLegend($("exLegend"), scale, spec.unit);
    views.explore.table(key);
    views.explore.scatter();
    views.explore.conc();
    views.explore.card();
  };
  views.explore.table = (selected) => {
    const rows = [
      ["Tailpipe CO2 (kt/yr)", (c) => fmt(c.co2_kt, 1)],
      ["CO2 per agent (kg/yr)", (c) => fmt(c.co2_kg_per_agent, 0)],
      ["CO2 reduction vs 2020 (%)", (c) => (num(c.co2_reduction_pct) ? fmt(c.co2_reduction_pct, 1) : "–")],
      ["EV electricity (GWh/yr)", (c) => fmt(c.electricity_gwh, 1)],
      ["EV electricity per agent (kWh/yr)", (c) => fmt(c.electricity_kwh_per_agent, 0)],
      ["EV share of fleet (%)", (c) => fmt(c.ev_share * 100, 1)],
      ["Added electricity vs 2020 (GWh/yr)", (c) => (num(c.added_electricity_gwh) ? fmt(c.added_electricity_gwh, 1) : "–")],
      ["Effectiveness κ (g CO2/kWh)", (c) => (num(c.kappa_g_per_kwh) ? fmt(c.kappa_g_per_kwh, 0) : "–")],
      ["Added load, 4 h window (MW)", (c) => (c.load_mw ? fmt(c.load_mw["4"], 1) : "–")],
    ];
    const keys = Object.keys(state.scen.tables);
    $("exTable").innerHTML = `<table><thead><tr><th></th>${keys.map((k) => `<th class="num${k === selected ? " selected" : ""}">${esc(state.scen.tables[k].label)}</th>`).join("")}</tr></thead><tbody>${rows.map(([name, f]) => `<tr><th scope="row">${name}</th>${keys.map((k) => `<td class="num${k === selected ? " selected" : ""}" style="${k === selected ? "background:#eef4ff" : ""}">${f(state.scen.tables[k].citywide)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  };
  views.explore.scatter = () => {
    const key = $("exScenario").value, refKey = state.scen.ref_key;
    const rows = state.scen.tables[key].rows;
    const pts = rows.filter((r) => key !== refKey && num(r.ref_co2_kg_per_agent)).map((r) => ({ fsa: r.fsa, x: r.ref_co2_kg_per_agent, y: r.ev_share * 100 }));
    if (!pts.length) { $("exScatter").innerHTML = '<p class="help">Pick a 2035 scenario to compare against the 2020 reference.</p>'; $("exScatterNote").textContent = ""; return; }
    const xr = [Math.min(...pts.map((p) => p.x)) * 0.95, Math.max(...pts.map((p) => p.x)) * 1.03];
    const yr = [0, Math.max(...pts.map((p) => p.y)) * 1.08];
    $("exScatter").innerHTML = chart({
      xr, yr, xlabel: "2020 CO2 per agent (kg/yr)", ylabel: "EV fleet share, scenario (%)", xfmt: (v) => fmt(v, 0), yfmt: (v) => fmt(v, 0),
      body: (X, Y) => pts.map((p) => `<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="${p.fsa === V.exSel ? 6 : 4}" fill="${p.fsa === V.exSel ? "#111827" : "#2563eb"}" fill-opacity="0.75" data-fsa="${esc(p.fsa)}" style="cursor:pointer"><title>${esc(p.fsa)}: ${fmt(p.x, 0)} kg, ${fmt(p.y, 1)}%</title></circle>`).join(""),
    });
    $("exScatter").querySelectorAll("circle").forEach((c) => c.addEventListener("click", () => { V.exSel = c.dataset.fsa; V.exMap.selected = V.exSel; V.exMap.schedule(); views.explore.card(); views.explore.scatter(); }));
    const p = pearson(pts.map((q) => q.x), pts.map((q) => q.y));
    $("exScatterNote").textContent = `Pearson r = ${fmt(p.r, 2)} (95% CI ${fmt(p.lo, 2)} to ${fmt(p.hi, 2)}, p ≈ ${fmt(p.p, 2)}, n = ${p.n}). Near zero means no detectable linear alignment, not independence.`;
  };
  views.explore.conc = () => {
    const key = $("exScenario").value;
    const vals = state.scen.tables[key].rows.map((r) => r.co2_kt).sort((a, b) => b - a);
    const total = vals.reduce((a, b) => a + b, 0);
    let cum = 0;
    const pts = [[0, 0], ...vals.map((v, i) => { cum += v; return [(i + 1) / vals.length * 100, cum / total * 100]; })];
    $("exConc").innerHTML = chart({
      xr: [0, 100], yr: [0, 100], xlabel: "Share of FSAs, highest emitters first (%)", ylabel: "Share of CO2 (%)", xfmt: (v) => fmt(v, 0), yfmt: (v) => fmt(v, 0),
      body: (X, Y) => `<line x1="${X(0)}" y1="${Y(0)}" x2="${X(100)}" y2="${Y(100)}" stroke="#9aa6b2" stroke-dasharray="4 4"/><polyline fill="none" stroke="#b42318" stroke-width="2" points="${pts.map((p) => `${X(p[0])},${Y(p[1])}`).join(" ")}"/>`,
    });
    const top5 = vals.slice(0, 5).reduce((a, b) => a + b, 0) / total * 100;
    const half = pts.findIndex((p) => p[1] >= 50);
    $("exConcNote").textContent = `Top five FSAs hold ${fmt(top5, 1)}% of this scenario's CO2; half arises in ${half} of ${vals.length} FSAs.`;
  };
  views.explore.card = () => {
    const fsa = V.exSel;
    if (!fsa) return;
    $("exCardTitle").textContent = `FSA ${fsa}`;
    const keys = Object.keys(state.scen.tables), cur = $("exScenario").value;
    const body = keys.map((k) => { const r = state.byScen[k][fsa]; return r ? `<tr class="${k === cur ? "selected" : ""}"><th scope="row">${esc(state.scen.tables[k].label)}</th><td class="num">${fmt(r.ev_share * 100, 1)}</td><td class="num">${fmt(r.co2_kg_per_agent, 0)}</td><td class="num">${fmt(r.electricity_kwh_per_agent, 0)}</td><td class="num">${num(r.kappa) ? fmt(r.kappa, 0) : "–"}</td><td class="num">${num(r.density_mwh_km2) ? fmt(r.density_mwh_km2, 1) : "–"}</td></tr>` : ""; }).join("");
    const r = state.byScen[cur][fsa];
    const mix = state.meta.categories.map((c) => `<div title="${esc(c)} ${fmt(r[`n_${c}`] / r.agents * 100, 1)}%" style="width:${r[`n_${c}`] / r.agents * 100}%;background:${FLEET_COLORS[c]}"></div>`).join("");
    $("exCard").innerHTML = `<p class="help" style="margin-top:0">${fmt(r.agents, 0)} agents, ${fmt(r.area_km2, 1)} km² land area.</p><div class="table-wrap"><table><thead><tr><th></th><th class="num">EV share %</th><th class="num">CO2 kg/agent</th><th class="num">kWh/agent</th><th class="num">κ</th><th class="num">MWh/km²</th></tr></thead><tbody>${body}</tbody></table></div><h3 style="margin-top:14px">Fleet mix, selected scenario</h3><div class="mix-bar">${mix}</div><div class="chart-legend">${state.meta.categories.map((c) => `<span><span class="swatch" style="background:${FLEET_COLORS[c]}"></span>${esc(c)}</span>`).join("")}</div>`;
  };
  views.explore.csv = () => {
    const key = $("exScenario").value, rows = state.scen.tables[key].rows;
    const cols = Object.keys(rows[0]).filter((c) => !c.startsWith("n_ice") && !c.startsWith("n_hev"));
    const text = [cols.join(","), ...rows.map((r) => cols.map((c) => (num(r[c]) ? r[c] : r[c] ?? "")).join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
    a.download = `fsa_${key}.csv`; a.click(); URL.revokeObjectURL(a.href);
  };

  // ----------------------------------------------------------------- What-if
  const WI = { overrides: {}, seq: 0, timer: null, data: null };
  views.whatif.init = () => {
    $("wiIndicator").innerHTML = [["co2_kg_per_agent", "CO2 per agent (kg/yr)"], ["ev_share", "EV fleet share (%)"], ["co2_delta", "Change in CO2 vs starting pathway (kt/yr)"], ["ev_delta", "Change in EV share vs starting pathway (points)"], ["electricity_kwh_per_agent", "EV electricity per agent (kWh/yr)"]].map(([k, l]) => `<option value="${k}">${l}</option>`).join("");
    V.wiMap = mapOf("wiMap", (fsa) => {
      $("wiSelected").innerHTML = fsa ? `<strong>${esc(fsa)}</strong>: EV share ${fmt((WI.rows?.[fsa]?.ev_share ?? 0) * 100, 1)}%` : "Click an FSA on the map.";
    });
    const go = () => { clearTimeout(WI.timer); WI.timer = setTimeout(views.whatif.run, 60); };
    ["wiBase", "wiReplace", "wiBoostK", "wiBoostPts", "wiSeed", "wiIndicator"].forEach((id) => $(id).addEventListener("change", go));
    $("wiFactor").addEventListener("input", () => { $("wiFactorValue").textContent = Number($("wiFactor").value).toFixed(2); go(); });
    $("wiOverrideSet").addEventListener("click", () => { const f = V.wiMap.selected; if (!f) return; WI.overrides[f] = Number($("wiOverrideValue").value) / 100; views.whatif.chips(); go(); });
    $("wiReset").addEventListener("click", () => { $("wiFactor").value = 1; $("wiFactorValue").textContent = "1.00"; $("wiBoostK").value = 0; $("wiReplace").value = "proportional"; WI.overrides = {}; views.whatif.chips(); go(); });
    views.whatif.run();
  };
  views.whatif.chips = () => {
    $("wiOverrides").innerHTML = Object.entries(WI.overrides).map(([f, v]) => `<span class="chip remove" data-fsa="${esc(f)}" role="button" tabindex="0" title="Remove override">${esc(f)} ${fmt(v * 100, 0)}% ✕</span>`).join("") || '<span class="help">No overrides.</span>';
    $("wiOverrides").querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => { delete WI.overrides[c.dataset.fsa]; views.whatif.chips(); views.whatif.run(); }));
  };
  views.whatif.run = async () => {
    const id = ++WI.seq;
    try {
      const d = await api("/api/whatif/run", {
        base: $("wiBase").value, ev_factor: Number($("wiFactor").value), replace: $("wiReplace").value,
        boost_k: Number($("wiBoostK").value), boost_points: Number($("wiBoostPts").value) / 100, overrides: WI.overrides, seed: Number($("wiSeed").value),
      });
      if (id !== WI.seq) return;
      WI.data = d; WI.rows = rowsBy(d.rows); WI.base = rowsBy(d.base_rows);
      views.whatif.render();
    } catch (e) { $("wiCards").innerHTML = `<div class="status error">${esc(e.message)}</div>`; }
  };
  const delta = (v, base, d, goodWhenNegative) => {
    if (!num(v) || !num(base)) return "";
    const diff = v - base;
    const cls = Math.abs(diff) < 1e-9 ? "" : (diff < 0) === goodWhenNegative ? "good" : "bad";
    return `<small class="${cls}">${sign(diff, d)} vs start</small>`;
  };
  views.whatif.render = () => {
    const d = WI.data, c = d.citywide, b = d.base_citywide;
    $("wiCards").innerHTML = `
      <div class="card"><span>EV fleet share</span><strong>${fmt(c.ev_share * 100, 1)}%</strong>${delta(c.ev_share * 100, b.ev_share * 100, 1, false)}</div>
      <div class="card"><span>Tailpipe CO2 (kt/yr)</span><strong>${fmt(c.co2_kt, 1)}</strong>${delta(c.co2_kt, b.co2_kt, 1, true)}</div>
      <div class="card"><span>Reduction vs 2020</span><strong>${fmt(c.co2_reduction_pct, 1)}%</strong>${delta(c.co2_reduction_pct, b.co2_reduction_pct, 1, false)}</div>
      <div class="card"><span>EV electricity (GWh/yr)</span><strong>${fmt(c.electricity_gwh, 1)}</strong>${delta(c.electricity_gwh, b.electricity_gwh, 1, true)}</div>
      <div class="card"><span>Effectiveness κ (g/kWh)</span><strong>${num(c.kappa_g_per_kwh) ? fmt(c.kappa_g_per_kwh, 0) : "n/a"}</strong>${delta(c.kappa_g_per_kwh, b.kappa_g_per_kwh, 0, false)}</div>
      <div class="card"><span>Added load, 4 h (MW)</span><strong>${fmt(c.load_mw["4"], 1)}</strong>${delta(c.load_mw["4"], b.load_mw["4"], 1, true)}</div>`;
    const ind = $("wiIndicator").value;
    const spec = {
      co2_kg_per_agent: { get: (r) => r.co2_kg_per_agent, unit: "kg/yr", d: 0 },
      ev_share: { get: (r) => r.ev_share * 100, unit: "%", d: 1 },
      electricity_kwh_per_agent: { get: (r) => r.electricity_kwh_per_agent, unit: "kWh/yr", d: 0 },
      co2_delta: { get: (r, f) => r.co2_kt - WI.base[f].co2_kt, unit: "kt/yr", d: 2, div: true },
      ev_delta: { get: (r, f) => (r.ev_share - WI.base[f].ev_share) * 100, unit: "points", d: 1, div: true },
    }[ind];
    const vals = Object.fromEntries(Object.entries(WI.rows).map(([f, r]) => [f, spec.get(r, f)]));
    // Fixed scale per indicator, from the starting pathway and the 0-2x factor extremes, so sliders do not rescale the map.
    const lim = (V.wiLim = V.wiLim || {});
    const arr = Object.values(vals);
    lim[ind] = lim[ind] || { min: 0, max: 0 };
    lim[ind].min = Math.min(lim[ind].min, ...arr); lim[ind].max = Math.max(lim[ind].max, ...arr);
    const scale = makeScale(lim[ind].min, lim[ind].max, !!spec.div, ind === "ev_share" ? SEQ_BLUE : SEQ);
    V.wiMap.fill = (f) => (num(vals[f]) ? scale.color(vals[f]) : null);
    V.wiMap.outline = (f) => (WI.overrides[f] !== undefined ? { color: "#2563eb", width: 3 } : null);
    V.wiMap.tipHtml = (f) => `<strong>${esc(f)}</strong><br>EV share ${fmt(WI.rows[f].ev_share * 100, 1)}% (start ${fmt(WI.base[f].ev_share * 100, 1)}%)<br>CO2 ${fmt(WI.rows[f].co2_kg_per_agent, 0)} kg/agent<br>${WI.overrides[f] !== undefined ? "Override set" : ""}`;
    V.wiMap.schedule();
    drawLegend($("wiLegend"), scale, spec.unit);
    const top = Object.entries(vals).filter(([, v]) => num(v)).sort((a, b) => (spec.div ? a[1] - b[1] : b[1] - a[1])).slice(0, 5);
    $("wiTopTitle").textContent = spec.div ? "Largest reductions" : "Top 5 FSAs";
    $("wiTop").innerHTML = `<table><thead><tr><th>Rank</th><th>FSA</th><th class="num">${esc(spec.unit)}</th><th class="num">EV share %</th><th class="num">CO2 kg/agent</th></tr></thead><tbody>${top.map(([f, v], i) => `<tr><td>${i + 1}</td><td>${esc(f)}</td><td class="num">${fmt(v, spec.d)}</td><td class="num">${fmt(WI.rows[f].ev_share * 100, 1)}</td><td class="num">${fmt(WI.rows[f].co2_kg_per_agent, 0)}</td></tr>`).join("")}</tbody></table>`;
    views.whatif.chips();
  };

  // ------------------------------------------------------------------ Policy
  const PO = { seq: 0, timer: null };
  const RULE_LABEL = { proportional: "Proportional to fleet", equal: "Equal per FSA", top_resid: "Top-k by CO2 per agent", top_kappa: "Top-k by effectiveness" };
  const RULE_COLOR = { proportional: "#64748b", equal: "#94a3b8", top_resid: "#b42318", top_kappa: "#0f8a5f" };
  views.policy.init = () => {
    V.poMap = mapOf("poMap");
    const go = () => { $("poNValue").textContent = fmt(Number($("poN").value), 0); $("poKValue").textContent = $("poK").value; clearTimeout(PO.timer); PO.timer = setTimeout(views.policy.run, 120); };
    ["poN", "poK"].forEach((id) => $(id).addEventListener("input", go));
    ["poBase", "poRule", "poReplaces", "poWithin"].forEach((id) => $(id).addEventListener("change", go));
    views.policy.run();
  };
  views.policy.run = async () => {
    const id = ++PO.seq;
    try {
      const d = await api("/api/whatif/policy", { base: $("poBase").value, n_extra: Number($("poN").value), rule: $("poRule").value, k: Number($("poK").value), replaces: $("poReplaces").value, within: $("poWithin").value });
      if (id !== PO.seq) return;
      views.policy.render(d);
    } catch (e) { $("poCards").innerHTML = `<div class="status error">${esc(e.message)}</div>`; }
  };
  views.policy.render = (d) => {
    const r = d.result, rule = $("poRule").value;
    const gain = d.gain_vs_proportional;
    $("poCards").innerHTML = `
      <div class="card"><span>CO2 avoided (kt/yr)</span><strong>${fmt(r.avoided_kt, 2)}</strong><small>${fmt(r.n_evs, 0)} extra EVs${r.n_evs < Number($("poN").value) ? " (all eligible vehicles)" : ""}</small></div>
      <div class="card"><span>Per 1,000 EVs (kt/yr)</span><strong>${fmt(r.avoided_kt_per_1000_evs, 3)}</strong><small>uniform effort: ${fmt(d.proportional.avoided_kt_per_1000_evs, 3)}</small></div>
      <div class="card"><span>Gain vs uniform effort</span><strong>${rule === "proportional" ? "baseline" : num(gain) ? sign(gain * 100, 0) + "%" : "n/a"}</strong><small>same number of EVs</small></div>
      <div class="card"><span>Added electricity (GWh/yr)</span><strong>${fmt(r.added_gwh, 2)}</strong><small>${num(r.kappa_g_per_kwh) ? fmt(r.kappa_g_per_kwh, 0) + " g CO2 avoided per kWh" : ""}</small></div>`;
    const names = ["proportional", "equal", "top_resid", "top_kappa"];
    lineChart($("poCurveN"), names.map((n) => ({ name: RULE_LABEL[n], color: RULE_COLOR[n], dash: n === "equal", points: d.curve_n.map((p) => [p.n_evs, p[n]]) })), { xlabel: "Extra EVs", ylabel: "kt CO2 avoided per 1,000 EVs", xfmt: (v) => fmt(v, 0) });
    const unif = d.proportional.avoided_kt_per_1000_evs;
    lineChart($("poCurveK"), [
      { name: RULE_LABEL.top_resid, color: RULE_COLOR.top_resid, points: d.curve_k.map((p) => [p.k, p.top_resid]) },
      { name: RULE_LABEL.top_kappa, color: RULE_COLOR.top_kappa, points: d.curve_k.map((p) => [p.k, p.top_kappa]) },
      { name: "Uniform effort", color: RULE_COLOR.proportional, dash: true, points: d.curve_k.map((p) => [p.k, unif]) },
    ], { xlabel: "Targeted FSAs (k)", ylabel: "kt CO2 avoided per 1,000 EVs", xfmt: (v) => fmt(v, 0) });
    const evs = Object.fromEntries(d.per_fsa.map((p) => [p.fsa, p]));
    const max = Math.max(...d.per_fsa.map((p) => p.evs), 1);
    const scale = makeScale(0, max, false, SEQ_BLUE);
    V.poMap.fill = (f) => scale.color(evs[f] ? evs[f].evs : 0);
    V.poMap.tipHtml = (f) => `<strong>${esc(f)}</strong><br>${fmt(evs[f]?.evs ?? 0, 0)} extra EVs<br>${fmt(evs[f]?.avoided_kt ?? 0, 3)} kt CO2 avoided`;
    V.poMap.schedule();
    drawLegend($("poLegend"), scale, "extra EVs");
    const b = d.within_bounds, bm = Math.max(b.random, b.high_km, b.low_km) * 1.1 || 1;
    const rows = [["Lowest distance first", b.low_km, "#94a3b8"], ["Random", b.random, "#2563eb"], ["Highest distance first", b.high_km, "#0f8a5f"]];
    $("poBounds").innerHTML = rows.map(([l, v, c]) => `<div style="display:grid;grid-template-columns:150px 1fr 70px;gap:10px;align-items:center;margin:8px 0;font-size:13px"><span>${l}</span><div style="background:#edf2f7;border-radius:4px"><div style="width:${v / bm * 100}%;height:16px;background:${c};border-radius:4px"></div></div><span style="text-align:right">${fmt(v, 3)}</span></div>`).join("");
  };

  // -------------------------------------------------------------- Priorities
  const PR = { data: null };
  views.priorities.init = () => {
    V.prMap = mapOf("prMap", (fsa) => { V.prSel = fsa; views.priorities.table(); });
    $("prRun").addEventListener("click", views.priorities.run);
    $("prIndicator").addEventListener("change", () => PR.data && views.priorities.render());
    views.priorities.run();
  };
  views.priorities.run = async () => {
    $("prRun").disabled = true; $("prRun").textContent = "Running…";
    try {
      PR.data = await api("/api/whatif/stability", { base: $("prBase").value, k: Number($("prK").value), runs: Number($("prRuns").value) });
      views.priorities.render();
    } catch (e) { $("prCards").innerHTML = `<div class="status error">${esc(e.message)}</div>`; }
    $("prRun").disabled = false; $("prRun").textContent = "Run";
  };
  views.priorities.render = () => {
    const d = PR.data, ind = $("prIndicator").value, key = `p_top_${ind}`;
    const robust = (n) => (d.robust[n].length ? d.robust[n].map((f) => `<span class="chip">${esc(f)}</span>`).join("") : "none");
    $("prCards").innerHTML = `
      <div class="card"><span>Robust, residual CO2</span><strong style="font-size:15px;font-weight:600">${robust("residual")}</strong></div>
      <div class="card"><span>Robust, effectiveness κ</span><strong style="font-size:15px;font-weight:600">${robust("kappa")}</strong></div>
      <div class="card"><span>Robust, demand density</span><strong style="font-size:15px;font-weight:600">${robust("density")}</strong></div>
      <div class="card"><span>Draws with no FSA in two lists</span><strong>${fmt(d.disjoint_top_lists_fraction * 100, 0)}%</strong><small>${d.runs} draws, top-${d.k}</small></div>`;
    const by = rowsBy(d.fsas);
    const scale = makeScale(0, 1, false, SEQ_BLUE);
    V.prMap.fill = (f) => (by[f] ? scale.color(by[f][key]) : null);
    V.prMap.outline = (f) => (by[f] && by[f][key] >= 0.8 ? { color: "#b42318", width: 2.6 } : null);
    V.prMap.tipHtml = (f) => (by[f] ? `<strong>${esc(f)}</strong><br>In top-${d.k}: ${fmt(by[f][key] * 100, 0)}% of draws` : esc(f));
    V.prMap.schedule();
    drawLegend($("prLegend"), scale, "probability (red outline: ≥ 80%)");
    $("prMapTitle").textContent = `Probability of being in the top-${d.k}: ${$("prIndicator").selectedOptions[0].textContent}`;
    views.priorities.table();
  };
  views.priorities.table = () => {
    const d = PR.data; if (!d) return;
    const ind = $("prIndicator").value, key = `p_top_${ind}`;
    const rows = [...d.fsas].sort((a, b) => b[key] - a[key] || b[`${ind}_mean`] - a[`${ind}_mean`]).slice(0, 15);
    const unit = { residual: "kg/agent", kappa: "g/kWh", density: "MWh/km²" }[ind];
    $("prTable").innerHTML = `<table><thead><tr><th>FSA</th><th class="num">In top-${d.k}</th><th class="num">Mean (${unit})</th><th class="num">5th–95th pct</th><th>Candidate levers (heuristic)</th></tr></thead><tbody>${rows.map((r) => `<tr class="${r.fsa === V.prSel ? "selected" : ""}"><th scope="row">${esc(r.fsa)}</th><td class="num">${fmt(r[key] * 100, 0)}%</td><td class="num">${fmt(r[`${ind}_mean`], ind === "kappa" ? 0 : 1)}</td><td class="num">${fmt(r[`${ind}_p5`], 0)} to ${fmt(r[`${ind}_p95`], 0)}</td><td style="white-space:normal">${r.levers.map((l) => `<span class="chip">${esc(l)}</span>`).join("") || '<span class="help">none</span>'}</td></tr>`).join("")}</tbody></table>`;
  };

  // -------------------------------------------------------------------- tabs
  const names = ["pipeline", "explore", "whatif", "policy", "priorities"];
  function show(name) {
    names.forEach((n) => { $(`tab-${n}`).classList.toggle("hidden", n !== name); document.querySelector(`[data-tab="${n}"]`).classList.toggle("active", n === name); });
    try { history.replaceState(null, "", `#${name}`); } catch (e) { /* ignore */ }
    if (name === "pipeline") return;
    ensure().then(() => { Object.values(V).forEach((m) => m && m.resize && m.resize()); });
  }
  document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => show(b.dataset.tab)));
  fetch("/api/config").then((r) => r.json()).then((d) => $("mockBanner").classList.toggle("hidden", !d.config.mock_data)).catch(() => {});
  const start = location.hash.slice(1);
  if (names.includes(start) && start !== "pipeline") show(start);
})();
