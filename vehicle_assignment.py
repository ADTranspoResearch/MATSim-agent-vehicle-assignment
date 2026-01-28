"""
Collection of functions that return the vehicle to be assigned to the
input agent and agent demographics.
"""

import random

def get_veh_from_xy(location, seed):
    """
    Function returns randomly selected vehicle type based on home
    location.

    location (set): XY coordinate of person home location.
    seed (int): random seed for reproducibility of random selection.

    returns (string): selected vehicle type.
    """


    # Setting seed for reproduction.
    random.seed(seed)

    # Vehicles should be a list of all possible vehicle types.
    vehicles = ["ICE_sedan","HEV_sedan"]
    # Ownership_rates should be a list corresponding to the selection
    # probability of the options in vehicles list.
    ownership_rates = [0.5, 0.5]

    vehicle = random.choices(vehicles, weights=ownership_rates, k=1)[0]
    return vehicle
