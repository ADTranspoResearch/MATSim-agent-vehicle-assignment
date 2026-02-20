"""
Collection of functions that return the vehicle to be assigned to the
input agent and agent demographics.
"""

import random
import pandas as pd

vehicle_dist_path = "vehicle_data/veh_dist.parquet"
pivot_veh_dist = pd.read_parquet(vehicle_dist_path)




def get_prob_from_demo(fsa, demographics):
    """
    Given agetn FSA and age/gender, return the probabilities of owning
    each vehicle type.
    
    :param fsa: Forward sorting area code of agent.
    :param demographics: tuple containing gender and age of agent.

    returns (tuple, tuple) (vehicle type labels, vehicle type 
            probabilities)
    """

    gender, age = demographics

    try:
        row = pivot_veh_dist.loc[(fsa, gender, age)]
        active_vehicles = row[row > 0]
        if active_vehicles.empty:
            raise KeyError("No vehicle types with probability > 0")  # TODO: Exclude age-specific vehicle distribution constraints.
        vehicle_labels = tuple(active_vehicles.index)
        vehicle_probs = tuple(float(p) for p in active_vehicles.values)

        return (vehicle_labels, vehicle_probs)
    
    except KeyError:
        error_msg = f"Cannot find vehicle data for FSA: {fsa}, Gender: {gender}, Age: {age}."
        raise RuntimeError(error_msg)







def get_veh_from_fsa(demographics, fsa, seed):
    """
    Function returns randomly selected vehicle type based on home
    location.

    location (set): XY coordinate of person home location.
    demographics (set): gender & age category of agent.
    fsa (string): forward sorting area of user home location
    seed (int): random seed for reproducibility of random selection.
    

    returns (string): selected vehicle type.
    """

    # Setting seed for reproduction.
    random.seed(seed)

    # probability of the options in vehicles list.
    vehicles, ownership_rates = get_prob_from_demo(fsa, demographics)

    vehicle = random.choices(vehicles, weights=ownership_rates, k=1)[0]
    return vehicle
