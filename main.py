"""
Module takes population file and assigns a vehicle class based on
indicated vehicle ownership data.
"""

import gzip
import xml.etree.ElementTree as ET

from population import get_home, get_demos, get_fsa_table
from vehicle_assignment import get_veh_from_fsa

# Modify these variables to alter how the module functions.
SEED = 1
POP_FILEPATH = "MATSim/population/" + "Siouxfalls_population.xml.gz"
# Replace when vehicle data is available.
VEHICLE_FILEPATH = "vehicle_data/" +"ownership" + "McGill_SAAQ_2013_2024-01-10.csv"

with gzip.open(POP_FILEPATH, "rt", encoding="utf-8") as f:
    tree = ET.parse(f)

root = tree.getroot()

# Initialize the FSA table, if not constructed will be constructed now.
fsa_table = get_fsa_table(root)

# Iterate over every agent in population, get home coordinates, get
# vehicle assigned to agent based on location, add it as a attribute
# to the XML file.
for person in root.findall(".//person"):
    home_xy = get_home(person)
    demographics = get_demos(person)
    fsa = fsa_table.loc[person.get("id")][0]
    vehicle = get_veh_from_fsa(demographics, fsa, SEED)
    person.set("vehicle", str(vehicle))

# Save the modified XML file.

tree.write("output/modified_population.xml", encoding="utf-8", xml_declaration=True)
