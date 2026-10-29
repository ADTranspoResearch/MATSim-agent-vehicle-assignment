"""Batch regressions. These tests never read the full 100% simulation.

The real Java integration test is opt-in via RUN_MATSIM_BATCH_INTEGRATION=1.
"""

import errno
import gzip
import io
import json
import math
import os
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
from urllib.request import url2pathname

import numpy as np
import pandas as pd

from matsim_vehicle_type import batch
from matsim_vehicle_type.fleet import composition, growth
from platform_gui import core


BUS_TYPE_XML = '''<vehicleType id="Bus">
  <attributes><attribute name="doorOperationMode" class="org.matsim.vehicles.VehicleType$DoorOperationMode">serial</attribute></attributes>
  <description>Transit bus</description>
  <capacity seats="70" standingRoomInPersons="0"/>
  <length meter="18.0"/><width meter="2.5"/><maximumVelocity meterPerSecond="25"/>
  <engineInformation><attributes>
    <attribute name="HbefaVehicleCategory" class="java.lang.String">old</attribute>
  </attributes></engineInformation>
  <costInformation fixedCostsPerDay="10"/>
  <passengerCarEquivalents pce="2.8"/><networkMode networkMode="bus"/>
  <flowEfficiencyFactor factor="1.0"/>
</vehicleType>'''


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

    def test_cli_and_program_defaults_use_100_percent_inputs_and_ten_seeds(self):
        with patch.dict(sys.modules, {"_setup_path": types.ModuleType("_setup_path")}):
            cli = core.load_script_module("test_batch_cli", batch.ROOT / "scripts/run_scenario_batch.py")
        args, options = cli.parser().parse_args([]), batch.BatchOptions()
        self.assertEqual(tuple(args.seeds), tuple(range(1, 11)))
        self.assertEqual(options.seeds, tuple(args.seeds))
        for name in ("events", "vehicles", "network", "output_dir"):
            self.assertEqual(getattr(args, name), getattr(options, name))
        self.assertEqual(options.events.name, "output_events_100.xml.gz")
        self.assertEqual(options.vehicles.name, "output_allVehicles_with_events_100_ids.xml.gz")
        self.assertEqual(options.network.name, "QC_network_fixed_1022.xml")
        self.assertEqual(options.output_dir.name, "batch_100_10seeds")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli.main(["--dry-run"]), 0)
        self.assertIn("50 runs; no files created", output.getvalue())
        self.assertIn("2035_pol_align/seed10", output.getvalue())
        custom = cli.parser().parse_args(["--scenarios", "2035_bau", "--seeds", "8", "19"])
        self.assertEqual(custom.seeds, [8, 19])

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
        source.write_text(f'''<vehicleDefinitions xmlns="http://www.matsim.org/files/dtd">
          {BUS_TYPE_XML}
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
        bus = root.find("v:vehicleType[@id='Bus']", ns)
        # MATSim's vehicleDefinitions_v2.0.xsd requires this child sequence.
        self.assertEqual([node.tag.rsplit("}", 1)[-1] for node in bus], [
            "attributes", "description", "capacity", "length", "width", "maximumVelocity",
            "engineInformation", "costInformation", "passengerCarEquivalents", "networkMode", "flowEfficiencyFactor"])
        self.assertEqual(bus.find("v:capacity", ns).get("seats"), "70")
        self.assertEqual(bus.find("v:attributes/v:attribute", ns).text, "serial")
        self.assertEqual(bus.find("v:maximumVelocity", ns).get("meterPerSecond"), "25")
        self.assertEqual(bus.find("v:costInformation", ns).get("fixedCostsPerDay"), "10")
        self.assertEqual(bus.find("v:passengerCarEquivalents", ns).get("pce"), "2.8")
        category = bus.find("v:engineInformation/v:attributes/v:attribute[@name='HbefaVehicleCategory']", ns)
        self.assertEqual(category.text, "Bus")
        self.assertEqual(root.find("v:vehicle[@id='0']", ns).get("type"), assigned.vehicle_type.iloc[0])
        self.assertEqual(batch.read_vehicle_inventory(target), (["0"], {"veh_0_bus"}))

    def test_emission_config_path_with_spaces_and_commas_is_one_argument(self):
        config = self.root / "Research Data, scenario's run" / "emission_config.xml"
        options = batch.BatchOptions()
        path = self.root / "emission.log"
        with patch.object(batch, "maven_command", return_value="mvn"), patch.object(batch, "run_logged") as run:
            batch.run_emission(options, config, path)
        command = run.call_args.args[0]
        self.assertIn("-Dexec.arguments=${env.MATSIM_BATCH_CONFIG_URI}", command)
        self.assertFalse(any(part.startswith("-Dexec.args=") for part in command))
        uri = run.call_args.kwargs["extra_env"]["MATSIM_BATCH_CONFIG_URI"]
        self.assertEqual(urlsplit(uri).scheme, "file")
        self.assertEqual(Path(url2pathname(urlsplit(uri).path)), config.resolve())
        self.assertIn("%20", uri)
        self.assertIn("%2C", uri)
        self.assertNotIn(uri, command)

    def test_maven_receives_config_environment_without_changing_parent(self):
        options = batch.BatchOptions()
        uri = "file:///C:/Users/qchen7/Research%20Data/emission_config.xml"
        process = Mock()
        process.wait.return_value = 0
        with patch.dict(os.environ, {"MATSIM_BATCH_CONFIG_URI": "parent"}), patch.object(batch.subprocess, "Popen", return_value=process) as popen:
            batch.run_logged(["mvn", "exec:java"], options, self.root / "emission.log",
                             extra_env={"MATSIM_BATCH_CONFIG_URI": uri})
            self.assertEqual(popen.call_args.kwargs["env"]["MATSIM_BATCH_CONFIG_URI"], uri)
            self.assertEqual(os.environ["MATSIM_BATCH_CONFIG_URI"], "parent")

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
        emissions = batch.EmissionSummary({"2": [2000, 500]}, {"L": [2000, 500]}, {})
        result, audit = batch.daily_fsa_results(assigned, emissions, ["G1B", "G1C", "G1E", "UNKNOWN"], 2035, "bau", 1)
        indexed = result.set_index("fsa")
        self.assertEqual(indexed.loc["G1B", "ev_count"], 2)
        self.assertEqual(indexed.loc["G1B", "active_ev_count"], 1)
        self.assertAlmostEqual(indexed.loc["G1B", "total_electricity_kwh_per_day"], 0.18)
        self.assertAlmostEqual(indexed.loc["G1B", "electricity_kwh_per_ev_per_day"], 0.09)
        self.assertEqual(indexed.loc["G1C", "total_co2_kg_per_day"], 2.5)
        self.assertTrue(math.isnan(indexed.loc["G1C", "co2_kg_per_ev_per_day"]))
        self.assertTrue(math.isnan(indexed.loc["G1E", "electricity_kwh_per_ev_per_day"]))
        self.assertAlmostEqual(audit.electricity_kwh_per_day.sum(), 0.18)
        self.assertEqual(indexed.loc["G1B", "total_distance_km_per_day"], 1)
        self.assertEqual(indexed.loc["G1C", "total_distance_km_per_day"], 2)
        self.assertEqual(audit.set_index("vehicle_id").loc["1", "distance_km_per_day"], 0)
        self.assertTrue(audit.year.eq(2035).all() and audit.scenario.eq("bau").all() and audit.seed.eq(1).all())
        roads = batch.daily_link_results(emissions, {"L", "empty"}, 2035, "bau", 1)
        self.assertEqual(roads.set_index("link_id").loc["empty", "co2_kg_per_day"], 0)
        totals = batch.validate_daily_results(result, audit, roads)
        self.assertEqual(totals["total_distance_km_per_day"], 3)
        self.assertEqual(totals["total_co2_kg_per_day"], 2.5)
        damaged = roads.copy()
        damaged.loc[damaged.link_id.eq("L"), "co2_kg_per_day"] += 1
        with self.assertRaisesRegex(ValueError, "warm/cold"):
            batch.validate_daily_results(result, audit, damaged)
        damaged.loc[damaged.link_id.eq("L"), "warm_co2_kg_per_day"] += 1
        with self.assertRaisesRegex(ValueError, "Vehicle/link"):
            batch.validate_daily_results(result, audit, damaged)
        with self.assertRaisesRegex(ValueError, "Vehicle/FSA"):
            batch.validate_daily_results(result.assign(total_distance_km_per_day=0), audit, roads)

    def test_both_emission_types_and_invalid_vehicle_failures(self):
        path = self.root / "emissions.xml.gz"
        with gzip.open(path, "wt") as stream:
            stream.write('''<events><event type="warmEmissionEvent" vehicleId="0" linkId="L1" CO2="1200"/>
              <event type="coldEmissionEvent" vehicle="0" link="L2" CO2="300"/>
              <event type="warmEmissionEvent" vehicleId="bus" CO2="500"/></events>''')
        with patch.object(batch, "scan_xml", wraps=batch.scan_xml) as scan:
            emissions = batch.summarize_emissions(path, {"0"}, {"bus"}, {"L1", "L2"})
        self.assertEqual(scan.call_count, 1)
        self.assertEqual(emissions.vehicle_grams, {"0": [1200, 300]})
        self.assertEqual(emissions.link_grams, {"L1": [1200, 0], "L2": [0, 300]})
        self.assertEqual(emissions.counts, {"warmEmissionEvent": 1, "coldEmissionEvent": 1, "excluded_bus_events": 1})
        with self.assertRaisesRegex(ValueError, "unknown vehicle"):
            batch.summarize_emissions(path, set(), {"bus"}, {"L1", "L2"})

    def test_missing_links_and_invalid_co2_fail_before_cleanup(self):
        path = self.root / "events.xml"
        cases = [("", "1", "missing/unknown link"), ('link="absent"', "1", "missing/unknown link"),
                 ('link="L"', None, "CO2 missing"), ('link="L"', "nan", "Invalid CO2"),
                 ('link="L"', "inf", "Invalid CO2"), ('link="L"', "-1", "Invalid CO2"),
                 ('link="L"', "invalid", "Invalid CO2")]
        for link, value, message in cases:
            with self.subTest(link=link, value=value):
                co2 = "" if value is None else f'CO2="{value}"'
                path.write_text(f'<events><event type="warmEmissionEvent" vehicle="0" {link} {co2}/></events>')
                with self.assertRaisesRegex(ValueError, message):
                    batch.summarize_emissions(path, {"0"}, set(), {"L"})
                self.assertTrue(path.exists())

    def test_valid_zero_emissions_keep_all_vehicles_and_links(self):
        path = self.root / "events.xml"
        for xml in ('<events/>', '<events><event type="warmEmissionEvent" vehicle="0" link="L" CO2="0"/></events>'):
            with self.subTest(xml=xml):
                path.write_text(xml)
                emissions = batch.summarize_emissions(path, {"0", "1"}, set(), {"L", "empty"})
                assigned = batch.assign_frame(self.base(2), self.distribution(), 2035, "bau", 1, self.body_shares, self.ev)
                fsa, vehicles = batch.daily_fsa_results(assigned, emissions, ["G1B", "UNKNOWN"], 2035, "bau", 1)
                links = batch.daily_link_results(emissions, {"L", "empty"}, 2035, "bau", 1)
                self.assertEqual(len(vehicles), 2)
                self.assertEqual(len(links), 2)
                self.assertTrue(vehicles[list(batch.CO2_COLUMNS)].eq(0).all().all())
                self.assertEqual(batch.validate_daily_results(fsa, vehicles, links)["total_co2_kg_per_day"], 0)

    def test_sample_standard_deviation_uses_per_seed_ratios(self):
        rows = []
        for seed, count, total in ((1, 1, 10.0), (2, 3, 60.0), (3, 0, 5.0)):
            rows.append({"year": 2035, "scenario": "bau", "seed": seed, "fsa": "G1B",
                "vehicle_count": 4, "ev_count": count, "active_ev_count": count,
                "total_co2_kg_per_day": total, "co2_kg_per_ev_per_day": total / count if count else np.nan,
                "total_electricity_kwh_per_day": count * 2,
                "electricity_kwh_per_ev_per_day": 2 if count else np.nan, "total_distance_km_per_day": 4})
        row = batch.aggregate_replicates(pd.DataFrame(rows)).iloc[0]
        self.assertEqual(row.seed_count, 3)
        self.assertEqual(row.co2_kg_per_ev_per_day_n_valid, 2)
        self.assertEqual(row.co2_kg_per_ev_per_day_mean, 15)
        self.assertAlmostEqual(row.co2_kg_per_ev_per_day_std, math.sqrt(50))
        self.assertEqual(row.total_distance_km_per_day_mean, 4)
        self.assertEqual(row.total_distance_km_per_day_std, 0)

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

    def summary_fixture(self):
        directory = self.root / "run"
        (directory / "emission").mkdir(parents=True)
        raw = directory / "emission/emission.events.offline.xml.gz"
        raw.write_bytes(b"temporary events retained until all summaries are saved")
        for name in ("assignments.parquet", "vehicles.xml.gz", "assignment_diagnostics.json", "emission_config.xml"):
            (directory / name).write_bytes(b"fixture dependency")
        assigned = batch.assign_frame(self.base(2), self.distribution(), 2035, "bau", 1, self.body_shares, self.ev)
        emissions = batch.EmissionSummary({"0": [1200, 300]}, {"L": [1200, 300]}, {"warmEmissionEvent": 1, "coldEmissionEvent": 1})
        return directory, raw, assigned, emissions

    def test_all_summary_tables_are_recorded_before_raw_cleanup(self):
        directory, raw, assigned, emissions = self.summary_fixture()
        options = batch.BatchOptions(output_dir=self.root)
        original_save = batch.save_stage

        def save_while_raw_exists(*args, **kwargs):
            self.assertTrue(raw.exists())
            return original_save(*args, **kwargs)

        with patch.object(batch, "save_stage", side_effect=save_while_raw_exists):
            batch.save_run_summary(options, directory, "key", assigned, emissions, {"L", "zero"}, ["G1B", "UNKNOWN"], 2035, "bau", 1)
        self.assertFalse(raw.exists())
        marker = directory / "summary.done.json"
        state = batch.completed_stage(marker, "key")
        self.assertIsNotNone(state)
        names = {Path(row["path"]).name for row in state["outputs"]}
        self.assertTrue({"vehicle_results.parquet", "link_results.parquet", "fsa_results.csv", "summary_diagnostics.json"} <= names)
        diagnostics = json.loads((directory / "summary_diagnostics.json").read_text())
        for name, rows in (("vehicle_results.parquet", 2), ("link_results.parquet", 2), ("fsa_results.csv", 2)):
            self.assertEqual(diagnostics["files"][name], {"row_count": rows, "size_bytes": (directory / name).stat().st_size})
        self.assertEqual(diagnostics["sample_expansion_factor"], 1)
        self.assertFalse(diagnostics["annualization"])
        self.assertEqual(diagnostics["total_distance_km_per_day"], 2)
        self.assertAlmostEqual(diagnostics["total_co2_kg_per_day"], 1.5)
        for name in ("link_results.parquet", "vehicle_results.parquet", "fsa_results.csv"):
            path = directory / name
            original = path.read_bytes()
            path.write_bytes(b"damaged")
            self.assertIsNone(batch.completed_stage(marker, "key"))
            path.write_bytes(original)
            # Update only the test marker to match restored files' new mtimes.
            batch.save_stage(marker, "key", [directory / item for item in sorted(names)])
        (directory / "link_results.parquet").unlink()
        self.assertIsNone(batch.completed_stage(marker, "key"))

    def test_failed_table_write_keeps_raw_events_and_does_not_mark_complete(self):
        directory, raw, assigned, emissions = self.summary_fixture()
        write = batch.write_frame

        def fail_link(path, frame):
            if path.name == "link_results.parquet":
                raise OSError("fixture disk full")
            write(path, frame)

        with patch.object(batch, "write_frame", side_effect=fail_link):
            with self.assertRaisesRegex(OSError, "disk full"):
                batch.save_run_summary(batch.BatchOptions(), directory, "key", assigned, emissions, {"L"}, ["G1B"], 2035, "bau", 1)
        self.assertTrue(raw.exists())
        self.assertFalse((directory / "summary.done.json").exists())

    def test_keep_events_and_failed_conservation_preserve_raw(self):
        directory, raw, assigned, emissions = self.summary_fixture()
        options = batch.BatchOptions(keep_emission_events=True)
        batch.save_run_summary(options, directory, "key", assigned, emissions, {"L"}, ["G1B"], 2035, "bau", 1)
        self.assertTrue(raw.exists())
        self.assertFalse(batch.completed_stage(directory / "summary.done.json", "key")["raw_events_cleaned"])
        (directory / "summary.done.json").unlink()
        emissions.link_grams["L"][0] += 1000
        with self.assertRaisesRegex(ValueError, "Vehicle/link"):
            batch.save_run_summary(options, directory, "key", assigned, emissions, {"L"}, ["G1B"], 2035, "bau", 1)
        self.assertTrue(raw.exists())
        self.assertFalse((directory / "summary.done.json").exists())

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

    def test_prediction_cache_tracks_fit_interval_module_and_scipy(self):
        options = batch.BatchOptions(output_dir=self.root)
        projection_name = "gompertz_projection.py"

        def manifest(module_hash="model-v1", scipy_version="1.13.1", fit_end=2040):
            def fake_identity(path):
                return {"path": str(path), "sha256": module_hash if path.name == projection_name else "unchanged"}

            with patch.object(Path, "is_file", return_value=True), patch.object(
                Path, "glob", return_value=iter([self.root / "G1B_projected_pop.csv"])
            ), patch.object(Path, "rglob", return_value=iter([])), patch.object(
                batch, "identity", side_effect=fake_identity
            ), patch.object(batch.importlib.metadata, "version", side_effect=lambda name: scipy_version if name == "scipy" else "unchanged"), patch.object(
                batch, "GOMPERTZ_FIT_END_YEAR", fit_end
            ):
                return batch.input_manifest(options)

        original = manifest()
        self.assertEqual(original["schema_version"], 2)
        self.assertEqual(original["emission_aggregation"]["link_rows"], "full_network")
        self.assertEqual(original["prediction_model"], "all_prediction_gompertz")
        self.assertTrue(any(Path(row["path"]).name == projection_name for row in original["inputs"]))
        for changed in (manifest(module_hash="model-v2"), manifest(scipy_version="changed"), manifest(fit_end=2050)):
            self.assertNotEqual(batch.fingerprint(original), batch.fingerprint(changed))

    def test_batch_audit_checks_actual_fit_years_and_scenario_model(self):
        initial = {"electric": .03, "ice_sedan": .4, "ice_suv": .5, "hev_sedan": .07}
        trends = {"electric": .25, "ice_sedan": .01, "ice_suv": .02, "hev_sedan": .03}
        for scenario in ("bau", "acc_adopt", "del_adopt", "pol_align"):
            with self.subTest(scenario=scenario):
                prediction = composition.predict_composition_trend(initial, trends, end_year=2041, scenario=scenario)
                audit = batch.validate_prediction_audit(prediction, scenario)
                self.assertEqual(audit["baseline_fit"]["fit_years"], tuple(range(2021, 2041)))
                damaged = prediction.copy()
                damaged.attrs = deepcopy(prediction.attrs)
                damaged.attrs["gompertz"]["baseline_fit"]["fit_years"] = (2035,)
                with self.assertRaisesRegex(ValueError, "All-prediction"):
                    batch.validate_prediction_audit(damaged, scenario)
                if scenario in ("acc_adopt", "del_adopt"):
                    self.assertEqual(audit["scenario_fit"]["fit_years"], tuple(range(2025, 2041)))
                    damaged.attrs = deepcopy(prediction.attrs)
                    damaged.attrs["gompertz"]["scenario_factor"] = 1
                    with self.assertRaisesRegex(ValueError, "scaled 2025-2040"):
                        batch.validate_prediction_audit(damaged, scenario)
        with self.assertRaisesRegex(ValueError, "All-prediction"):
            batch.validate_prediction_audit(pd.DataFrame(), "bau")

    def test_q0q_latest_all_prediction_reference_values(self):
        # Aggregated Q0Q inputs from the 2026-10-28 model comparison; no raw SAAQ dependency.
        initial = dict(zip(batch.CATEGORIES, [0.03146884742240094, 0.017643338002078346, 0.025866353408936883,
                                            0.2776623141914788, 0.5265892558622871, 0.12076989111281797]))
        trends = dict(zip(batch.CATEGORIES, [0.920700542305875, 0.16091458341124212, 0.3708773794658104,
                                           -0.026202607002655524, 0.0677301410594064, -0.006932667569830103]))
        predictions = {}
        for scenario, expected in (("bau", .81337), ("acc_adopt", .97630), ("del_adopt", .54254)):
            prediction = composition.predict_composition_trend(initial, trends, end_year=2041, scenario=scenario)
            batch.validate_prediction_audit(prediction, scenario)
            self.assertAlmostEqual(prediction.loc["electric", 2035], expected, delta=1e-5)
            predictions[scenario] = prediction
        for scenario in ("acc_adopt", "del_adopt"):
            pd.testing.assert_frame_equal(predictions[scenario].loc[:, :2024], predictions["bau"].loc[:, :2024])

    def test_distribution_diagnostics_store_fits_and_fallbacks(self):
        cache, population = self.root / "cache", self.root / "population"
        cache.mkdir()
        population.mkdir()
        pd.DataFrame({"year": [2020], "persons": [1000]}).to_csv(population / "G1B_projected_pop.csv", index=False)
        history = pd.DataFrame([( "G1B", year, kind, count, entrants)
            for year in range(2013, 2021) for kind, count, entrants in (("electric", 3, 1), ("ice_sedan", 7, 9))],
            columns=["fsa", "year", "vehicle_type", "fleet_count", "entrant_count"])
        raw = pd.DataFrame({"fsa": ["G1B"] * 8, "year": range(2013, 2021), "size": [10] * 8, "new": [10] * 8, "exit": [1] * 8})
        options = batch.BatchOptions(population_dir=population)
        base = self.base(2)
        base["fsa"] = ["G1B", "G1C"]
        controls = pd.DataFrame({"new": 1, "implied_exit": 1}, index=range(2021, 2041))
        stock = pd.DataFrame({2035: {"electric": 6, "ice_sedan": 4}})
        with patch.object(batch, "PC_QC", ["G1B"]), patch.object(batch, "aggregate_history", return_value=(history, raw)), patch.object(
            core, "read_vehicle_distribution", return_value={"G1B": {"electric": .3, "ice_sedan": .7}}
        ), patch.object(composition, "get_growth_trends", return_value={"electric": .25, "ice_sedan": .01}), patch.object(
            batch, "project_fleet_controls", return_value=controls
        ), patch.object(growth, "predict_fleet_over_time", return_value=stock):
            result = batch.build_distributions(options, base, cache, "key")
        diagnostics = json.loads((cache / "prediction_diagnostics.json").read_text())
        self.assertEqual(len(diagnostics["fits"]), 4)
        self.assertEqual({row["scenario"] for row in diagnostics["fits"]}, {"bau", "acc_adopt", "del_adopt", "pol_align"})
        self.assertTrue(all(row["fsa"] == "G1B" for row in diagnostics["fits"]))
        self.assertEqual(diagnostics["fits"][0]["baseline_fit"]["fit_years"], list(range(2021, 2041)))
        self.assertTrue(any(row["fsa"] == "G1C" for row in diagnostics["fallbacks"]))
        self.assertIn("G1C", result["2035_bau"]["fallback_reasons"])

    def test_fifty_run_workflow_and_resume_after_link_file_damage(self):
        # Synthetic pipeline only: both Maven compilation and Java are mocked.
        options = batch.BatchOptions(output_dir=self.root / "batch", emission_module=self.root / "module")
        base = self.base(2)
        base.loc[1, "distance_metres_per_day"] = 0
        shares = batch.checked_shares({"ice_sedan": 1})
        distributions = {scenario: {"shares": {"G1B": shares}, "city_average": shares, "fallback_reasons": {}}
                         for scenario in batch.SCENARIOS}
        ev = types.SimpleNamespace(read_link_lengths=lambda path: {"L": 1000, "empty": 500},
            read_historical_shares=lambda *args: self.body_shares, assign_vehicle_type=self.ev.assign_vehicle_type,
            KWH_PER_KM_BY_TYPE=self.ev.KWH_PER_KM_BY_TYPE)

        def compile_fixture(command, *args, **kwargs):
            main = options.emission_module / "target/classes/org/matsim/contrib/emissions/example/RunAverageEmissionToolOfflineExample.class"
            main.parent.mkdir(parents=True, exist_ok=True)
            main.write_bytes(b"mocked class")

        def config_fixture(opts, directory, assigned, seed):
            path = directory / "emission_config.xml"
            path.write_text("<config/>")
            return path

        def emission_fixture(opts, config, log):
            with gzip.open(config.parent / "emission/emission.events.offline.xml.gz", "wt") as stream:
                stream.write('<events><event type="warmEmissionEvent" vehicleId="0" linkId="L" CO2="1200"/>'
                             '<event type="coldEmissionEvent" vehicle="0" link="L" CO2="300"/></events>')

        with patch.object(batch, "input_manifest", return_value={"schema_version": 2}), patch.object(
            core, "load_script_module", return_value=ev
        ), patch.object(batch, "prepare_mobility", return_value=(base, set())), patch.object(
            batch, "build_distributions", return_value=distributions
        ), patch.object(batch, "write_assigned_vehicles", side_effect=lambda source, target, frame: target.write_bytes(b"mocked vehicles")), patch.object(
            batch, "maven_command", return_value="mvn"
        ), patch.object(batch, "run_logged", side_effect=compile_fixture) as compile_run, patch.object(
            batch, "write_emission_config", side_effect=config_fixture
        ), patch.object(batch, "run_emission", side_effect=emission_fixture) as emission_run:
            batch.run_batch(options)
            self.assertEqual(emission_run.call_count, 50)
            self.assertEqual(compile_run.call_count, 1)
            statistics = pd.read_csv(options.output_dir / "fsa_results_seed_statistics.csv")
            self.assertTrue(statistics.seed_count.eq(10).all())
            totals = pd.read_csv(options.output_dir / "all_fsa_totals_by_seed.csv")
            self.assertEqual(len(totals), 50)
            self.assertTrue(totals.total_distance_km_per_day.eq(1).all())
            status = json.loads((options.output_dir / "batch_status.json").read_text())
            self.assertEqual(status["state"], "complete")
            self.assertEqual(len(status["completed"]), 50)
            self.assertFalse(list(options.output_dir.glob("*/seed*/emission/emission.events.offline.xml.gz")))
            batch.run_batch(options)
            self.assertEqual(emission_run.call_count, 50)
            directory = options.output_dir / "2020_REF/seed1"
            (directory / "link_results.parquet").write_bytes(b"corrupted parquet")
            batch.run_batch(options)
            self.assertEqual(emission_run.call_count, 51)
            self.assertEqual(compile_run.call_count, 1)
            self.assertIsNotNone(batch.completed_stage(directory / "summary.done.json",
                batch.fingerprint({"inputs": batch.fingerprint({"schema_version": 2}), "scenario": "2020_REF", "seed": 1})))

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
        self.root = self.root / "Research Data, scenario's run"
        self.root.mkdir()
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
        source.write_text(f'''<vehicleDefinitions xmlns="http://www.matsim.org/files/dtd"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://www.matsim.org/files/dtd http://www.matsim.org/files/dtd/vehicleDefinitions_v2.0.xsd">
          {BUS_TYPE_XML}<vehicle id="0" type="defaultVehicleType"/><vehicle id="veh_0_bus" type="Bus"/>
          </vehicleDefinitions>''')
        distribution = {"shares": {"G1B": batch.checked_shares({"ice_sedan": 1})}, "city_average": batch.checked_shares({"ice_sedan": 1})}
        assigned = batch.assign_frame(self.base(1), distribution, 2035, "bau", 1, self.body_shares, self.ev)
        vehicle_path = self.root / "vehicles.xml.gz"
        batch.write_assigned_vehicles(source, vehicle_path, assigned)
        config = batch.write_emission_config(options, self.root, vehicle_path, 1)
        (self.root / "emission").mkdir()
        batch.run_logged([batch.maven_command(), "-q", "-DskipTests", "compile"], options, self.root / "build.log")
        batch.run_emission(options, config, self.root / "run.log")
        emissions = batch.summarize_emissions(self.root / "emission/emission.events.offline.xml.gz", {"0"}, {"veh_0_bus"}, {"L1", "L2"})
        self.assertGreater(sum(emissions.vehicle_grams.get("0", [])), 0)
        result, vehicles = batch.daily_fsa_results(assigned, emissions, ["G1B", "UNKNOWN"], 2035, "bau", 1)
        links = batch.daily_link_results(emissions, {"L1", "L2"}, 2035, "bau", 1)
        batch.validate_daily_results(result, vehicles, links)
        self.assertAlmostEqual(result.total_co2_kg_per_day.sum(), sum(emissions.vehicle_grams["0"]) / 1000)


if __name__ == "__main__":
    unittest.main()
