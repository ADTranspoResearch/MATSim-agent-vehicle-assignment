"""Tests for the platform indicators and what-if engine.

Run from the repository root:  python3 -m unittest discover -s tests
"""

import csv
import random
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from platform_gui import core, indicators, whatif  # noqa: E402

PAPER_TABLE = ROOT / "demo_data" / "paper_results" / "fsa_results.csv"


def synthetic_engine() -> whatif.WhatIfEngine:
    """Three FSAs, 100 agents, no files. Built by hand to avoid file input."""
    engine = object.__new__(whatif.WhatIfEngine)
    sizes = [40, 40, 20]
    engine.fsas = ["A", "B", "C"]
    engine.n_fsa = 3
    engine.fi = np.repeat(np.arange(3), sizes)
    rng = np.random.default_rng(1)
    engine.km = rng.uniform(5, 60, 100)
    engine.rate = np.full(100, 0.2)
    engine.g = whatif.DEFAULT_G_PER_KM.copy()
    engine.cal = np.ones(3)
    engine.n_agents_sample = np.array(sizes)
    engine.agents = engine.n_agents_sample * whatif.SAMPLE_EXPANSION_FACTOR
    engine.area = np.array([1.0, 2.0, 3.0])
    engine.n_persons = 100
    engine.pop_idx = np.arange(100)
    engine._draw_cache = {}
    return engine


BASE_SHARES = np.array([
    [0.1, 0.1, 0.1, 0.2, 0.3, 0.2],
    [0.4, 0.0, 0.1, 0.1, 0.3, 0.1],
    [0.0, 0.0, 0.2, 0.2, 0.4, 0.2],
])


