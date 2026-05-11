"""
Used to filter only personal vehicles from SAAQ data and save it to
separate file to minimize data size.
"""

import pandas as pd
import _setup_path  # pylint: disable=unused-import
from matsim_vehicle_type.config import DATA_DIR

fleet_path = DATA_DIR / "vehicles" / "ownership"
output_path = fleet_path / "personal_ownership"


dtype_map = {
    "MOD": "string",
    "CYL2": "string",
    "CARB": "string",
    "Motorisation": "string",
    "Genre": "string",
    "Hybrid Type": "string",
    "Propulsion": "string",
}
columns_to_drop = [
    "CYL2",
    "TYUTILN",
    "TYUTILR",
    "TYLIEU",
    "TYVEH",
    "MUNI",
    "Region",
    "RMR",
    "Engine Size",
    "Propulsion",
    "Transmission",
    "TCPP",
    "Autonomie",
]

for i in range(13, 21):
    filename = f"McGill_SAAQ_20{i}_2024-01-10.csv"
    filepath = fleet_path / filename
    print(f"running {filename}.")
    df = pd.read_csv(filepath, sep=";", decimal=",", encoding="utf-16", dtype=dtype_map)
    df = df.loc[df["Usage"] == "Personnel"]
    # df = df.loc[df["RTA"].isin(PC_QC)]
    df.drop(columns=columns_to_drop, inplace=True)
    df.to_csv(
        output_path / f"Personal_McGill_SAAQ_20{i}_2024-01-10.csv",
        index=False,
        decimal=".",
    )
    print(f"{filename} saved.")
