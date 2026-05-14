"""
Contains configuration parameters that can be adjusted for each run.

Also contains useful imports that other modules can leverage.
"""

from pathlib import Path
import csv

ROOT = Path(__file__).resolve().parents[1]

# Modify these variables to alter how the module functions.
SEED = 2
# Scenario Data.
SCN_YEAR = 2040
# Possible case options =
# REF : Reference scenario (only when using historical vehicle data)
# BAU : buisness as usual,
# EVAS : Electric vehicle availability standard,
# C : Carney scenario
SCN_CASE = "pred"


POP_NAME = "quebec_population.xml.gz"
VEH_NAME = "output_allVehicles.xml.gz"


# Useful directories that can be imported directly.
DATA_DIR = ROOT / "data"
POP_DIR = DATA_DIR / "MATSim" / "population"
VEH_DIR = DATA_DIR / "MATSim" / "vehicles"
POP_FILE = POP_DIR / POP_NAME
VEH_FILE = VEH_DIR / VEH_NAME
OUTPUT_DIR = ROOT / "output"


with open(DATA_DIR / "FSA" / "fsa_codes_of_interest.csv", newline="") as f:
    reader = csv.reader(f)
    PC_QC_list = [row[0] for row in reader]
    PC_QC = set(PC_QC_list)
