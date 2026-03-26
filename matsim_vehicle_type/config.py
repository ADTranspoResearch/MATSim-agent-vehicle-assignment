
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

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

POP_NAME = "quebec_population.xml.gz"
VEH_NAME = "output_allVehicles.xml.gz"




DATA_DIR = ROOT / "data"
MATSIM_DIR = DATA_DIR / "MATSim"
POP_DIR = MATSIM_DIR / "population"
VEH_DIR = MATSIM_DIR / "vehicles"



POP_FILE = POP_DIR / POP_NAME

VEH_FILE = VEH_DIR / VEH_NAME


OUTPUT_DIR = ROOT / "output"
