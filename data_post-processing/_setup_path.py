"""
Module should be imported in the first line of every script to have the
proper path to import the necessary modules from matsim_vehicle_type.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))
