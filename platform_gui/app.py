from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import core


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MATSim Vehicle Assignment Platform</title>
  <style>
    :root {
      --bg: #f5f7fa;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #607080;
      --line: #d9e1ea;
      --blue: #2563eb;
      --green: #0f8a5f;
      --red: #b42318;
      --shadow: 0 10px 28px rgba(18, 33, 54, 0.09);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      padding: 18px 28px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1 { margin: 0; font-size: 22px; font-weight: 720; }
    main {
      min-height: calc(100vh - 65px);
      padding: 22px 28px;
    }
    .workspace {
      display: grid;
      grid-template-columns: minmax(320px, 390px) minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }
    .left-rail {
      position: sticky;
      top: 88px;
    }
    .right-stage {
      min-width: 0;
    }
    .config-toggle {
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .config-toggle::after {
      content: "Open";
      font-size: 12px;
      color: #4b5f73;
    }
    .results-stack { display: grid; gap: 18px; }
    .below-map-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; align-items: start; }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 24px;
      background: rgba(16, 29, 44, 0.42);
      z-index: 10;
    }
    .modal-backdrop.open {
      display: flex;
    }
    .modal {
      width: min(920px, 100%);
      max-height: min(760px, calc(100vh - 48px));
      display: flex;
      flex-direction: column;
      background: #ffffff;
      border: 1px solid rgba(217, 225, 234, 0.9);
      border-radius: 8px;
      box-shadow: 0 22px 65px rgba(18, 33, 54, 0.28);
      overflow: hidden;
    }
    .modal-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px 18px;
      border-bottom: 1px solid var(--line);
    }
    .modal-header h2 { margin: 0; }
    .modal-body {
      overflow: auto;
      padding: 16px 18px;
    }
    .modal-footer {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      padding: 14px 18px;
      border-top: 1px solid var(--line);
      background: #f8fafc;
    }
    h2 { margin: 0 0 12px; font-size: 17px; }
    h3 { margin: 0 0 10px; font-size: 14px; color: #26384a; }
    label { display: block; margin: 10px 0 5px; color: #34475a; font-size: 12px; font-weight: 680; }
    input, select {
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      background: #fff;
      color: var(--text);
      font-size: 13px;
    }
    input[type="range"] { min-height: 30px; padding: 0; }
    input:focus, select:focus { outline: 2px solid rgba(37, 99, 235, 0.2); border-color: var(--blue); }
    button {
      min-height: 38px;
      border: 0;
      border-radius: 6px;
      padding: 8px 13px;
      background: var(--blue);
      color: #fff;
      font-weight: 720;
      cursor: pointer;
    }
    button.secondary { background: #edf2f7; color: #243447; }
    button.success { background: var(--green); }
    button:disabled { opacity: 0.55; cursor: progress; }
    .metric-toggle { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .metric-toggle button { background: #edf2f7; color: #243447; }
    .metric-toggle button.active { background: var(--blue); color: #fff; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      box-shadow: var(--shadow);
      margin-bottom: 18px;
    }
    .panel:last-child { margin-bottom: 0; }
    .status {
      min-height: 40px;
      margin: 0 0 16px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--muted);
      font-size: 13px;
    }
    .status.error { color: var(--red); border-color: #f1b4ae; background: #fff6f5; }
    .status.ok { color: var(--green); border-color: #a8dec9; background: #f3fbf7; }
    .muted { color: var(--muted); font-size: 13px; }
    .summary {
      display: grid;
      grid-template-columns: repeat(4, minmax(130px, 1fr));
      gap: 12px;
    }
    .stat {
      background: #ffffff;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 13px;
    }
    .stat span { display: block; color: var(--muted); font-size: 12px; }
    .stat strong { display: block; margin-top: 4px; font-size: 18px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 9px 8px; border-bottom: 1px solid var(--line); text-align: left; }
    th { color: #3f5062; font-size: 12px; }
    img {
      width: 100%;
      max-height: 680px;
      object-fit: contain;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .slider-row { display: flex; align-items: center; gap: 10px; }
    .slider-row input { flex: 1; }
    .slider-value { min-width: 44px; text-align: right; font-weight: 720; color: #23364a; }
    .share-stack { margin-top: 14px; }
    .share-bar {
      height: 24px;
      display: flex;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #f2f5f8;
    }
    .share-slice { min-width: 1px; }
    .share-table { margin-top: 8px; }
    .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: middle; }
    .map-toolbar { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
    .map-toolbar > div:last-child { display: grid; gap: 8px; justify-items: end; }
    .map-buttons { display: flex; gap: 8px; }
    .map-buttons button { min-width: 38px; padding: 8px 10px; }
    .map-shell {
      height: min(72vh, 760px);
      min-height: 520px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
      overflow: hidden;
      cursor: grab;
    }
    .map-shell.dragging { cursor: grabbing; }
    #mapCanvas { width: 100%; height: 100%; display: block; }
    .detail-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }
    .detail-item { border: 1px solid var(--line); border-radius: 6px; padding: 9px; background: #f8fafc; }
    .detail-item span { display: block; color: var(--muted); font-size: 11px; }
    .detail-item strong { display: block; margin-top: 2px; font-size: 14px; overflow-wrap: anywhere; }
    .hidden { display: none; }
    code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
    @media (max-width: 980px) {
      main { padding: 16px; }
      .workspace, .below-map-grid { grid-template-columns: 1fr; }
      .left-rail { position: static; }
      .summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .detail-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
  </style>
</head>
<body>
  <header>
    <h1>MATSim Vehicle Assignment Platform</h1>
    <div class="muted">Configure, assign vehicle types, and generate FSA research outputs</div>
  </header>
  <main>
    <div class="workspace">
      <div class="left-rail">
        <div class="panel">
          <button class="secondary config-toggle" id="configToggle" type="button">Configuration</button>
        </div>

        <div class="panel">
          <h2>Vehicle Assignment</h2>
          <div class="grid">
            <div>
              <label for="source">Composition Source</label>
              <select id="source">
                <option value="predicted">Predicted</option>
                <option value="historical">Historical</option>
              </select>
            </div>
            <div>
              <label for="year">Year</label>
              <select id="year"></select>
            </div>
          </div>
          <label for="scenario">Scenario</label>
          <select id="scenario"></select>
          <label for="seed">Assignment Seed</label>
          <input id="seed" type="number" value="2">
          <div id="evFactorGroup">
            <label for="evFactor">Custom Target Factor</label>
            <div class="slider-row">
              <input id="evFactor" type="range" min="0.5" max="1.5" step="0.05" value="1">
              <span id="evFactorValue" class="slider-value">1.00</span>
            </div>
          </div>
          <div class="share-stack">
            <h3>Projected Quebec City Vehicle Share</h3>
            <div id="shareBox" class="muted">Select settings to preview projected share.</div>
          </div>
          <div class="actions">
            <button id="assignBtn">Assign Vehicle Types</button>
          </div>
        </div>

        <div class="panel">
          <h2>Emission Module</h2>
          <label for="assignedVehicleSelect">Vehicle Assignment XML</label>
          <select id="assignedVehicleSelect"></select>
          <div class="actions">
            <button id="emissionBtn">Run Emission Module</button>
          </div>
        </div>

        <div class="panel">
          <h2>Generate Results</h2>
          <div class="actions">
            <button class="success" id="resultsBtn">Generate Results</button>
          </div>
        </div>
      </div>

      <div class="right-stage">
        <div id="status" class="status">Ready.</div>
        <div class="results-stack">
          <div class="panel">
            <div class="map-toolbar">
              <div>
                <h2>Interactive FSA Map</h2>
                <div id="mapCaption" class="muted">Generate CO2 emissions results to display the default emissions map.</div>
              </div>
              <div>
                <div class="metric-toggle">
                  <button id="metricCo2" class="active" type="button" data-metric="co2">CO2 Emissions</button>
                  <button id="metricEv" class="secondary" type="button" data-metric="ev">Electricity Demand</button>
                </div>
                <div class="map-buttons">
                  <button class="secondary" id="zoomOutBtn" type="button">−</button>
                  <button class="secondary" id="zoomInBtn" type="button">+</button>
                  <button class="secondary" id="resetMapBtn" type="button">Reset</button>
                </div>
              </div>
            </div>
            <div id="mapShell" class="map-shell">
              <canvas id="mapCanvas"></canvas>
            </div>
            <div id="fsaDetails" class="detail-grid"></div>
          </div>
          <div class="summary" id="summary"></div>
          <div class="below-map-grid">
            <div class="panel">
              <h2>Top 5 FSA</h2>
              <div id="topBox" class="muted">No result loaded yet.</div>
            </div>
            <div class="panel">
              <h2>Output Files</h2>
              <div id="filesBox" class="muted">No output files yet.</div>
            </div>
            <div class="panel">
              <h2>Map Legend</h2>
              <div id="legendBox" class="muted">No result loaded yet.</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </main>
  <div class="modal-backdrop" id="configModal" aria-hidden="true">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="configTitle">
      <div class="modal-header">
        <h2 id="configTitle">Configuration</h2>
        <button class="secondary" id="closeConfig" type="button">Close</button>
      </div>
      <div class="modal-body">
        <div id="configFields"></div>
      </div>
      <div class="modal-footer">
        <button class="secondary" id="reloadConfig" type="button">Reload</button>
        <button id="saveConfig" type="button">Save Config</button>
      </div>
    </div>
  </div>
  <script>
    const configKeys = [
      "population_file", "vehicle_file", "transit_vehicle_file", "matsim_events_file", "emission_events_file",
      "emission_events_dir", "emission_config_dir", "emission_config_template", "emission_module_dir",
      "network_file", "fsa_lookup_file", "fsa_shapefile", "historical_vehicle_share_dir",
      "predicted_vehicle_share_dir", "historical_bev_share_file", "output_dir", "results_dir"
    ];
    let appConfig = {};
    let options = {};
    let lastAssignedVehicle = "";
    let activeMetric = "co2";
    let currentMap = null;
    let selectedFeature = null;
    const resultCache = {};
    const mapView = { zoom: 1, offsetX: 0, offsetY: 0 };
    const canvasState = {
      width: 0,
      height: 0,
      dpr: 1,
      hatch: null,
      transform: null,
      cachedFeatures: [],
      frame: 0
    };
    const shareColors = {
      electric: "#2563eb",
      hev_sedan: "#0f8a5f",
      hev_suv: "#48a868",
      ice_sedan: "#f59e0b",
      ice_suv: "#ef4444",
      "ice_van/pickup": "#7c3aed",
      truck: "#64748b",
      defaultVehicleType: "#94a3b8"
    };

    const $ = (id) => document.getElementById(id);
    const fmt = (value, digits = 3) => value === null || value === undefined || Number.isNaN(Number(value))
      ? "n/a"
      : Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
    const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));

    function setStatus(message, kind = "") {
      const el = $("status");
      el.textContent = message;
      el.className = `status ${kind}`;
    }

    async function api(path, opts = {}) {
      const response = await fetch(path, opts);
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || response.statusText);
      return data;
    }

    function renderConfigFields() {
      const box = $("configFields");
      box.innerHTML = "";
      for (const key of configKeys) {
        const label = document.createElement("label");
        label.textContent = key.replaceAll("_", " ");
        const input = document.createElement("input");
        input.id = `cfg_${key}`;
        input.value = appConfig[key] || "";
        box.append(label, input);
      }
    }

    function collectConfig() {
      for (const key of configKeys) appConfig[key] = $(`cfg_${key}`).value.trim();
      return appConfig;
    }

    function updateConfigValue(key, value) {
      appConfig[key] = value || "";
      const input = $(`cfg_${key}`);
      if (input) input.value = appConfig[key];
    }

    function updateYears() {
      const source = $("source").value;
      const years = source === "predicted" ? options.predicted_years : options.historical_years;
      $("year").innerHTML = years.map(y => `<option value="${y}">${y}</option>`).join("");
      if (years.includes(2035)) $("year").value = "2035";
      updateScenarios();
    }

    function updateScenarios() {
      const source = $("source").value;
      const year = $("year").value;
      const scenarios = source === "predicted"
        ? (options.predicted_scenarios?.[year] || ["BAU"])
        : ["HISTORICAL"];
      $("scenario").innerHTML = scenarios.map(s => `<option value="${s}">${s}</option>`).join("");
      if (scenarios.includes("BAU")) $("scenario").value = "BAU";
      updateEvFactorVisibility();
    }

    function updateEvFactorVisibility() {
      const isCustom = $("source").value === "predicted" && $("scenario").value === "CUSTOM_ADOPTION";
      $("evFactorGroup").classList.toggle("hidden", !isCustom);
    }

    function selectedEvFactor() {
      return $("scenario").value === "CUSTOM_ADOPTION" ? Number($("evFactor").value) : 1.0;
    }

    function vehicleFileValue() {
      return $("assignedVehicleSelect").value || lastAssignedVehicle;
    }

    function renderSummary(items) {
      $("summary").innerHTML = items.map(item => `
        <div class="stat"><span>${item.label}</span><strong>${item.value}</strong></div>
      `).join("");
    }

    function renderShare(shareRows) {
      if (!shareRows || !shareRows.length) {
        $("shareBox").innerHTML = "No projected share available.";
        return;
      }
      const slices = shareRows.map(row => {
        const color = shareColors[row.vehicle_type] || "#94a3b8";
        return `<div class="share-slice" title="${escapeHtml(row.label)} ${fmt(row.share * 100, 2)}%" style="width:${Math.max(row.share * 100, 0.2)}%; background:${color}"></div>`;
      }).join("");
      const rows = shareRows.map(row => {
        const color = shareColors[row.vehicle_type] || "#94a3b8";
        return `<tr><td><span class="swatch" style="background:${color}"></span>${escapeHtml(row.label)}</td><td>${fmt(row.share * 100, 2)}%</td></tr>`;
      }).join("");
      $("shareBox").innerHTML = `
        <div class="share-bar">${slices}</div>
        <table class="share-table"><tbody>${rows}</tbody></table>`;
    }

    async function refreshProjectedShare() {
      try {
        $("evFactorValue").textContent = Number($("evFactor").value).toFixed(2);
        const data = await api("/api/projected-share", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            config: collectConfig(),
            source: $("source").value,
            year: Number($("year").value),
            scenario: $("scenario").value,
            ev_factor: selectedEvFactor()
          })
        });
        renderShare(data.projected_share);
      } catch (err) {
        $("shareBox").innerHTML = escapeHtml(err.message);
      }
    }

    async function loadVehicleFiles(selectedPath = "") {
      const data = await api("/api/vehicle-files");
      const files = data.files || [];
      $("assignedVehicleSelect").innerHTML = files.length
        ? files.map(file => `<option value="${escapeHtml(file.path)}">${escapeHtml(file.name)}</option>`).join("")
        : `<option value="">No generated vehicle XML files</option>`;
      if (selectedPath) {
        const hasSelected = files.some(file => file.path === selectedPath);
        if (!hasSelected) {
          $("assignedVehicleSelect").insertAdjacentHTML("afterbegin", `<option value="${escapeHtml(selectedPath)}">${escapeHtml(selectedPath)}</option>`);
        }
        $("assignedVehicleSelect").value = selectedPath;
      } else if (files[0]) {
        $("assignedVehicleSelect").value = files[0].path;
      }
    }

    function renderResult(data, metric = activeMetric, store = true) {
      if (store) resultCache[metric] = data;
      currentMap = data.map || null;
      selectedFeature = null;
      canvasState.transform = null;
      canvasState.cachedFeatures = [];
      resetMap();
      $("mapCaption").textContent = currentMap
        ? `${data.metric} (${data.unit}); drag to pan, zoom with controls, click an FSA for details.`
        : "No map was generated.";
      $("topBox").innerHTML = `
        <table>
          <thead><tr><th>Rank</th><th>FSA</th><th>${data.unit}</th></tr></thead>
          <tbody>${(data.top_fsa || []).map((row, idx) => `
            <tr><td>${idx + 1}</td><td>${row.fsa}</td><td>${fmt(row.value, 6)}</td></tr>
          `).join("")}</tbody>
        </table>`;
      const fileRows = Object.entries(data)
        .filter(([key, value]) => key.endsWith("csv") || key === "heatmap")
        .map(([key, value]) => `<tr><td>${key}</td><td><code>${escapeHtml(value)}</code></td></tr>`)
        .join("");
      $("filesBox").innerHTML = `<table><tbody>${fileRows}</tbody></table>`;
      renderLegend(data.map);
    }

    function renderLegend(map) {
      if (!map) {
        $("legendBox").innerHTML = "No result loaded yet.";
        return;
      }
      const ticks = map.ticks || [0, map.max_value || 0];
      $("legendBox").innerHTML = `
        <table><tbody>
          ${ticks.map(tick => `<tr><td><span class="swatch" style="background:${colorForValue(tick, map.max_value)}"></span>${fmt(tick, 4)} ${escapeHtml(map.unit)}</td></tr>`).join("")}
          <tr><td><span class="swatch" style="background:${colorForValue(0, map.max_value)}; border:1px solid #9aa6b2"></span>Zero/low value</td></tr>
          <tr><td><span class="swatch" style="background:repeating-linear-gradient(135deg,#eeeeee 0,#eeeeee 4px,#b2b2b2 4px,#b2b2b2 6px)"></span>No data</td></tr>
          <tr><td class="muted">Hatched means no result row; pale means valid zero/low value.</td></tr>
        </tbody></table>`;
    }

    function setActiveMetric(metric) {
      activeMetric = metric;
      document.querySelectorAll("[data-metric]").forEach(item => {
        item.classList.toggle("active", item.dataset.metric === metric);
        item.classList.toggle("secondary", item.dataset.metric !== metric);
      });
    }

    async function generateActiveResult(statusMessage = "Generating research outputs...") {
      $("resultsBtn").disabled = true;
      setStatus(statusMessage);
      try {
        const data = await api("/api/results", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            config: collectConfig(),
            metric: activeMetric,
            year: Number($("year").value),
            scenario: $("scenario").value,
            vehicle_file: vehicleFileValue()
          })
        });
        renderResult(data);
        const summary = [
          { label: "Metric", value: data.metric },
          { label: "Top FSA", value: data.top_fsa?.[0]?.fsa || "n/a" },
          { label: "Year", value: $("year").value },
          { label: "Scenario", value: $("scenario").value }
        ];
        renderSummary(summary);
        setStatus("Research outputs generated.", "ok");
      } catch (err) {
        setStatus(err.message, "error");
      } finally {
        $("resultsBtn").disabled = false;
      }
    }

    function colorForValue(value, maxValue) {
      if (!maxValue || maxValue <= 0 || !value || value <= 0) return "rgb(255,253,240)";
      const stops = [[255,253,240], [255,239,171], [255,213,97], [254,178,76], [240,96,35], [189,0,38]];
      const t = Math.min(1, Math.max(0, value / maxValue)) ** 0.55;
      const scaled = t * (stops.length - 1);
      const idx = Math.min(stops.length - 2, Math.floor(scaled));
      const frac = scaled - idx;
      const a = stops[idx], b = stops[idx + 1];
      const rgb = a.map((component, i) => Math.round(component + (b[i] - component) * frac));
      return `rgb(${rgb.join(",")})`;
    }

    function fitTransform() {
      const canvas = $("mapCanvas");
      const [minx, miny, maxx, maxy] = currentMap.bounds;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      const scale = Math.min(width / (maxx - minx), height / (maxy - miny));
      const baseX = (width - (maxx - minx) * scale) / 2;
      const baseY = (height - (maxy - miny) * scale) / 2;
      return { minx, miny, maxx, maxy, scale, baseX, baseY, width, height };
    }

    function worldToScreen(point, transform) {
      const x = transform.baseX + (point[0] - transform.minx) * transform.scale;
      const y = transform.baseY + (transform.maxy - point[1]) * transform.scale;
      return [x, y];
    }

    function screenToWorld(x, y, transform) {
      const unzoomX = (x - mapView.offsetX) / mapView.zoom;
      const unzoomY = (y - mapView.offsetY) / mapView.zoom;
      return [
        (unzoomX - transform.baseX) / transform.scale + transform.minx,
        transform.maxy - (unzoomY - transform.baseY) / transform.scale
      ];
    }

    function createHatchPattern(ctx) {
      const patternCanvas = document.createElement("canvas");
      patternCanvas.width = 12;
      patternCanvas.height = 12;
      const pctx = patternCanvas.getContext("2d");
      pctx.fillStyle = "#eeeeee";
      pctx.fillRect(0, 0, 12, 12);
      pctx.strokeStyle = "#b2b2b2";
      pctx.lineWidth = 2;
      pctx.beginPath();
      pctx.moveTo(-2, 12);
      pctx.lineTo(12, -2);
      pctx.stroke();
      return ctx.createPattern(patternCanvas, "repeat");
    }

    function ensureCanvasSize() {
      const canvas = $("mapCanvas");
      const shell = $("mapShell");
      const dpr = window.devicePixelRatio || 1;
      const rect = shell.getBoundingClientRect();
      const width = Math.max(1, Math.round(rect.width));
      const height = Math.max(1, Math.round(rect.height));
      const pixelWidth = Math.max(1, Math.round(width * dpr));
      const pixelHeight = Math.max(1, Math.round(height * dpr));
      if (canvas.width !== pixelWidth || canvas.height !== pixelHeight || canvasState.dpr !== dpr) {
        canvas.width = pixelWidth;
        canvas.height = pixelHeight;
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
        canvasState.width = width;
        canvasState.height = height;
        canvasState.dpr = dpr;
        canvasState.hatch = null;
        canvasState.transform = null;
        canvasState.cachedFeatures = [];
      }
    }

    function rebuildMapCache() {
      canvasState.cachedFeatures = [];
      canvasState.transform = null;
      if (!currentMap) return;
      ensureCanvasSize();
      const transform = fitTransform();
      canvasState.transform = transform;
      canvasState.cachedFeatures = currentMap.features.map(feature => ({
        feature,
        screenParts: feature.parts.map(part => part.map(point => worldToScreen(point, transform)))
      }));
    }

    function scheduleDrawMap() {
      if (canvasState.frame) return;
      canvasState.frame = window.requestAnimationFrame(() => {
        canvasState.frame = 0;
        drawMap();
      });
    }

    function drawMap() {
      ensureCanvasSize();
      if (currentMap && (!canvasState.transform || !canvasState.cachedFeatures.length)) {
        rebuildMapCache();
      }
      const canvas = $("mapCanvas");
      const ctx = canvas.getContext("2d");
      ctx.setTransform(canvasState.dpr, 0, 0, canvasState.dpr, 0, 0);
      ctx.clearRect(0, 0, canvasState.width, canvasState.height);
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvasState.width, canvasState.height);

      if (!currentMap) {
        ctx.fillStyle = "#607080";
        ctx.font = "14px system-ui, sans-serif";
        ctx.fillText("Generate results to display the interactive map.", 20, 34);
        renderFeatureDetails(null);
        return;
      }

      if (!canvasState.hatch) {
        canvasState.hatch = createHatchPattern(ctx);
      }

      for (const item of canvasState.cachedFeatures) {
        const feature = item.feature;
        ctx.beginPath();
        for (const part of item.screenParts) {
          part.forEach((point, idx) => {
            const x = point[0] * mapView.zoom + mapView.offsetX;
            const y = point[1] * mapView.zoom + mapView.offsetY;
            if (idx === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
          });
          ctx.closePath();
        }
        ctx.fillStyle = feature.has_data === false
          ? canvasState.hatch
          : colorForValue(feature.value, currentMap.max_value);
        ctx.fill();
        ctx.strokeStyle = selectedFeature?.fsa === feature.fsa ? "#1d4ed8" : "#9aa6b2";
        ctx.lineWidth = selectedFeature?.fsa === feature.fsa ? 2.4 : 0.8;
        ctx.stroke();
      }
      renderFeatureDetails(selectedFeature);
    }

    function resetMap() {
      mapView.zoom = 1;
      mapView.offsetX = 0;
      mapView.offsetY = 0;
      scheduleDrawMap();
    }

    function zoomMap(factor) {
      const canvas = $("mapCanvas");
      const cx = canvas.clientWidth / 2;
      const cy = canvas.clientHeight / 2;
      mapView.offsetX = cx - (cx - mapView.offsetX) * factor;
      mapView.offsetY = cy - (cy - mapView.offsetY) * factor;
      mapView.zoom = Math.min(12, Math.max(0.5, mapView.zoom * factor));
      scheduleDrawMap();
    }

    function pointInPolygon(point, polygon) {
      let inside = false;
      for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
        const xi = polygon[i][0], yi = polygon[i][1];
        const xj = polygon[j][0], yj = polygon[j][1];
        const intersect = ((yi > point[1]) !== (yj > point[1])) &&
          (point[0] < (xj - xi) * (point[1] - yi) / ((yj - yi) || 1e-12) + xi);
        if (intersect) inside = !inside;
      }
      return inside;
    }

    function featureAt(screenX, screenY) {
      if (!currentMap) return null;
      const transform = fitTransform();
      const point = screenToWorld(screenX, screenY, transform);
      for (let i = currentMap.features.length - 1; i >= 0; i--) {
        const feature = currentMap.features[i];
        const [minx, miny, maxx, maxy] = feature.bbox;
        if (point[0] < minx || point[0] > maxx || point[1] < miny || point[1] > maxy) continue;
        if (feature.parts.some(part => pointInPolygon(point, part))) return feature;
      }
      return null;
    }

    function renderFeatureDetails(feature) {
      if (!feature || !currentMap) {
        $("fsaDetails").innerHTML = `<div class="muted">Click an FSA block to inspect code, population, area, value, and per-vehicle average.</div>`;
        return;
      }
      $("fsaDetails").innerHTML = `
        <div class="detail-item"><span>FSA</span><strong>${escapeHtml(feature.fsa)}</strong></div>
        <div class="detail-item"><span>Population${feature.population_year ? ` (${feature.population_year})` : ""}</span><strong>${fmt(feature.population, 0)}</strong></div>
        <div class="detail-item"><span>Land area</span><strong>${fmt(feature.land_area, 3)} km²</strong></div>
        <div class="detail-item"><span>Value</span><strong>${fmt(feature.value, 6)} ${escapeHtml(currentMap.unit)}</strong></div>
        <div class="detail-item"><span>Relevant vehicles</span><strong>${fmt(feature.relevant_vehicle_count, 0)}</strong></div>
        <div class="detail-item"><span>Average per vehicle</span><strong>${fmt(feature.per_vehicle, 9)} ${escapeHtml(feature.per_vehicle_unit || currentMap.per_vehicle_unit || "")}</strong></div>`;
    }

    async function loadAll() {
      const data = await api("/api/config");
      appConfig = data.config;
      options = data.options;
      renderConfigFields();
      updateYears();
      await loadVehicleFiles();
      await refreshProjectedShare();
      drawMap();
    }

    function openConfigModal() {
      $("configModal").classList.add("open");
      $("configModal").setAttribute("aria-hidden", "false");
      $("closeConfig").focus();
    }

    function closeConfigModal() {
      $("configModal").classList.remove("open");
      $("configModal").setAttribute("aria-hidden", "true");
      $("configToggle").focus();
    }

    $("source").addEventListener("change", async () => { updateYears(); await refreshProjectedShare(); });
    $("year").addEventListener("change", async () => { updateScenarios(); await refreshProjectedShare(); });
    $("scenario").addEventListener("change", async () => {
      updateEvFactorVisibility();
      await refreshProjectedShare();
    });
    $("evFactor").addEventListener("input", () => { $("evFactorValue").textContent = Number($("evFactor").value).toFixed(2); });
    $("evFactor").addEventListener("change", refreshProjectedShare);
    $("zoomOutBtn").addEventListener("click", () => zoomMap(1 / 1.25));
    $("zoomInBtn").addEventListener("click", () => zoomMap(1.25));
    $("resetMapBtn").addEventListener("click", resetMap);
    window.addEventListener("resize", () => {
      canvasState.transform = null;
      canvasState.cachedFeatures = [];
      scheduleDrawMap();
    });
    let dragging = false;
    let moved = false;
    let lastPoint = null;
    $("mapShell").addEventListener("mousedown", (event) => {
      dragging = true;
      moved = false;
      lastPoint = [event.clientX, event.clientY];
      $("mapShell").classList.add("dragging");
    });
    window.addEventListener("mousemove", (event) => {
      if (!dragging || !lastPoint) return;
      const dx = event.clientX - lastPoint[0];
      const dy = event.clientY - lastPoint[1];
      if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
      mapView.offsetX += dx;
      mapView.offsetY += dy;
      lastPoint = [event.clientX, event.clientY];
      scheduleDrawMap();
    });
    window.addEventListener("mouseup", () => {
      dragging = false;
      lastPoint = null;
      $("mapShell").classList.remove("dragging");
    });
    $("mapCanvas").addEventListener("click", (event) => {
      if (moved) return;
      const rect = $("mapCanvas").getBoundingClientRect();
      selectedFeature = featureAt(event.clientX - rect.left, event.clientY - rect.top);
      scheduleDrawMap();
    });
    document.querySelectorAll("[data-metric]").forEach(button => {
      button.addEventListener("click", async () => {
        setActiveMetric(button.dataset.metric);
        if (resultCache[activeMetric]) {
          renderResult(resultCache[activeMetric], activeMetric, false);
          return;
        }
        currentMap = null;
        selectedFeature = null;
        canvasState.transform = null;
        canvasState.cachedFeatures = [];
        drawMap();
        $("mapCaption").textContent = activeMetric === "co2"
          ? "Loading CO2 emissions results..."
          : "Loading electricity demand results...";
        $("topBox").innerHTML = "No result loaded yet.";
        $("filesBox").innerHTML = "No output files yet.";
        $("legendBox").innerHTML = "No result loaded yet.";
        await generateActiveResult(activeMetric === "co2"
          ? "Generating CO2 emissions results..."
          : "Generating electricity demand results...");
      });
    });
    $("configToggle").addEventListener("click", openConfigModal);
    $("closeConfig").addEventListener("click", closeConfigModal);
    $("configModal").addEventListener("click", (event) => {
      if (event.target === $("configModal")) closeConfigModal();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && $("configModal").classList.contains("open")) {
        closeConfigModal();
      }
    });
    $("reloadConfig").addEventListener("click", async () => {
      await loadAll();
      setStatus("Configuration reloaded.", "ok");
    });
    $("saveConfig").addEventListener("click", async () => {
      try {
        await api("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ config: collectConfig() })
        });
        const refreshed = await api("/api/options");
        options = refreshed.options;
        updateYears();
        await loadVehicleFiles();
        await refreshProjectedShare();
        setStatus("Configuration saved.", "ok");
      } catch (err) {
        setStatus(err.message, "error");
      }
    });
    $("assignBtn").addEventListener("click", async () => {
      $("assignBtn").disabled = true;
      setStatus("Assigning vehicle types. Large MATSim XML files can take a little while...");
      try {
        const data = await api("/api/assign", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            config: collectConfig(),
            source: $("source").value,
            year: Number($("year").value),
            scenario: $("scenario").value,
            seed: Number($("seed").value),
            ev_factor: selectedEvFactor()
          })
        });
        lastAssignedVehicle = data.output_file;
        await loadVehicleFiles(data.output_file);
        renderShare(data.projected_share);
        renderSummary([
          { label: "Assigned agents", value: data.assigned_count.toLocaleString() },
          { label: "Bus vehicles", value: data.transit_vehicle_count.toLocaleString() },
          { label: "Vehicle types", value: Object.keys(data.type_counts).length },
          { label: "Year", value: $("year").value }
        ]);
        $("filesBox").innerHTML = `<table><tbody>
          <tr><td>assigned_vehicle_file</td><td><code>${data.output_file}</code></td></tr>
          <tr><td>composition_file</td><td><code>${data.distribution_file}</code></td></tr>
        </tbody></table>`;
        setStatus("Vehicle assignment completed.", "ok");
      } catch (err) {
        setStatus(err.message, "error");
      } finally {
        $("assignBtn").disabled = false;
      }
    });
    $("emissionBtn").addEventListener("click", async () => {
      $("emissionBtn").disabled = true;
      setStatus("Running MATSim emission module. This can take several minutes...");
      try {
        const vehicleFile = vehicleFileValue();
        if (!vehicleFile) throw new Error("Run vehicle assignment first or provide an assigned vehicle file.");
        const data = await api("/api/run-emissions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            config: collectConfig(),
            year: Number($("year").value),
            scenario: $("scenario").value,
            vehicle_file: vehicleFile
          })
        });
        updateConfigValue("emission_events_file", data.emission_events_file);
        $("filesBox").innerHTML = `<table><tbody>
          <tr><td>emission_events_file</td><td><code>${data.emission_events_file}</code></td></tr>
          <tr><td>emission_config_file</td><td><code>${data.emission_config_file}</code></td></tr>
          <tr><td>assigned_vehicle_file</td><td><code>${data.vehicle_file}</code></td></tr>
        </tbody></table>`;
        renderSummary([
          { label: "Emission events", value: "Ready" },
          { label: "Year", value: $("year").value },
          { label: "Scenario", value: $("scenario").value },
          { label: "Vehicle file", value: "Assigned" }
        ]);
        setStatus("Emission module completed. CO2 results will use the new emission events file.", "ok");
      } catch (err) {
        setStatus(err.message, "error");
      } finally {
        $("emissionBtn").disabled = false;
      }
    });
    $("resultsBtn").addEventListener("click", () => generateActiveResult());

    loadAll().catch(err => setStatus(err.message, "error"));
  </script>
