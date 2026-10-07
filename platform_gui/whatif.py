"""What-if engine: recompute FSA results for any adoption rate in milliseconds.

Why this is fast. Travel demand is held fixed across pathways and emissions
use average factors, so an agent's tailpipe CO2 depends only on its own vehicle
category. The engine therefore builds an agent table once (home FSA, simulated
km per day, kWh per km as an EV) and then evaluates any fleet composition as a
lookup and a sum. No MATSim run, no event parsing per change.

Vehicle draws follow ``core.assign_vehicle_types``: one uniform draw per
person, in population order, from ``random.Random(seed)``. A given seed
therefore reproduces the assigned vehicle file for the same share table.

Limits. Per-category CO2 factors are regressed from the reference emission
events (or taken from DEFAULT_G_PER_KM when none exist) and each FSA is
rescaled to match the reference run exactly. They are averages, so the engine
is valid only while demand and emission factors stay as in the reference run.
"""

from __future__ import annotations

import hashlib
import json
import random
import threading
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np

from . import core, indicators

CATEGORIES = ("electric", "hev_sedan", "hev_suv", "ice_sedan", "ice_suv", "ice_van/pickup")
EV = 0
# Placeholder g/km, used only when no emission events exist to regress from.
DEFAULT_G_PER_KM = np.array([0.0, 110.0, 140.0, 180.0, 230.0, 300.0])
# Categories an EV displaces first when the replaced vehicle is "highest emitter".
DISPLACE_ORDER = (5, 4, 3, 2, 1)
REPLACE_FILTERS = {
    "any": (1, 2, 3, 4, 5),
    "high_emitter": (4, 5),
    "sedan": (1, 3),
}
SAMPLE_EXPANSION_FACTOR = 10
DAYS_PER_YEAR = 365
DEFAULT_SEED = 2
REFERENCE_YEAR = 2020
SCENARIO_YEAR = 2035

_ENGINE_LOCK = threading.Lock()
_ENGINE: dict[str, Any] = {"key": None, "engine": None}


def clean(value: Any) -> Any:
    """Make nested numpy and NaN values JSON safe."""
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _file_signature(paths: list[Path]) -> str:
    parts = []
    for path in paths:
        if path.exists():
            stat = path.stat()
            parts.append(f"{path}:{stat.st_size}:{int(stat.st_mtime)}")
        else:
            parts.append(f"{path}:missing")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


def _waterfill(weights, caps, total) -> np.ndarray:
    """Split ``total`` units by weight without exceeding per-FSA caps."""
    weights = np.asarray(weights, dtype=float)
    caps = np.asarray(caps, dtype=float)
    total = min(float(total), float(caps.sum()))
    allocated = np.zeros(len(weights))
    remaining = total
    active = (weights > 0) & (caps > 0)
    for _ in range(len(weights) + 2):
        if remaining <= 1e-9 or not active.any():
            break
        share = np.where(active, weights, 0.0)
        share = share / share.sum() * remaining
        room = np.where(active, caps - allocated, 0.0)
        step = np.minimum(share, room)
        allocated += step
        remaining -= step.sum()
        active &= (caps - allocated) > 1e-9
    base = np.minimum(np.floor(allocated + 1e-9), caps)
    missing = int(round(total - base.sum()))
    if missing > 0:
        fraction = allocated - base
        fraction[caps - base < 1] = -1.0
        for index in np.argsort(-fraction)[:missing]:
            if caps[index] - base[index] >= 1:
                base[index] += 1
    return base.astype(int)


