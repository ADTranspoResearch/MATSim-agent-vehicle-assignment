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
SCN_YEAR = 2035
# Possible case options =
# REF : Reference scenario (only when using historical vehicle data)
# BAU : buisness as usual,
# EVAS : Electric vehicle availability standard,
# C : Carney scenario
SCN_CASE = "ACCELERATED_ADOPTION"
SCN_CONFIGS = {
    "BAU":{
        "type": "none",
        "file_prefix": "bau"
    },
    "25_LOWER": {
        "type": "scale",
        "factor": 0.75,  
        "file_prefix": "25lower"
    },
    "25_HIGHER": {
        "type": "scale",
        "factor": 1.25,
        "file_prefix": "25higher"
    },
    "QC_HIGH_TARGET": {
        "type": "target",
        "targets": {
            2025: 0.22, 2026: 0.325, 2027: 0.45, 2028: 0.60, 2029: 0.75,
            2030: 0.85, 2031: 0.91, 2032: 0.95, 2033: 0.975, 2034: 0.99, 2035: 1.00
        },
        "file_prefix": "target"
    },
    "POLICY_ALIGNED": {
        "type": "target",
        "targets": {
            2025: 0.22, 2026: 0.26, 2027: 0.3, 2028: 0.35, 2029: 0.44,
            2030: 0.52, 2031: 0.58, 2032: 0.64, 2033: 0.7, 2034: 0.75, 2035: 0.8
        },
        "file_prefix": "target"
    },
    "ACCELERATED_ADOPTION": {
        "type": "ev_logit_scaled_target",
        "anchor_year": 2024,
        "target_year": 2035,
        "factor": 1.25,
        "ceiling": 1.0,
        "file_prefix": "ev2035_25higher",
    },
    "DELAYED_ADOPTION": {
        "type": "ev_logit_scaled_target",
        "anchor_year": 2024,
        "target_year": 2035,
        "factor": 0.75,
        "ceiling": 1.0,
        "file_prefix": "ev2035_25lower",
    }
}


POP_NAME = "population.xml.gz"
VEH_NAME = "output_vehicles.xml.gz"


# Useful directories that can be imported directly.
DATA_DIR = ROOT / "data"
POP_DIR = DATA_DIR / "MATSim" / "population"
VEH_DIR = DATA_DIR / "MATSim" / "vehicles"
POP_FILE = POP_DIR / POP_NAME
VEH_FILE = VEH_DIR / VEH_NAME
OUTPUT_DIR = ROOT / "output"

DTYPE_MAP = {
    "MOD": "string",
    "CYL2": "string",
    "CARB": "string",
    "Motorisation": "string",
    "Genre": "string",
    "Hybrid Type": "string",
    "Propulsion": "string",
}


with open(DATA_DIR / "FSA" / "fsa_codes_of_interest.csv", newline="") as f:
    reader = csv.reader(f)
    PC_QC_list = [row[0] for row in reader]
    PC_QC = set(PC_QC_list)

with open(DATA_DIR / "FSA" / "qcp_fsalist.csv", newline="") as f:
    reader = csv.reader(f)
    PC_QCP_list = [row[0] for row in reader]
    PC_QCP = set(PC_QCP_list)