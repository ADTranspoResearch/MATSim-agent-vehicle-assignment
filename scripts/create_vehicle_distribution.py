import _setup_path #pylint: disable=unused-import
from matsim_vehicle_type.config import SCN_YEAR, DATA_DIR
from matsim_vehicle_type.vehicles.vehicle_distribution import build_vehicle_distribution

year = SCN_YEAR
year = 2020
filename = f"McGill_SAAQ_{year}_2024-01-10.csv"
ownership_path = DATA_DIR / "vehicles" / "ownership" / filename

build_vehicle_distribution(year, ownership_path, to_file=True)
