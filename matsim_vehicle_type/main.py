"""
Module takes population file and assigns a vehicle class based on
indicated vehicle ownership data.
"""

import gzip
import xml.etree.ElementTree as ET
import random

from matsim_vehicle_type.population.population import get_fsa_table
from matsim_vehicle_type.vehicles.vehicle_assignment import (
    get_veh_from_fsa,
    load_veh_dist,
)
from matsim_vehicle_type.config import (
    SEED,
    SCN_CASE,
    SCN_YEAR,
    POP_FILE,
    VEH_FILE,
    OUTPUT_DIR,
)
VEHICLE_TYPE_ALIAS = {
    "ice_van/pickup": "truck",
    "hev_van/pickup": "truck",
    "unknown": "defaultVehicleType",
    "other": "defaultVehicleType",
}

VEHICLE_TYPE_XML = """
<vehicleTypes xmlns="http://www.matsim.org/files/dtd">
	<vehicleType id="Bus">
		<length meter="18.0"/>
		<width meter="2.5"/>
		<engineInformation>
			<attributes>
				<attribute name="HbefaVehicleCategory" class="java.lang.String">Bus</attribute>
				<attribute name="HbefaTechnology" class="java.lang.String">average</attribute>
				<attribute name="HbefaSizeClass" class="java.lang.String">average</attribute>
				<attribute name="HbefaEmissionsConcept" class="java.lang.String">average</attribute>
			</attributes>
		</engineInformation>

		<networkMode networkMode="bus"/>
	</vehicleType>


   	<vehicleType id="ice_sedan">
		<length meter="7.5"/>
		<width meter="1.0"/>
		<engineInformation>
			<attributes>
				<attribute name="HbefaVehicleCategory" class="java.lang.String">ice_sedan</attribute>
				<attribute name="HbefaTechnology" class="java.lang.String">average</attribute>
				<attribute name="HbefaSizeClass" class="java.lang.String">average</attribute>
				<attribute name="HbefaEmissionsConcept" class="java.lang.String">average</attribute>
			</attributes>
		</engineInformation>
		<networkMode networkMode="car"/>
	</vehicleType>

	<vehicleType id="ice_suv">
		<length meter="7.5"/>
		<width meter="1.0"/>
		<engineInformation>
			<attributes>
				<attribute name="HbefaVehicleCategory" class="java.lang.String">ice_suv</attribute>
				<attribute name="HbefaTechnology" class="java.lang.String">average</attribute>
				<attribute name="HbefaSizeClass" class="java.lang.String">average</attribute>
				<attribute name="HbefaEmissionsConcept" class="java.lang.String">average</attribute>
			</attributes>
		</engineInformation>
		<networkMode networkMode="car"/>
	</vehicleType>

	<vehicleType id="hev_sedan">
		<length meter="7.5"/>
		<width meter="1.0"/>
		<engineInformation>
			<attributes>
				<attribute name="HbefaVehicleCategory" class="java.lang.String">hev_sedan</attribute>
				<attribute name="HbefaTechnology" class="java.lang.String">average</attribute>
				<attribute name="HbefaSizeClass" class="java.lang.String">average</attribute>
				<attribute name="HbefaEmissionsConcept" class="java.lang.String">average</attribute>
			</attributes>
		</engineInformation>
		<networkMode networkMode="car"/>
	</vehicleType>

	<vehicleType id="hev_suv">
		<length meter="7.5"/>
		<width meter="1.0"/>
		<engineInformation>
			<attributes>
				<attribute name="HbefaVehicleCategory" class="java.lang.String">hev_suv</attribute>
				<attribute name="HbefaTechnology" class="java.lang.String">average</attribute>
				<attribute name="HbefaSizeClass" class="java.lang.String">average</attribute>
				<attribute name="HbefaEmissionsConcept" class="java.lang.String">average</attribute>
			</attributes>
		</engineInformation>
		<networkMode networkMode="car"/>
	</vehicleType>

	<vehicleType id="truck">
		<length meter="7.5"/>
		<width meter="1.0"/>
		<engineInformation>
			<attributes>
				<attribute name="HbefaVehicleCategory" class="java.lang.String">truck</attribute>
				<attribute name="HbefaTechnology" class="java.lang.String">average</attribute>
				<attribute name="HbefaSizeClass" class="java.lang.String">average</attribute>
				<attribute name="HbefaEmissionsConcept" class="java.lang.String">average</attribute>
			</attributes>
		</engineInformation>
		<networkMode networkMode="car"/>
	</vehicleType>

	<vehicleType id="electric">
		<length meter="7.5"/>
		<width meter="1.0"/>
		<engineInformation>
			<attributes>
				<attribute name="HbefaVehicleCategory" class="java.lang.String">electric</attribute>
				<attribute name="HbefaTechnology" class="java.lang.String">average</attribute>
				<attribute name="HbefaSizeClass" class="java.lang.String">average</attribute>
				<attribute name="HbefaEmissionsConcept" class="java.lang.String">average</attribute>
			</attributes>
		</engineInformation>
		<networkMode networkMode="car"/>
	</vehicleType>

	<vehicleType id="defaultVehicleType">
		<length meter="7.5"/>
		<width meter="1.0"/>
		<engineInformation>
			<attributes>
				<attribute name="HbefaVehicleCategory" class="java.lang.String">defaultVehicleType</attribute>
				<attribute name="HbefaTechnology" class="java.lang.String">average</attribute>
				<attribute name="HbefaSizeClass" class="java.lang.String">average</attribute>
				<attribute name="HbefaEmissionsConcept" class="java.lang.String">average</attribute>
			</attributes>
		</engineInformation>
		<networkMode networkMode="car"/>
	</vehicleType>
</vehicleTypes>
"""