class WhatIfEngine:
    def __init__(self, config: dict[str, Any]):
        self.config = dict(config)
        self.mock = bool(config.get("mock_data"))
        self.notes: list[str] = []
        self._draw_cache: dict[int, np.ndarray] = {}
        self._share_cache: dict[str, np.ndarray] = {}
        self.fallback_fsas: dict[str, list[str]] = {}
        self.calibration: dict[str, dict[str, float]] = {}
        self._geometry: dict[str, Any] | None = None
        self._build()

    # ------------------------------------------------------------------ build
    def _paths(self) -> dict[str, Path]:
        config = self.config
        return {
            "lookup": core.resolve_path(config["fsa_lookup_file"]),
            "population": core.resolve_path(config["population_file"]),
            "events": core.resolve_path(config["matsim_events_file"]),
            "network": core.resolve_path(config["network_file"]),
            "shapefile": core.resolve_path(config["fsa_shapefile"]),
            "bev": core.resolve_path(config["historical_bev_share_file"]),
        }

    def _scenario_keys(self) -> list[dict[str, Any]]:
        options = core.list_vehicle_options(self.config)
        keys: list[dict[str, Any]] = []
        for year in options["historical_years"]:
            keys.append(
                {"key": f"{year}_HISTORICAL", "label": f"{year} reference", "year": year,
                 "source": "historical", "scenario": "HISTORICAL"}
            )
        for year in options["predicted_years"]:
            for scenario in options["predicted_scenarios"][str(year)]:
                if scenario == core.CUSTOM_ADOPTION_SCENARIO:
                    continue
                keys.append(
                    {"key": f"{year}_{scenario}", "label": f"{year} {scenario}", "year": year,
                     "source": "predicted", "scenario": scenario}
                )
        return keys

    def _build(self) -> None:
        paths = self._paths()
        self.scenarios = self._scenario_keys()
        by_key = {item["key"]: item for item in self.scenarios}
        if not by_key:
            raise FileNotFoundError("No vehicle composition files found for the what-if engine.")
        historical = [item for item in self.scenarios if item["source"] == "historical"]
        self.ref_key = next(
            (item["key"] for item in historical if item["year"] == REFERENCE_YEAR),
            historical[0]["key"] if historical else None,
        )
        self.base_key = (
            f"{SCENARIO_YEAR}_BAU"
            if f"{SCENARIO_YEAR}_BAU" in by_key
            else next(item["key"] for item in self.scenarios if item["source"] == "predicted")
        )

        lookup = core.read_fsa_lookup(paths["lookup"])
        person_ids: list[str] = []
        with core.open_text(paths["population"]) as stream:
            for _, element in ET.iterparse(stream, events=("end",)):
                if element.tag.rsplit("}", 1)[-1] == "person":
                    person_ids.append(element.get("id") or "")
                    element.clear()
        self.n_persons = len(person_ids)
        keep = [index for index, pid in enumerate(person_ids) if lookup.get(pid)]
        self.pop_idx = np.array(keep, dtype=int)
        self.ids = np.array([person_ids[index] for index in keep])
        agent_fsa = [lookup[pid] for pid in self.ids]
        self.fsas = sorted(set(agent_fsa))
        fsa_index = {fsa: index for index, fsa in enumerate(self.fsas)}
        self.fi = np.array([fsa_index[fsa] for fsa in agent_fsa], dtype=int)
        self.n_fsa = len(self.fsas)
        self.n_agents_sample = np.bincount(self.fi, minlength=self.n_fsa)
        self.agents = self.n_agents_sample * SAMPLE_EXPANSION_FACTOR

        shapes = {shape.fsa.upper(): shape for shape in core.read_fsa_shapes(paths["shapefile"])}
        self.area = np.array(
            [float(shapes[fsa].land_area or 0.0) if fsa in shapes else 0.0 for fsa in self.fsas]
        )

        cache_file = core.resolve_path(self.config["results_dir"]) / "whatif_agent_table.npz"
        co2_events = core.emission_events_for_scenario(
            self.config, SCENARIO_YEAR, self.base_key.split("_", 1)[1]
        )
        signature = _file_signature(
            [paths["lookup"], paths["population"], paths["events"], paths["network"], paths["bev"], co2_events]
            + [Path(core.vehicle_distribution_path(self.config, item["year"], item["source"], item["scenario"]))
               for item in self.scenarios]
        )
        if self._load_cache(cache_file, signature):
            return

        ev_module = core.load_script_module(
            "whatif_ev", core.PROJECT_ROOT / "data_post-processing" / "summarize_ev_electricity_by_scenario.py"
        )
        link_lengths = ev_module.read_link_lengths(paths["network"])
        metres, _, _ = ev_module.summarize_event_distances(paths["events"], set(self.ids.tolist()), link_lengths)
        self.km = np.array([metres.get(pid, 0.0) / 1000 for pid in self.ids])

        try:
            bev = ev_module.read_historical_shares(paths["bev"], 2024)
            self.rate = np.array(
                [ev_module.KWH_PER_KM_BY_TYPE[ev_module.assign_vehicle_type(pid, "BAU", bev)] for pid in self.ids]
            )
        except (OSError, KeyError, ValueError) as error:
            self.notes.append(f"EV consumption rates fell back to 0.22 kWh/km ({error}).")
            self.rate = np.full(len(self.ids), 0.22)

        self.g = DEFAULT_G_PER_KM.copy()
        self.cal = np.ones(self.n_fsa)
        self.calibrated = False
        self._calibrate(co2_events)
        self._save_cache(cache_file, signature)

    def _calibrate(self, co2_events: Path) -> None:
        """Regress g/km per category and one scale per FSA on all reference runs.

        Every scenario with emission events contributes: its vehicle types are
        drawn from the share table with the default seed, which reproduces the
        assigned vehicle file, and its emission events give the target CO2.
        """
        co2_module = core.load_script_module(
            "whatif_co2", core.PROJECT_ROOT / "data_post-processing" / "summarize_fsa_co2_emissions.py"
        )
        lookup = core.read_fsa_lookup(self._paths()["lookup"])
        draws = self.draws(DEFAULT_SEED)
        runs = []
        for item in self.scenarios:
            events = core.emission_events_for_scenario(self.config, item["year"], item["scenario"])
            if item["scenario"] == "HISTORICAL" and not events.name.endswith(f"{item['year']}.HISTORICAL.xml.gz"):
                events = events if events != core.resolve_path(self.config["emission_events_file"]) else Path("missing")
            if not events.exists() or (
                events == core.resolve_path(self.config["emission_events_file"])
                and item["key"] != self.base_key
            ):
                continue
            co2_by_agent, _, _, _, _ = co2_module.summarize_emission_events(events, lookup)
            actual = np.array([co2_by_agent.get(pid, 0.0) for pid in self.ids])
            runs.append((item["key"], self.kinds(self.shares(item["key"]), draws), actual))
        if not runs:
            self.notes.append("No emission events found: CO2 uses placeholder g/km factors.")
            return
        design = np.vstack([
            np.column_stack([np.where(kind == c, self.km, 0.0) for c in range(1, len(CATEGORIES))])
            for _, kind, _ in runs
        ])
        target = np.concatenate([actual for _, _, actual in runs])
        solution, _, rank, _ = np.linalg.lstsq(design, target, rcond=None)
        if rank == design.shape[1] and np.all(np.isfinite(solution)):
            self.g = np.concatenate([[0.0], np.clip(solution, 0.0, None)])
        else:
            self.notes.append("Could not regress g/km per category; using placeholders.")
        model = sum(np.bincount(self.fi, self.km * self.g[kind], self.n_fsa) for _, kind, _ in runs)
        observed = sum(np.bincount(self.fi, actual, self.n_fsa) for _, _, actual in runs)
        self.cal = np.divide(observed, model, out=np.ones(self.n_fsa), where=model > 0)
        self.calibrated = True
        factor = SAMPLE_EXPANSION_FACTOR * DAYS_PER_YEAR / 1e9
        self.calibration = {
            key: {
                "engine_kt": float((self.km * self.g[kind] * self.cal[self.fi]).sum() * factor),
                "events_kt": float(actual.sum() * factor),
            }
            for key, kind, actual in runs
        }

    def _save_cache(self, path: Path, signature: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                path, signature=signature, km=self.km, rate=self.rate, g=self.g, cal=self.cal,
                calibrated=self.calibrated, notes=json.dumps(self.notes), calibration=json.dumps(self.calibration),
            )
        except OSError:
            pass

    def _load_cache(self, path: Path, signature: str) -> bool:
        if not path.exists():
            return False
        try:
            data = np.load(path, allow_pickle=False)
            if str(data["signature"]) != signature or len(data["km"]) != len(self.ids):
                return False
            self.km, self.rate, self.g, self.cal = data["km"], data["rate"], data["g"], data["cal"]
            self.calibrated = bool(data["calibrated"])
            self.notes = json.loads(str(data["notes"]))
            self.calibration = json.loads(str(data["calibration"]))
            return True
        except (OSError, ValueError, KeyError):
            return False

    # ------------------------------------------------------------- composition
    def draws(self, seed: int) -> np.ndarray:
        if seed not in self._draw_cache:
            if len(self._draw_cache) > 8:
                self._draw_cache.pop(next(iter(self._draw_cache)))
            rng = random.Random(seed)
            all_draws = np.array([rng.random() for _ in range(self.n_persons)])
            self._draw_cache[seed] = all_draws[self.pop_idx]
        return self._draw_cache[seed]

    def random_draws(self, seed: int) -> np.ndarray:
        return np.random.default_rng(seed).random(self.n_persons)[self.pop_idx]

    def shares(self, key: str) -> np.ndarray:
        if key not in self._share_cache:
            item = next(entry for entry in self.scenarios if entry["key"] == key)
            path = core.vehicle_distribution_path(self.config, item["year"], item["source"], item["scenario"])
            distribution = core.read_vehicle_distribution(path)
            alias = {"truck": "ice_van/pickup"}
            matrix = np.zeros((self.n_fsa, len(CATEGORIES)))
            fallback = next(iter(distribution.values()), [])
            missing: list[str] = []
            for index, fsa in enumerate(self.fsas):
                rows = distribution.get(fsa)
                if rows is None:
                    rows = fallback
                    missing.append(fsa)
                for vehicle_type, probability in rows:
                    vehicle_type = alias.get(vehicle_type, vehicle_type)
                    if vehicle_type in CATEGORIES:
                        matrix[index, CATEGORIES.index(vehicle_type)] += probability
            total = matrix.sum(axis=1, keepdims=True)
            matrix = np.divide(matrix, total, out=np.zeros_like(matrix), where=total > 0)
            self._share_cache[key] = matrix
            self.fallback_fsas[key] = missing
        return self._share_cache[key]

    def kinds(self, shares: np.ndarray, draws: np.ndarray) -> np.ndarray:
        cumulative = np.cumsum(shares, axis=1)
        thresholds = cumulative[self.fi][:, :-1]
        point = draws * cumulative[self.fi][:, -1]
        return (point[:, None] >= thresholds).sum(axis=1)

    def apply_adoption(
        self,
        shares: np.ndarray,
        ev_factor: float = 1.0,
        replace: str = "proportional",
        overrides: dict[str, float] | None = None,
        boost_points: float = 0.0,
        boost_scores: np.ndarray | None = None,
        boost_k: int = 0,
    ) -> np.ndarray:
        old = shares[:, EV].copy()
        new = np.clip(old * ev_factor, 0.0, 1.0)
        if boost_points and boost_k and boost_scores is not None:
            order = np.argsort(-np.nan_to_num(boost_scores, nan=-np.inf))[:boost_k]
            new[order] = np.clip(new[order] + boost_points, 0.0, 1.0)
        for fsa, target in (overrides or {}).items():
            if fsa in self.fsas:
                new[self.fsas.index(fsa)] = float(np.clip(target, 0.0, 1.0))
        result = shares.copy()
        result[:, EV] = new
        rest_old = 1.0 - old
        delta = new - old
        if replace == "high_emitter":
            need = np.clip(delta, 0.0, None)
            for category in DISPLACE_ORDER:
                take = np.minimum(need, result[:, category])
                result[:, category] -= take
                need = need - take
            shrink = delta < 0
            scale = np.divide(1.0 - new, rest_old, out=np.ones_like(rest_old), where=rest_old > 0)
            result[shrink, 1:] = shares[shrink, 1:] * scale[shrink, None]
            leftover = np.clip(1.0 - result.sum(axis=1), 0.0, None)
            result[:, 5] += np.where(delta > 0, leftover, 0.0)
        else:
            scale = np.divide(1.0 - new, rest_old, out=np.zeros_like(rest_old), where=rest_old > 0)
            result[:, 1:] = shares[:, 1:] * scale[:, None]
        return result

    # ----------------------------------------------------------------- metrics
    def metrics(self, kind: np.ndarray) -> dict[str, np.ndarray]:
        factor = SAMPLE_EXPANSION_FACTOR * DAYS_PER_YEAR
        co2_g = self.km * self.g[kind] * self.cal[self.fi]
        is_ev = kind == EV
        counts = np.zeros((self.n_fsa, len(CATEGORIES)))
        for category in range(len(CATEGORIES)):
            counts[:, category] = np.bincount(self.fi, weights=(kind == category), minlength=self.n_fsa)
        return {
            "agents": self.agents.astype(float),
            "n_vehicles": self.agents.astype(float),
            "n_ev": np.bincount(self.fi, weights=is_ev, minlength=self.n_fsa) * SAMPLE_EXPANSION_FACTOR,
            "co2_kt": np.bincount(self.fi, weights=co2_g, minlength=self.n_fsa) * factor / 1e9,
            "gwh": np.bincount(self.fi, weights=self.km * self.rate * is_ev, minlength=self.n_fsa) * factor / 1e6,
            "counts": counts * SAMPLE_EXPANSION_FACTOR,
        }

    def rows(self, m: dict[str, np.ndarray], ref: dict[str, np.ndarray] | None) -> list[dict[str, Any]]:
        share = indicators.ev_share(m["n_ev"], m["n_vehicles"])
        per_agent = indicators.co2_per_agent_kg(m["co2_kt"], m["agents"])
        out: dict[str, Any] = {
            "fsa": self.fsas,
            "agents": m["agents"],
            "area_km2": self.area,
            "n_ev": m["n_ev"],
            "ev_share": share,
            "co2_kt": m["co2_kt"],
            "co2_kg_per_agent": per_agent,
            "electricity_gwh": m["gwh"],
            "electricity_kwh_per_agent": indicators.kwh_per_agent(m["gwh"], m["agents"]),
        }
        for index, category in enumerate(CATEGORIES):
            out[f"n_{category}"] = m["counts"][:, index]
        if ref is not None:
            added = indicators.added_electricity_gwh(m["gwh"], ref["gwh"])
            out["co2_reduction_kt"] = ref["co2_kt"] - m["co2_kt"]
            out["added_gwh"] = added
            out["kappa"] = indicators.kappa_g_per_kwh(ref["co2_kt"], m["co2_kt"], ref["gwh"], m["gwh"])
            out["density_mwh_km2"] = indicators.density_mwh_per_km2(added, self.area)
            out["ref_co2_kg_per_agent"] = indicators.co2_per_agent_kg(ref["co2_kt"], ref["agents"])
            out["ref_ev_share"] = indicators.ev_share(ref["n_ev"], ref["n_vehicles"])
            for window in indicators.CHARGING_WINDOWS_H:
                out[f"load_mw_{window}h"] = indicators.load_mw(added, window)
        return [{name: values[i] for name, values in out.items()} for i in range(self.n_fsa)]

    def citywide(self, m: dict[str, np.ndarray], ref_city: dict[str, float] | None) -> dict[str, Any]:
        return indicators.citywide_summary(
            float(m["co2_kt"].sum()), float(m["gwh"].sum()), float(m["n_ev"].sum()),
            float(m["n_vehicles"].sum()), float(m["agents"].sum()), ref_city,
        )

    def reference(self, seed: int = DEFAULT_SEED) -> dict[str, np.ndarray]:
        if self.ref_key is None:
            raise FileNotFoundError("No historical reference composition available.")
        return self.metrics(self.kinds(self.shares(self.ref_key), self.draws(seed)))

    # ------------------------------------------------------------------ views
    def describe(self) -> dict[str, Any]:
        self.shares(self.base_key)
        if self.ref_key:
            self.shares(self.ref_key)
        return clean({
            "mock": self.mock,
            "fsas": self.fsas,
            "agents": self.agents,
            "area_km2": self.area,
            "scenarios": self.scenarios,
            "ref_key": self.ref_key,
            "base_key": self.base_key,
            "categories": CATEGORIES,
            "g_per_km": dict(zip(CATEGORIES, self.g)),
            "calibrated": self.calibrated,
            "calibration": self.calibration,
            "notes": self.notes,
            "fallback_fsas": {key: value for key, value in self.fallback_fsas.items() if value},
            "total_agents": int(self.agents.sum()),
            "windows": indicators.CHARGING_WINDOWS_H,
        })

    def scenario_tables(self, seed: int = DEFAULT_SEED) -> dict[str, Any]:
        ref = self.reference(seed)
        ref_city = self.citywide(ref, None)
        tables: dict[str, Any] = {}
        for item in self.scenarios:
            m = self.metrics(self.kinds(self.shares(item["key"]), self.draws(seed)))
            is_ref = item["key"] == self.ref_key
            tables[item["key"]] = {
                "label": item["label"],
                "rows": self.rows(m, None if is_ref else ref),
                "citywide": self.citywide(m, None if is_ref else ref_city),
            }
        return clean({"ref_key": self.ref_key, "tables": tables, "ref_citywide": ref_city})

    def run(self, params: dict[str, Any]) -> dict[str, Any]:
        seed = int(params.get("seed", DEFAULT_SEED))
        base_key = params.get("base") or self.base_key
        draws = self.draws(seed)
        ref = self.reference(seed)
        ref_city = self.citywide(ref, None)
        base_shares = self.shares(base_key)
        base = self.metrics(self.kinds(base_shares, draws))
        score = indicators.co2_per_agent_kg(base["co2_kt"], base["agents"])
        shares = self.apply_adoption(
            base_shares,
            ev_factor=float(params.get("ev_factor", 1.0)),
            replace=params.get("replace", "proportional"),
            overrides={str(k).upper(): float(v) for k, v in (params.get("overrides") or {}).items()},
            boost_points=float(params.get("boost_points", 0.0)),
            boost_scores=score,
            boost_k=int(params.get("boost_k", 0)),
        )
        scenario = self.metrics(self.kinds(shares, draws))
        return clean({
            "rows": self.rows(scenario, ref),
            "base_rows": self.rows(base, ref),
            "citywide": self.citywide(scenario, ref_city),
            "base_citywide": self.citywide(base, ref_city),
            "ref_citywide": ref_city,
            "expected_ev_share": float((shares[:, EV] * self.agents).sum() / self.agents.sum()),
        })

    # ------------------------------------------------------------- allocation
    def _selector(self, kind: np.ndarray, replaces: str, within: str, seed: int):
        mask = np.isin(kind, REPLACE_FILTERS[replaces])
        eligible = np.flatnonzero(mask)
        if within == "random":
            key = np.random.default_rng(seed).random(len(eligible))
        elif within == "high_km":
            key = -self.km[eligible]
        else:
            key = self.km[eligible]
        order = np.lexsort((key, self.fi[eligible]))
        sorted_idx = eligible[order]
        fsa_sorted = self.fi[sorted_idx]
        starts = np.r_[0, np.flatnonzero(np.diff(fsa_sorted)) + 1]
        lengths = np.diff(np.r_[starts, len(fsa_sorted)])
        rank = np.arange(len(fsa_sorted)) - np.repeat(starts, lengths)
        return {"idx": sorted_idx, "fsa": fsa_sorted, "rank": rank,
                "caps": np.bincount(fsa_sorted, minlength=self.n_fsa)}

    def _allocate(self, kind, selector, n_extra, rule, k, base_metrics):
        caps = selector["caps"]
        idx = selector["idx"]
        avoided_g = self.km[idx] * self.g[kind[idx]] * self.cal[selector["fsa"]]
        added_kwh = self.km[idx] * self.rate[idx]
        kappa_f = np.divide(
            np.bincount(selector["fsa"], avoided_g, self.n_fsa),
            np.bincount(selector["fsa"], added_kwh, self.n_fsa),
            out=np.full(self.n_fsa, np.nan), where=np.bincount(selector["fsa"], added_kwh, self.n_fsa) > 0,
        )
        resid = indicators.co2_per_agent_kg(base_metrics["co2_kt"], base_metrics["agents"])
        weights = self.agents.astype(float)
        if rule == "equal":
            weights = np.ones(self.n_fsa)
        elif rule in ("top_resid", "top_kappa"):
            score = resid if rule == "top_resid" else kappa_f
            score = np.where(caps > 0, np.nan_to_num(score, nan=-np.inf), -np.inf)
            chosen = np.argsort(-score)[: max(int(k), 1)]
            mask = np.zeros(self.n_fsa, dtype=bool)
            mask[chosen] = True
            weights = np.where(mask, weights, 0.0)
        per_fsa = _waterfill(weights, caps, n_extra)
        pick = selector["rank"] < per_fsa[selector["fsa"]]
        f = SAMPLE_EXPANSION_FACTOR * DAYS_PER_YEAR
        avoided_by_fsa = np.bincount(selector["fsa"][pick], avoided_g[pick], self.n_fsa) * f / 1e9
        added_by_fsa = np.bincount(selector["fsa"][pick], added_kwh[pick], self.n_fsa) * f / 1e6
        n_sample = int(pick.sum())
        n_real = n_sample * SAMPLE_EXPANSION_FACTOR
        avoided = float(avoided_by_fsa.sum())
        added = float(added_by_fsa.sum())
        return {
            "n_evs": n_real,
            "avoided_kt": avoided,
            "added_gwh": added,
            "avoided_kt_per_1000_evs": avoided / (n_real / 1000) if n_real else 0.0,
            "kappa_g_per_kwh": avoided * 1e9 / (added * 1e6) if added > 0 else None,
            "per_fsa_evs": per_fsa * SAMPLE_EXPANSION_FACTOR,
            "per_fsa_avoided_kt": avoided_by_fsa,
        }

    def policy(self, params: dict[str, Any]) -> dict[str, Any]:
        seed = int(params.get("seed", DEFAULT_SEED))
        key = params.get("base") or self.base_key
        rule = params.get("rule", "top_resid")
        k = int(params.get("k", 5))
        replaces = params.get("replaces", "any")
        within = params.get("within", "random")
        n_real = int(params.get("n_extra", 1000))
        n_sample = max(int(round(n_real / SAMPLE_EXPANSION_FACTOR)), 1)
        kind = self.kinds(self.shares(key), self.draws(seed))
        base = self.metrics(kind)
        selectors = {
            mode: self._selector(kind, replaces, mode, seed) for mode in ("random", "high_km", "low_km")
        }
        main = self._allocate(kind, selectors[within], n_sample, rule, k, base)
        proportional = self._allocate(kind, selectors[within], n_sample, "proportional", k, base)
        gain = None
        if proportional["avoided_kt_per_1000_evs"] > 0:
            gain = main["avoided_kt_per_1000_evs"] / proportional["avoided_kt_per_1000_evs"] - 1

        fleet_sample = int(self.n_agents_sample.sum())
        fractions = (0.005, 0.01, 0.02, 0.03, 0.05)
        curve_n = []
        for fraction in fractions:
            count = max(int(round(fleet_sample * fraction)), 1)
            point = {"n_evs": count * SAMPLE_EXPANSION_FACTOR, "fraction": fraction}
            for name in ("proportional", "equal", "top_resid", "top_kappa"):
                result = self._allocate(kind, selectors[within], count, name, k, base)
                point[name] = result["avoided_kt_per_1000_evs"]
                point[f"{name}_total"] = result["avoided_kt"]
            curve_n.append(point)
        curve_k = []
        for value in (1, 2, 3, 5, 8, 12, 20, 30, self.n_fsa):
            point = {"k": value}
            for name in ("top_resid", "top_kappa"):
                point[name] = self._allocate(kind, selectors[within], n_sample, name, value, base)[
                    "avoided_kt_per_1000_evs"
                ]
            curve_k.append(point)
        bounds = {
            mode: self._allocate(kind, selectors[mode], n_sample, rule, k, base)["avoided_kt_per_1000_evs"]
            for mode in ("random", "high_km", "low_km")
        }
        return clean({
            "result": {name: value for name, value in main.items() if not name.startswith("per_fsa")},
            "per_fsa": [
                {"fsa": fsa, "evs": main["per_fsa_evs"][i], "avoided_kt": main["per_fsa_avoided_kt"][i]}
                for i, fsa in enumerate(self.fsas)
            ],
            "proportional": {k_: v for k_, v in proportional.items() if not k_.startswith("per_fsa")},
            "gain_vs_proportional": gain,
            "curve_n": curve_n,
            "curve_k": curve_k,
            "within_bounds": bounds,
            "eligible_evs": int(selectors[within]["caps"].sum()) * SAMPLE_EXPANSION_FACTOR,
        })

    # -------------------------------------------------------------- stability
    def stability(self, params: dict[str, Any]) -> dict[str, Any]:
        key = params.get("base") or self.base_key
        runs = int(np.clip(int(params.get("runs", 100)), 5, 500))
        k = int(params.get("k", 5))
        base_shares, ref_shares = self.shares(key), self.shares(self.ref_key)
        names = ("residual", "kappa", "density")
        values = {name: np.zeros((runs, self.n_fsa)) for name in names}
        added_all = np.zeros((runs, self.n_fsa))
        for run in range(runs):
            u = self.random_draws(10_000 + run)
            m = self.metrics(self.kinds(base_shares, u))
            r = self.metrics(self.kinds(ref_shares, u))
            added = indicators.added_electricity_gwh(m["gwh"], r["gwh"])
            values["residual"][run] = indicators.co2_per_agent_kg(m["co2_kt"], m["agents"])
            values["kappa"][run] = indicators.kappa_g_per_kwh(r["co2_kt"], m["co2_kt"], r["gwh"], m["gwh"])
            values["density"][run] = indicators.density_mwh_per_km2(added, self.area)
            added_all[run] = added
        top = {}
        for name in names:
            ranked = np.nan_to_num(values[name], nan=-np.inf)
            order = np.argsort(-ranked, axis=1)[:, :k]
            member = np.zeros_like(ranked, dtype=bool)
            np.put_along_axis(member, order, True, axis=1)
            top[name] = member
        overlap = (top["residual"].astype(int) + top["kappa"].astype(int) + top["density"].astype(int)) >= 2
        warnings.simplefilter("ignore", RuntimeWarning)
        mean = {name: np.nanmean(values[name], axis=0) for name in names}
        mean_added = added_all.mean(axis=0)
        q75 = {name: np.nanpercentile(mean[name], 75) for name in names}
        q50_kappa = np.nanmedian(mean["kappa"])
        q75_added = np.percentile(mean_added, 75)
        fsa_rows = []
        for i, fsa in enumerate(self.fsas):
            high_resid = mean["residual"][i] >= q75["residual"]
            high_kappa = mean["kappa"][i] >= q75["kappa"] if np.isfinite(mean["kappa"][i]) else False
            low_kappa = mean["kappa"][i] <= q50_kappa if np.isfinite(mean["kappa"][i]) else True
            levers = []
            if high_resid and high_kappa:
                levers.append("Adoption support or vehicle replacement")
            if high_resid and low_kappa:
                levers.append("Complement EVs: retire vehicles, reduce driving")
            if high_kappa and mean_added[i] >= q75_added:
                levers.append("Managed charging, early grid preparation")
            if mean["density"][i] >= q75["density"]:
                levers.append("Charging access study (multi-unit, public chargers)")
            fsa_rows.append({
                "fsa": fsa,
                **{f"p_top_{name}": float(top[name][:, i].mean()) for name in names},
                **{f"{name}_mean": mean[name][i] for name in names},
                **{f"{name}_p5": np.nanpercentile(values[name][:, i], 5) for name in names},
                **{f"{name}_p95": np.nanpercentile(values[name][:, i], 95) for name in names},
                "levers": levers,
            })
        return clean({
            "runs": runs,
            "k": k,
            "fsas": fsa_rows,
            "disjoint_top_lists_fraction": float((~overlap.any(axis=1)).mean()),
            "robust": {
                name: [row["fsa"] for row in fsa_rows if row[f"p_top_{name}"] >= 0.8] for name in names
            },
        })

    # --------------------------------------------------------------- geometry
    def geometry(self) -> dict[str, Any]:
        if self._geometry is not None:
            return self._geometry
        shapefile = core.resolve_path(self.config["fsa_shapefile"])
        cache = core.resolve_path(self.config["results_dir"]) / "whatif_geometry.json"
        signature = _file_signature([shapefile, shapefile.with_suffix(".dbf")]) + ":" + ",".join(self.fsas)
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if cached.get("signature") == signature:
                self._geometry = cached["geometry"]
                return self._geometry
        except (OSError, ValueError, KeyError):
            pass
        self._geometry = self._build_geometry()
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"signature": signature, "geometry": self._geometry}), encoding="utf-8")
        except OSError:
            pass
        return self._geometry

    def _build_geometry(self) -> dict[str, Any]:
        shapes = core.read_fsa_shapes(core.resolve_path(self.config["fsa_shapefile"]))
        values = {fsa: 1.0 for fsa in self.fsas}
        bounds = core.bounds_for_map_shapes(shapes, values)
        features = []
        for shape in shapes:
            if not core.boxes_intersect(shape.bbox, bounds):
                continue
            parts = []
            for part in shape.parts:
                if len(part) < 3 or not core.boxes_intersect(core.polygon_bbox(part), bounds):
                    continue
                simplified = core.simplify_polyline(part)
                if len(simplified) >= 4:
                    parts.append([[round(x, 1), round(y, 1)] for x, y in simplified])
            if parts:
                features.append({"fsa": shape.fsa.upper(), "parts": parts, "has_data": shape.fsa.upper() in values})
        return {"bounds": [round(number, 1) for number in bounds], "features": features}


def get_engine(config: dict[str, Any], force: bool = False) -> WhatIfEngine:
    keys = (
        "fsa_lookup_file", "population_file", "matsim_events_file", "network_file", "fsa_shapefile",
        "historical_bev_share_file", "historical_vehicle_share_dir", "predicted_vehicle_share_dir",
        "emission_events_dir", "emission_events_file", "results_dir", "mock_data",
    )
    key = json.dumps({name: config.get(name) for name in keys}, sort_keys=True)
    with _ENGINE_LOCK:
        if force or _ENGINE["key"] != key:
            _ENGINE["engine"] = WhatIfEngine(config)
            _ENGINE["key"] = key
        return _ENGINE["engine"]