class IndicatorTests(unittest.TestCase):
    def test_kappa_and_load_units(self):
        # 10 kt avoided for 20 GWh added is 500 g/kWh; 20 GWh over 4 h per day is 13.7 MW.
        kappa = indicators.kappa_g_per_kwh([30.0], [20.0], [0.0], [20.0])
        self.assertAlmostEqual(kappa[0], 500.0)
        self.assertAlmostEqual(float(indicators.load_mw(20.0, 4)), 20e3 / 365 / 4)

    def test_kappa_undefined_without_added_electricity(self):
        self.assertTrue(np.isnan(indicators.kappa_g_per_kwh([5.0], [4.0], [1.0], [1.0])[0]))

    def test_concentration(self):
        values = [50, 30, 10, 5, 5]
        self.assertAlmostEqual(indicators.top_share(values, 2), 0.8)
        self.assertEqual(indicators.fsas_for_half(values), 1)

    @unittest.skipUnless(PAPER_TABLE.exists(), "paper results not available locally")
    def test_matches_paper_values(self):
        with PAPER_TABLE.open(encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        by = {}
        for row in rows:
            if row["fsa"] == "NAN":
                continue
            by.setdefault(row["scenario"], {})[row["fsa"]] = {k: float(v) for k, v in row.items() if k not in ("fsa", "scenario")}
        fsas = sorted(by["BAU"])
        col = lambda s, c: np.array([by[s][f][c] for f in fsas])  # noqa: E731
        ref_co2, ref_gwh = col("REF2020", "co2_kt_yr"), col("REF2020", "ev_electricity_GWh_yr")
        co2, gwh = col("BAU", "co2_kt_yr"), col("BAU", "ev_electricity_GWh_yr")
        agents = col("BAU", "n_agents")
        kappa = indicators.kappa_g_per_kwh(ref_co2, co2, ref_gwh, gwh)
        self.assertAlmostEqual(np.nanmin(kappa), 295, delta=1)
        self.assertAlmostEqual(np.nanmax(kappa), 2158, delta=1)
        self.assertAlmostEqual(indicators.top_share(co2, 5), 0.282, places=3)
        self.assertEqual(indicators.fsas_for_half(co2), 12)
        city = indicators.citywide_summary(co2.sum(), gwh.sum(), col("BAU", "n_ev").sum(), col("BAU", "n_vehicles").sum(), agents.sum(),
                                           {"co2_kt": ref_co2.sum(), "electricity_gwh": ref_gwh.sum()})
        self.assertAlmostEqual(city["kappa_g_per_kwh"], 1012.0, delta=0.5)
        self.assertAlmostEqual(city["load_mw"]["4"], 344.1, delta=0.1)
        r = indicators.pearson(
            indicators.co2_per_agent_kg(ref_co2, agents), indicators.ev_share(col("BAU", "n_ev"), col("BAU", "n_vehicles"))
        )
        self.assertAlmostEqual(r["r"], -0.06, delta=0.01)


class EngineTests(unittest.TestCase):
    def test_draws_reproduce_assignment_code(self):
        """The vectorised draw must pick the same type as core.choose_vehicle_type."""
        engine = synthetic_engine()
        names = whatif.CATEGORIES
        distribution = {
            fsa: [(name, float(p)) for name, p in zip(names, BASE_SHARES[i]) if p > 0]
            for i, fsa in enumerate(engine.fsas)
        }
        rng = random.Random(2)
        expected = []
        for index in range(100):
            vehicle = core.choose_vehicle_type(engine.fsas[engine.fi[index]], distribution, rng)
            expected.append(names.index({"truck": "ice_van/pickup"}.get(vehicle, vehicle)))
        rng = random.Random(2)
        engine._draw_cache[2] = np.array([rng.random() for _ in range(100)])
        kind = engine.kinds(BASE_SHARES, engine.draws(2))
        self.assertEqual(kind.tolist(), expected)

    def test_adoption_keeps_shares_normalised(self):
        engine = synthetic_engine()
        for replace in ("proportional", "high_emitter"):
            for factor in (0.0, 0.5, 1.0, 1.7, 5.0):
                shares = engine.apply_adoption(BASE_SHARES, ev_factor=factor, replace=replace)
                np.testing.assert_allclose(shares.sum(axis=1), 1.0, atol=1e-9)
                self.assertTrue((shares >= -1e-12).all())

    def test_adoption_factor_zero_removes_evs_and_override_sets_share(self):
        engine = synthetic_engine()
        self.assertEqual(engine.apply_adoption(BASE_SHARES, ev_factor=0.0)[:, 0].max(), 0.0)
        shares = engine.apply_adoption(BASE_SHARES, overrides={"C": 0.9})
        self.assertAlmostEqual(shares[2, 0], 0.9)

    def test_high_emitter_displaces_pickups_first(self):
        engine = synthetic_engine()
        shares = engine.apply_adoption(BASE_SHARES, ev_factor=1.0, overrides={"A": 0.25}, replace="high_emitter")
        self.assertAlmostEqual(shares[0, 5], 0.05)  # 0.2 pickups lose the 0.15 added to EVs
        self.assertAlmostEqual(shares[0, 4], 0.3)

    def test_more_evs_means_less_co2_and_more_electricity(self):
        engine = synthetic_engine()
        draws = np.random.default_rng(3).random(100)
        low = engine.metrics(engine.kinds(engine.apply_adoption(BASE_SHARES, ev_factor=0.5), draws))
        high = engine.metrics(engine.kinds(engine.apply_adoption(BASE_SHARES, ev_factor=1.5), draws))
        self.assertLess(high["co2_kt"].sum(), low["co2_kt"].sum())
        self.assertGreater(high["gwh"].sum(), low["gwh"].sum())

    def test_waterfill_respects_caps_and_total(self):
        out = whatif._waterfill([1, 1, 1], [2, 50, 50], 30)
        self.assertEqual(out.sum(), 30)
        self.assertLessEqual(out[0], 2)
        self.assertEqual(whatif._waterfill([1, 1], [3, 4], 100).tolist(), [3, 4])

    def test_allocation_counts_and_targeting_gain(self):
        engine = synthetic_engine()
        engine.cal = np.array([3.0, 1.0, 1.0])  # FSA A emits three times as much per km
        kind = engine.kinds(BASE_SHARES, np.random.default_rng(5).random(100))
        base = engine.metrics(kind)
        selector = engine._selector(kind, "any", "random", seed=1)
        targeted = engine._allocate(kind, selector, 10, "top_resid", 1, base)
        uniform = engine._allocate(kind, selector, 10, "proportional", 1, base)
        self.assertEqual(targeted["n_evs"], 10 * whatif.SAMPLE_EXPANSION_FACTOR)
        self.assertEqual(uniform["n_evs"], 10 * whatif.SAMPLE_EXPANSION_FACTOR)
        self.assertEqual(int(np.argmax(targeted["per_fsa_evs"])), 0)
        self.assertGreater(targeted["avoided_kt_per_1000_evs"], uniform["avoided_kt_per_1000_evs"])

    def test_distance_order_gives_bounds(self):
        engine = synthetic_engine()
        kind = engine.kinds(BASE_SHARES, np.random.default_rng(5).random(100))
        base = engine.metrics(kind)
        results = {
            mode: engine._allocate(kind, engine._selector(kind, "any", mode, 1), 8, "proportional", 1, base)["avoided_kt"]
            for mode in ("low_km", "random", "high_km")
        }
        self.assertLess(results["low_km"], results["random"] + 1e-12)
        self.assertGreater(results["high_km"], results["random"] - 1e-12)


if __name__ == "__main__":
    unittest.main()