def replace_vehicle_type_definitions(root):
    new_root = ET.fromstring(VEHICLE_TYPE_XML)
    new_types = list(new_root)
    new_type_ids = {vehicle_type.get("id") for vehicle_type in new_types}

    for child in list(root):
        if child.tag.endswith("vehicleType") and child.get("id") in new_type_ids:
            root.remove(child)

    children = list(root)
    insert_at = next(
        (i for i, child in enumerate(children) if child.tag.endswith("vehicle")),
        len(children),
    )

    for vehicle_type in new_types:
        root.insert(insert_at, vehicle_type)
        insert_at += 1


def assign_matsim_users_vehicle_type(scenario_year=SCN_YEAR, scenario_type="historical"):
    random.seed(SEED)

    with gzip.open(POP_FILE, "rt", encoding="utf-8") as f:
        tree = ET.parse(f)
    root = tree.getroot()

    # Initialize the FSA table, if not constructed will be constructed now.
    load_veh_dist(scenario_year, scenario_type)
    fsa_table = get_fsa_table(root)

    # Iterate over every agent in population, get home coordinates, get
    # vehicle assigned to agent based on location, add it as a attribute
    # to the XML file.
    person_vehicle_dict = {}
    for person in root.findall(".//person"):
        pid = person.get("id")
        fsa = fsa_table.loc[pid].values[0]
        vehicle_type = get_veh_from_fsa(fsa)
        vehicle_type = VEHICLE_TYPE_ALIAS.get(vehicle_type, vehicle_type)
        person_vehicle_dict[pid] = vehicle_type

    # Save the modified XML file.

    with gzip.open(VEH_FILE, "rt", encoding="utf-8") as f:
        tree = ET.parse(f)
    root = tree.getroot()
    replace_vehicle_type_definitions(root)
    agent_id_list = person_vehicle_dict.keys()
    for child in root:
        if child.tag.endswith("vehicle"):
            vid = child.get("id")
            if vid in agent_id_list:
                child.set("type", person_vehicle_dict[vid])

    ET.register_namespace("", "http://www.matsim.org/files/dtd")
    tree = ET.ElementTree(root)
    output_path = OUTPUT_DIR / f"vehicles_updated_{SCN_YEAR}_{SCN_CASE}.xml"
    tree.write(
        output_path,
        encoding="utf-8",
        xml_declaration=True,
    )

if __name__ == "__main__":
    assign_matsim_users_vehicle_type()