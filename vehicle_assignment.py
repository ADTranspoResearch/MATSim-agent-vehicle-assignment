"""
Collection of functions that return the vehicle to be assigned to the
input agent and agent demographics.
"""

import random
from vehicle_data.vehicle_distribution import pivot_veh_dist

def get_fsa_from_xy(location):
    """
    Returns the FSA that the passed coordinate is located inside of.
    
    :param location: tuple containing XY coordinates

    Returns string: FSA code (ex: H1A)
    """
    return None

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


agent_demo = ('F', 34) 
labels, probs = get_prob_from_demo('G0V', agent_demo)
print(labels)
print(probs)


def get_veh_from_xy(location, demographics, seed):
    """
    Function returns randomly selected vehicle type based on home
    location.

    location (set): XY coordinate of person home location.
    seed (int): random seed for reproducibility of random selection.
    demographic (set): gender & age category of agent.

    returns (string): selected vehicle type.
    """

    fsa = get_fsa_from_xy(location)

    # Setting seed for reproduction.
    random.seed(seed)

    # probability of the options in vehicles list.
    vehicles, ownership_rates = get_prob_from_demo(fsa, demographics)

    vehicle = random.choices(vehicles, weights=ownership_rates, k=1)[0]
    return vehicle
