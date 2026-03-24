
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

# Modify these variables to alter how the module functions.
SEED = 2
# Scenario Data.
SCN_YEAR = 2018
# Possible case options =
# REF : Reference scenario (only when using historical vehicle data)
# BAU : buisness as usual,
# EVAS : Electric vehicle availability standard,
# C : Carney scenario
SCN_CASE = "REF"

POP_NAME = "quebec_population.xml.gz"
VEH_NAME = "output_allVehicles.xml.gz"




DATA_DIR = ROOT / "data"
POP_DIR = DATA_DIR / "MATSim" / "population"
VEH_DIR = DATA_DIR / "MATSim" / "vehicles"



POP_FILE = POP_DIR / POP_NAME

VEH_FILE = VEH_DIR / VEH_NAME


OUTPUT_DIR = ROOT / "output"
