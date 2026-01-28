"""
Module takes population file and assigns a vehicle class based on
indicated vehicle ownership data.
"""

import gzip
import xml.etree.ElementTree as ET

from population import get_home
from vehicle_assignment import get_veh_from_xy

# Modify these variables to alter how the module functions.
SEED = 1
POP_FILEPATH = "MATSim/population/" + "Siouxfalls_population.xml.gz"
# Replace when vehicle data is available.
VEHICLE_FILEPATH = "vehicle_data" + "vehicle_ownership.csv"

with gzip.open(POP_FILEPATH, "rt", encoding="utf-8") as f:
    tree = ET.parse(f)

root = tree.getroot()

# Iterate over every agent in population, get home coordinates, get
# vehicle assigned to agent based on location, add it as a attribute
# to the XML file.
for person in root.findall(".//person"):
    home_xy = get_home(person)
    vehicle = get_veh_from_xy(home_xy, SEED)
    person.set("vehicle", str(vehicle))

# Save the modified XML file.

tree.write("output/modified_population.xml", encoding="utf-8", xml_declaration=True)