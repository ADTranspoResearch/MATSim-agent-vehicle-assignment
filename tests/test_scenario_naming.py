"""Exercise renamed scenarios across assignment, discovery and emissions."""

import hashlib
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from platform_gui import core, whatif


class ScenarioNamingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for directory in ("predicted", "historical", "population", "output", "events"):
            (self.root / directory).mkdir()
        for scenario in ("bau", "acc_adopt", "del_adopt", "pol_align"):
            (self.root / "predicted" / f"fsa_vehicle_share_2035_{scenario}.csv").write_text(
                "fsa,electric,ice_sedan\nG1B,0.25,0.75\n", encoding="utf-8"
            )
        (self.root / "historical" / "fsa_vehicle_share_2020.csv").write_text(
            "fsa,electric,ice_sedan\nG1B,0.01,0.99\n", encoding="utf-8"
        )
        (self.root / "people.xml").write_text('<population><person id="1"/></population>')
        (self.root / "vehicles.xml").write_text(
            '<vehicleDefinitions><vehicle id="1" type="car"/></vehicleDefinitions>'
        )
        (self.root / "transit.xml").write_text('<vehicleDefinitions/>')
        (self.root / "lookup.csv").write_text('agent_id,fsa\n1,G1B\n')
        (self.root / "template.xml").write_text('<config/>')
        self.config = {
            "predicted_vehicle_share_dir": str(self.root / "predicted"),
            "historical_vehicle_share_dir": str(self.root / "historical"),
            "fsa_projected_pop_dir": str(self.root / "population"),
            "population_file": str(self.root / "people.xml"),
            "vehicle_file": str(self.root / "vehicles.xml"),
            "transit_vehicle_file": str(self.root / "transit.xml"),
            "fsa_lookup_file": str(self.root / "lookup.csv"),
            "output_dir": str(self.root / "output"),
            "emission_config_template": str(self.root / "template.xml"),
            "emission_config_dir": str(self.root / "configs"),
            "emission_events_dir": str(self.root / "events"),
            "emission_events_file": str(self.root / "fallback.xml.gz"),
            "emission_module_dir": str(self.root / "module"),
            "network_file": str(self.root / "network.xml"),
        }

    def test_scenarios_flow_through_assignment_and_emission_config(self):
        options = core.list_vehicle_options(self.config)
        self.assertEqual(
            set(options["predicted_scenarios"]["2035"]),
            {"bau", "acc_adopt", "del_adopt", "pol_align", core.CUSTOM_ADOPTION_SCENARIO},
        )
        engine = object.__new__(whatif.WhatIfEngine)
        engine.config = self.config
        self.assertTrue(
            {"2035_bau", "2035_acc_adopt", "2035_del_adopt", "2035_pol_align"}
            <= {item["key"] for item in engine._scenario_keys()}
        )
        expected_names = set()
        for scenario in ("bau", "acc_adopt", "del_adopt", "pol_align"):
            with self.subTest(scenario=scenario):
                result = core.assign_vehicle_types(self.config, 2035, "predicted", scenario, 1)
                expected_name = f"vehicles_2035_{scenario}_seed1.xml"
                expected_names.add(expected_name)
                self.assertEqual(result.output_file.name, expected_name)
                self.assertEqual(result.assigned_count, 1)
                self.assertTrue(result.output_file.is_file())
                config_path, events_path = core.create_emission_run_config(
                    self.config, 2035, scenario, str(result.output_file)
                )
                self.assertEqual(config_path.name, f"config_average_2035_{scenario}.xml")
                vehicle_param = ET.parse(config_path).find(
                    './module[@name="vehicles"]/param[@name="vehiclesFile"]'
                )
                self.assertEqual(Path(vehicle_param.get("value")), result.output_file)
                flat_events = self.root / "events" / f"emission.events.offline.2035.{scenario}.xml.gz"
                flat_events.touch()
                self.assertEqual(core.emission_events_for_scenario(self.config, 2035, scenario), flat_events)
                events_path.touch()
                self.assertEqual(core.emission_events_for_scenario(self.config, 2035, scenario), events_path)
        self.assertEqual(
            {item["name"] for item in core.list_assignment_vehicle_files(self.config)}, expected_names
        )

    def test_renamed_scenarios_preserve_ev_body_type_draws(self):
        module = core.load_script_module(
            "test_ev_scenario_naming",
            core.PROJECT_ROOT / "data_post-processing" / "summarize_ev_electricity_by_scenario.py",
        )
        shares = {"Passenger cars": 0.5, "Multi-purpose vehicles": 0.3, "Pickup trucks and vans": 0.2}
        for scenario, original in (
            ("bau", "BAU"),
            ("acc_adopt", "ACCELERATED_ADOPTION"),
            ("del_adopt", "DELAYED_ADOPTION"),
            ("pol_align", "POLICY_ALIGNED"),
        ):
            for agent in map(str, range(100)):
                digest = hashlib.sha256(f"{original}:{agent}".encode("utf-8")).digest()
                draw = int.from_bytes(digest[:8], "big") / 2**64
                expected = "Passenger cars" if draw <= 0.5 else "Multi-purpose vehicles" if draw <= 0.8 else "Pickup trucks and vans"
                self.assertEqual(module.assign_vehicle_type(agent, scenario, shares), expected)


if __name__ == "__main__":
    unittest.main()
