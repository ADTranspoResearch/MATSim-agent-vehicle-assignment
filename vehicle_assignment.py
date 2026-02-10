"""
Collection of functions that return the vehicle to be assigned to the
input agent and agent demographics.
"""

import random


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

    # Qi you can change the orders here or assign them dynamically from the dataframe.
    vehicle_labels = ("ice_sedan","hev_sedan", "ice_suv", "hev_suv", "van/pickup", "electric")
    vehicle_probs = ("placeholder")
    return (vehicle_labels,vehicle_probs)


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
