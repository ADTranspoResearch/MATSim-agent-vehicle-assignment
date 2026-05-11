"""
Script takes a MATSim population file, and assigns each agent a vehicle
type based on the provided vehicle ownership distribution data.
"""

import _setup_path  # pylint: disable=unused-import
from matsim_vehicle_type.main import assign_matsim_users_vehicle_type

if __name__ == "__main__":
    assign_matsim_users_vehicle_type()
