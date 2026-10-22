"""Batch regressions. These tests never read the full 100% simulation.

The real Java integration test is opt-in via RUN_MATSIM_BATCH_INTEGRATION=1.
"""

import errno
import gzip
import math
import os
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from matsim_vehicle_type import batch
from matsim_vehicle_type.fleet import composition, growth
from platform_gui import core


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ev = core.load_script_module("test_batch_ev", batch.ROOT / "data_post-processing/summarize_ev_electricity_by_scenario.py")
        self.body_shares = {"Passenger cars": 1.0, "Multi-purpose vehicles": 0.0, "Pickup trucks and vans": 0.0}

    def base(self, count=120):
        return pd.DataFrame({
            "vehicle_id": [str(i) for i in range(count)],
            "agent_id": [f"person{i}" for i in range(count)],
            "fsa": ["G1B"] * count,
            "fsa_source": ["event_home"] * count,
            "distance_metres_per_day": [1000.0] * count,
        })

    def distribution(self):
        return {"shares": {"G1B": batch.checked_shares({"electric": 0.5, "ice_sedan": 0.5})},
                "city_average": batch.checked_shares({"electric": 1.0})}

    def test_native_batch_lock_exclusion_and_release_after_exception(self):
        directory = self.root / "batch"
        with self.assertRaisesRegex(ValueError, "body failed"):
            with batch.batch_lock(directory):
                with self.assertRaisesRegex(RuntimeError, "Another process"):
                    with batch.batch_lock(directory):
                        self.fail("A second batch acquired an occupied lock")
                raise ValueError("body failed")
        # Failed batch bodies must release their lock for a later retry.
        with batch.batch_lock(directory):
            pass

    def test_windows_file_lock_does_not_require_fcntl(self):
        calls = []
        stream = Mock()
        stream.fileno.return_value = 123
        stream.seek.side_effect = lambda position: calls.append(("seek", position))
        windows = types.SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0,
            locking=lambda fd, mode, size: calls.append(("locking", fd, mode, size)))
        with patch.object(batch.os, "name", "nt"), patch.dict(sys.modules, {"msvcrt": windows, "fcntl": None}):
            batch._file_lock(stream)
            batch._file_lock(stream, unlock=True)
        self.assertEqual(calls, [("seek", 0), ("locking", 123, 2, 1), ("seek", 0), ("locking", 123, 0, 1)])

    def test_lock_system_errors_are_not_reported_as_another_batch(self):
        with patch.object(batch, "_file_lock", side_effect=OSError(errno.EIO, "I/O failure")):
            with self.assertRaises(OSError) as raised:
                with batch.batch_lock(self.root / "batch"):
                    self.fail("Lock acquisition should fail")
        self.assertEqual(raised.exception.errno, errno.EIO)

    def test_seed_reproducibility_and_stable_input_order(self):
        base = self.base()
        args = (self.distribution(), 2035, "bau", 1, self.body_shares, self.ev)
        first = batch.assign_frame(base, *args)
        second = batch.assign_frame(base.iloc[::-1], *args)
        pd.testing.assert_frame_equal(first, second)
        different = batch.assign_frame(base, self.distribution(), 2035, "bau", 2, self.body_shares, self.ev)
        self.assertFalse(first.vehicle_type.equals(different.vehicle_type))

    def test_unknown_and_missing_fsa_use_city_average(self):
        base = self.base(2)
        base["fsa"] = ["UNKNOWN", "G1C"]
        assigned = batch.assign_frame(base, self.distribution(), 2035, "bau", 1, self.body_shares, self.ev)
        self.assertEqual(assigned.vehicle_type.tolist(), ["electric", "electric"])
        self.assertEqual(assigned.distribution_source.tolist(), ["unknown_fsa", "missing_fsa_distribution"])

    def test_vehicle_namespace_and_bus_metadata_are_preserved(self):
        source = self.root / "input.xml"
        source.write_text('''<vehicleDefinitions xmlns="http://www.matsim.org/files/dtd">
          <vehicleType id="Bus"><capacity seats="70"/><networkMode networkMode="bus"/></vehicleType>
          <vehicleType id="defaultVehicleType"/>
          <vehicle id="0" type="defaultVehicleType"/><vehicle id="veh_0_bus" type="Bus"/>
          </vehicleDefinitions>''')
        assigned = batch.assign_frame(self.base(1), self.distribution(), 2035, "bau", 1, self.body_shares, self.ev)
        target = self.root / "vehicles.xml.gz"
        batch.write_assigned_vehicles(source, target, assigned)
        with gzip.open(target, "rt") as stream:
            root = ET.parse(stream).getroot()
        ns = {"v": "http://www.matsim.org/files/dtd"}
        self.assertEqual(root.find("v:vehicle[@id='veh_0_bus']", ns).get("type"), "Bus")
        self.assertEqual(root.find("v:vehicleType[@id='Bus']/v:capacity", ns).get("seats"), "70")
        self.assertIsNotNone(root.find("v:vehicleType[@id='Bus']/v:engineInformation", ns))
        self.assertEqual(root.find("v:vehicle[@id='0']", ns).get("type"), assigned.vehicle_type.iloc[0])
        self.assertEqual(batch.read_vehicle_inventory(target), (["0"], {"veh_0_bus"}))

    def test_driver_mapping_ignores_passengers_and_counts_left_links(self):
        path = self.root / "events.xml"
        path.write_text('''<events>
          <event type="actend" actType="home" person="owner" x="1" y="2"/>
          <event type="PersonEntersVehicle" vehicle="car" person="passenger"/>
          <event type="vehicle enters traffic" vehicle="car" person="owner"/>
          <event type="left link" vehicle="car" link="L"/>
          <event type="entered link" vehicle="car" link="L"/>
          <event type="left link" vehicle="bus" link="L"/>
          </events>''')
        homes, drivers, metres, diagnostic = batch.scan_mobility(path, {"car"}, {"bus"}, {"L": 1250})
        self.assertEqual(drivers, {"car": "owner"})
        self.assertEqual(homes, {"owner": (1.0, 2.0)})
        self.assertEqual(metres, {"car": 1250})
        self.assertEqual(diagnostic["events"], 6)
        with self.assertRaisesRegex(ValueError, "missing links"):
            batch.scan_mobility(path, {"car"}, {"bus"}, {})

    def test_spatial_lookup_reports_unknown_and_shared_boundaries(self):
        import geopandas as gpd
        from shapely.geometry import box

        path = self.root / "fsas.shp"
        shapes = gpd.GeoDataFrame({"CFSAUID": ["G1C", "G1B"]},
            geometry=[box(1, 0, 2, 1), box(0, 0, 1, 1)], crs="EPSG:32187")
        shapes.to_file(path)
        located, diagnostic = batch.locate_homes({"inside": (0.5, 0.5), "edge": (1, 0.5), "outside": (3, 3)}, path, "EPSG:32187")
        self.assertEqual(located, {"inside": "G1B", "edge": "G1B"})
        self.assertEqual(diagnostic["boundary_ambiguous_persons"], 1)
        self.assertEqual(diagnostic["spatial_unmatched_persons"], 1)

    def test_history_controls_keep_raw_counts_and_composition_filter(self):
        directory, cache = self.root / "ownership", self.root / "cache"
        directory.mkdir()
        cache.mkdir()
        for year in range(2013, 2021):
            pd.DataFrame({"AnneeSAAQ": [year] * 4, "RTA": ["G1B"] * 4,
                "Entrant": [1, 0, 1, 0], "Sortant": [0, 1, 0, 1],
                "vehicle_type": ["electric", "ice_sedan", "unknown", "hev_van/pickup"]}).to_csv(
                    directory / f"Personal_McGill_SAAQ_{year}_2024-01-10.csv", index=False)
        options = batch.BatchOptions(ownership_dir=directory, chunksize=2)
        counts, totals = batch.aggregate_history(options, {"G1B"}, cache, "fixture")
        self.assertEqual(set(counts.vehicle_type), {"electric", "ice_sedan"})
        self.assertTrue(totals["size"].eq(4).all())
        self.assertTrue(totals["new"].eq(2).all())
        self.assertTrue(totals["exit"].eq(2).all())

    def test_daily_units_all_assigned_evs_and_zero_ev_rows(self):
        base = self.base(3)
        base["fsa"] = ["G1B", "G1B", "G1C"]
        base["distance_metres_per_day"] = [1000, 0, 2000]
        distribution = {"shares": {"G1B": batch.checked_shares({"electric": 1}),
                                    "G1C": batch.checked_shares({"ice_sedan": 1})},
                        "city_average": batch.checked_shares({"electric": 1})}
        assigned = batch.assign_frame(base, distribution, 2035, "bau", 1, self.body_shares, self.ev)
        result, audit = batch.daily_fsa_results(assigned, {"2": 2500}, ["G1B", "G1C", "G1E", "UNKNOWN"], 2035, "bau", 1)
        indexed = result.set_index("fsa")
        self.assertEqual(indexed.loc["G1B", "ev_count"], 2)
        self.assertEqual(indexed.loc["G1B", "active_ev_count"], 1)
        self.assertAlmostEqual(indexed.loc["G1B", "total_electricity_kwh_per_day"], 0.18)
        self.assertAlmostEqual(indexed.loc["G1B", "electricity_kwh_per_ev_per_day"], 0.09)
        self.assertEqual(indexed.loc["G1C", "total_co2_kg_per_day"], 2.5)
        self.assertTrue(math.isnan(indexed.loc["G1C", "co2_kg_per_ev_per_day"]))
        self.assertTrue(math.isnan(indexed.loc["G1E", "electricity_kwh_per_ev_per_day"]))
        self.assertAlmostEqual(audit.electricity_kwh_per_day.sum(), 0.18)

    def test_both_emission_types_and_invalid_vehicle_failures(self):
        path = self.root / "emissions.xml.gz"
        with gzip.open(path, "wt") as stream:
            stream.write('''<events><event type="warmEmissionEvent" vehicleId="0" CO2="1200"/>
              <event type="coldEmissionEvent" vehicle="0" CO2="300"/>
              <event type="warmEmissionEvent" vehicleId="bus" CO2="500"/></events>''')
        grams, counts = batch.summarize_emissions(path, {"0"}, {"bus"})
        self.assertEqual(grams, {"0": 1500})
        self.assertEqual(counts, {"warmEmissionEvent": 1, "coldEmissionEvent": 1, "excluded_bus_events": 1})
        with self.assertRaisesRegex(ValueError, "unknown vehicle"):
            batch.summarize_emissions(path, set(), {"bus"})

    def test_sample_standard_deviation_uses_per_seed_ratios(self):
        rows = []
        for seed, count, total in ((1, 1, 10.0), (2, 3, 60.0), (3, 0, 5.0)):
            rows.append({"year": 2035, "scenario": "bau", "seed": seed, "fsa": "G1B",
                "vehicle_count": 4, "ev_count": count, "active_ev_count": count,
                "total_co2_kg_per_day": total, "co2_kg_per_ev_per_day": total / count if count else np.nan,
                "total_electricity_kwh_per_day": count * 2,
                "electricity_kwh_per_ev_per_day": 2 if count else np.nan})
        row = batch.aggregate_replicates(pd.DataFrame(rows)).iloc[0]
        self.assertEqual(row.seed_count, 3)
        self.assertEqual(row.co2_kg_per_ev_per_day_n_valid, 2)
        self.assertEqual(row.co2_kg_per_ev_per_day_mean, 15)
        self.assertAlmostEqual(row.co2_kg_per_ev_per_day_std, math.sqrt(50))

    def test_summary_completion_is_independent_of_cleaned_raw_events(self):
        marker, output, raw = self.root / "summary.done.json", self.root / "fsa.csv", self.root / "events.gz"
        output.write_text("fsa,total_co2_kg_per_day\nG1B,1\n")
        raw.write_bytes(b"temporary dump")
        batch.save_stage(marker, "key", [output])
        raw.unlink()
        self.assertIsNotNone(batch.completed_stage(marker, "key"))
        self.assertIsNone(batch.completed_stage(marker, "different inputs"))
        output.write_text("corrupted")
        self.assertIsNone(batch.completed_stage(marker, "key"))

    def test_explicit_scenario_does_not_mutate_global_config(self):
        initial = {"electric": 0.03, "ice_sedan": 0.4, "ice_suv": 0.5, "hev_sedan": 0.07}
        trends = {"electric": 0.25, "ice_sedan": 0.01, "ice_suv": 0.02, "hev_sedan": 0.03}
        original = composition.SCN_CASE
        explicit = composition.predict_composition_trend(initial, trends, end_year=2041, scenario="pol_align")
        self.assertEqual(composition.SCN_CASE, original)
        self.assertAlmostEqual(explicit.loc["electric", 2035], 0.8)
        with patch.object(composition, "SCN_CASE", "pol_align"):
            implicit = composition.predict_composition_trend(initial, trends, end_year=2041)
        pd.testing.assert_frame_equal(explicit, implicit)

    def test_fleet_no_output_mode_preserves_stock_calculations(self):
        historic = [pd.DataFrame({"AnneeSAAQ": [2020, 2020], "vehicle_type": ["electric", "ice_sedan"], "count": [1, 9]})]
        controls = pd.DataFrame({"new": [2], "implied_exit": [1]}, index=[2021])
        mix = pd.DataFrame({2021: [0.5, 0.5]}, index=["electric", "ice_sedan"])
        stock = growth.predict_fleet_over_time(historic, controls, mix, "TEST", write_outputs=False)
        self.assertAlmostEqual(stock.loc["electric", 2021], 1.9)
        self.assertAlmostEqual(stock.loc["ice_sedan", 2021], 9.1)
        self.assertAlmostEqual(stock[2021].sum(), 11)

    @unittest.skipUnless(os.environ.get("RUN_MATSIM_BATCH_INTEGRATION") == "1", "real Java test is opt-in")
    def test_real_java_module_on_two_link_fixture(self):
        """Explicit opt-in invokes Java only on a tiny generated simulation."""
        options = batch.BatchOptions(output_dir=self.root, events=self.root / "events.xml", network=self.root / "network.xml")
        options.network.write_text('''<?xml version="1.0"?>
          <!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v2.dtd">
          <network><nodes><node id="n0" x="0" y="0"/><node id="n1" x="500" y="0"/>
          <node id="n2" x="1000" y="0"/></nodes><links>
          <link id="L1" from="n0" to="n1" length="500" freespeed="8.333333" capacity="1000" permlanes="1" modes="car">
          <attributes><attribute name="hbefa_road_type" class="java.lang.String">URB/Loc/30</attribute></attributes></link>
          <link id="L2" from="n1" to="n2" length="500" freespeed="8.333333" capacity="1000" permlanes="1" modes="car">
          <attributes><attribute name="hbefa_road_type" class="java.lang.String">URB/Loc/30</attribute></attributes></link>
          </links></network>''')
        options.events.write_text('''<?xml version="1.0"?><events version="1.0">
          <event time="3600" type="vehicle enters traffic" person="person0" vehicle="0" link="L1" networkMode="car" relativePosition="1"/>
          <event time="3600" type="left link" vehicle="0" link="L1"/>
          <event time="3600" type="entered link" vehicle="0" link="L2"/>
          <event time="3660" type="left link" vehicle="0" link="L2"/>
          <event time="3660" type="vehicle leaves traffic" person="person0" vehicle="0" link="L2" networkMode="car" relativePosition="1"/>
          </events>''')
        source = self.root / "input.xml"
        source.write_text('<vehicleDefinitions xmlns="http://www.matsim.org/files/dtd"><vehicle id="0" type="defaultVehicleType"/></vehicleDefinitions>')
        distribution = {"shares": {"G1B": batch.checked_shares({"ice_sedan": 1})}, "city_average": batch.checked_shares({"ice_sedan": 1})}
        assigned = batch.assign_frame(self.base(1), distribution, 2035, "bau", 1, self.body_shares, self.ev)
        vehicle_path = self.root / "vehicles.xml.gz"
        batch.write_assigned_vehicles(source, vehicle_path, assigned)
        config = batch.write_emission_config(options, self.root, vehicle_path, 1)
        (self.root / "emission").mkdir()
        batch.run_logged([batch.maven_command(), "-q", "-DskipTests", "compile"], options, self.root / "build.log")
        batch.run_logged([batch.maven_command(), "-q", "exec:java", f"-Dexec.mainClass={core.AVERAGE_EMISSION_MAIN_CLASS}",
                          f"-Demission.events.input={options.events}", f"-Dexec.args={config}"], options, self.root / "run.log")
        grams, _ = batch.summarize_emissions(self.root / "emission/emission.events.offline.xml.gz", {"0"}, set())
        self.assertGreater(grams.get("0", 0), 0)
        result, _ = batch.daily_fsa_results(assigned, grams, ["G1B", "UNKNOWN"], 2035, "bau", 1)
        self.assertAlmostEqual(result.total_co2_kg_per_day.sum(), grams["0"] / 1000)


if __name__ == "__main__":
    unittest.main()
