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

def main():
    random.seed(SEED)

    with gzip.open(POP_FILE, "rt", encoding="utf-8") as f:
        tree = ET.parse(f)
    root = tree.getroot()

    # Initialize the FSA table, if not constructed will be constructed now.
    load_veh_dist(SCN_YEAR)
    fsa_table = get_fsa_table(root)

    # Iterate over every agent in population, get home coordinates, get
    # vehicle assigned to agent based on location, add it as a attribute
    # to the XML file.
    person_vehicle_dict = {}
    for person in root.findall(".//person"):
        pid = person.get("id")
        fsa = fsa_table.loc[pid].values[0]
        vehicle_type = get_veh_from_fsa(fsa)
        person_vehicle_dict[pid] = vehicle_type

    # Save the modified XML file.

    with gzip.open(VEH_FILE, "rt", encoding="utf-8") as f:
        tree = ET.parse(f)
    root = tree.getroot()

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
    main()