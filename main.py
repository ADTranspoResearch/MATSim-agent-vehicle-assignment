"""
Module takes population file and assigns a vehicle class based on
indicated vehicle ownership data.
"""

import gzip
import xml.etree.ElementTree as ET
import random

from population import get_home, get_fsa_table
from vehicle_assignment import get_veh_from_fsa, load_veh_dist

# Modify these variables to alter how the module functions.
SEED = 2
# Scenario Data.
SCN_YEAR = 2021
# Possible case options =
# REF : Reference scenario (only when using historical vehicle data)
# BAU : buisness as usual,
# EVAS : Electric vehicle availability standard,
# C : Carney scenario
SCN_CASE = "BAU"

POP_FILEPATH = "MATSim/population/" + "quebec_population.xml.gz"
# Replace when vehicle data is available.

VEHICLE_DEFINITION_PATH = "MATSim/vehicles/" + "output_allVehicles.xml.gz"


random.seed(SEED)

with gzip.open(POP_FILEPATH, "rt", encoding="utf-8") as f:
    tree = ET.parse(f)
root = tree.getroot()
with gzip.open(VEHICLE_DEFINITION_PATH, "rt", encoding="utf-8") as f:
    veh_tree = ET.parse(f)
veh_root = veh_tree.getroot()


# Initialize the FSA table, if not constructed will be constructed now.
load_veh_dist(SCN_YEAR)
fsa_table = get_fsa_table(root)

# Iterate over every agent in population, get home coordinates, get
# vehicle assigned to agent based on location, add it as a attribute
# to the XML file.
person_vehicle_dict = {}
for person in root.findall(".//person"):
    home_xy = get_home(person)
    pid = person.get("id")
    fsa = fsa_table.loc[pid].values[0]
    vehicle_type = get_veh_from_fsa(fsa)
    person_vehicle_dict[pid] = vehicle_type

# Save the modified XML file.

with gzip.open(VEHICLE_DEFINITION_PATH, "rt", encoding="utf-8") as f:
    tree = ET.parse(f)
root = tree.getroot()

for child in root:
    if child.tag.endswith("vehicle"):
        vid = child.get("id")
        if vid in person_vehicle_dict.keys():
            child.set("type", person_vehicle_dict[vid])


tree = ET.ElementTree(root)
tree.write(
    f"output/vehicles_updated_{SCN_YEAR}_{SCN_CASE}.xml",
    encoding="utf-8",
    xml_declaration=True,
)