</body>
</html>
"""


class PlatformHandler(BaseHTTPRequestHandler):
    server_version = "MATSimPlatform/0.1"

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}")

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                body = INDEX_HTML.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif parsed.path == "/api/config":
                config = core.load_config()
                self.send_json({"config": config, "options": core.list_vehicle_options(config)})
            elif parsed.path == "/api/options":
                config = core.load_config()
                self.send_json({"options": core.list_vehicle_options(config)})
            elif parsed.path == "/api/vehicle-files":
                config = core.load_config()
                self.send_json({"files": core.list_assignment_vehicle_files(config)})
            elif parsed.path == "/file":
                self.serve_file(parsed.query)
            else:
                self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        try:
            payload = self.read_json()
            if self.path == "/api/config":
                config = payload.get("config") or {}
                core.save_config(config)
                self.send_json({"ok": True})
            elif self.path == "/api/assign":
                config = payload.get("config") or core.load_config()
                result = core.assign_vehicle_types(
                    config=config,
                    year=int(payload["year"]),
                    source=payload["source"],
                    scenario=payload.get("scenario") or "HISTORICAL",
                    seed=int(payload.get("seed", 2)),
                    ev_factor=float(payload.get("ev_factor", 1.0)),
                )
                core.save_config(config)
                self.send_json(
                    {
                        "output_file": core.display_path(result.output_file),
                        "distribution_file": core.display_path(result.distribution_file),
                        "assigned_count": result.assigned_count,
                        "transit_vehicle_count": result.transit_vehicle_count,
                        "type_counts": result.type_counts,
                        "projected_share": result.projected_share,
                    }
                )
            elif self.path == "/api/projected-share":
                config = payload.get("config") or core.load_config()
                self.send_json(
                    {
                        "projected_share": core.projected_quebec_city_share(
                            config=config,
                            year=int(payload["year"]),
                            scenario=payload.get("scenario") or "BAU",
                            ev_factor=float(payload.get("ev_factor", 1.0)),
                            source=payload.get("source") or "predicted",
                        )
                    }
                )
            elif self.path == "/api/results":
                config = payload.get("config") or core.load_config()
                metric = payload.get("metric")
                year = int(payload["year"])
                scenario = payload.get("scenario") or "BAU"
                core.save_config(config)
                if metric == "co2":
                    self.send_json(core.generate_co2_results(config, year, scenario))
                elif metric == "ev":
                    vehicle_file = payload.get("vehicle_file")
                    if not vehicle_file:
                        raise ValueError("EV results require an assigned vehicle file.")
                    self.send_json(core.generate_ev_results(config, year, scenario, vehicle_file))
                else:
                    raise ValueError(f"Unknown metric: {metric}")
            elif self.path == "/api/run-emissions":
                config = payload.get("config") or core.load_config()
                result = core.run_emission_module(
                    config=config,
                    year=int(payload["year"]),
                    scenario=payload.get("scenario") or "BAU",
                    vehicle_file=payload["vehicle_file"],
                )
                core.save_config(config)
                self.send_json(result)
            else:
                self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def serve_file(self, query: str) -> None:
        params = parse_qs(query)
        raw_path = params.get("path", [""])[0]
        if not raw_path:
            self.send_json({"error": "Missing path"}, HTTPStatus.BAD_REQUEST)
            return
        path = core.resolve_path(raw_path).resolve()
        root = core.PROJECT_ROOT.resolve()
        if root not in path.parents and path != root:
            self.send_json({"error": "File path is outside the project"}, HTTPStatus.FORBIDDEN)
            return
        if not path.is_file():
            self.send_json({"error": f"File not found: {raw_path}"}, HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MATSim vehicle assignment GUI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), PlatformHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"MATSim Vehicle Assignment Platform running at {url}")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
