"""
Module contains functions for parsing and analyzing MATSim population.
"""

import xml.etree.ElementTree as ET


def get_home(person: ET.Element):
    """
    Takes a "person" XML tree as input and returns home XY coord.

    :param person: XML Element of person from population file.

    Returns (X,Y)
    """

    plan = person.find("plan")
    found_home = False
    for activity in plan.findall(".//act"):
        # Only looking for first home based activity.
        if activity.get("type") == "home":
            xy = (float(activity.get("x")), float(activity.get("y")))
            found_home = True
            break
    if found_home:
        return xy
    else:
        raise (
            KeyError(f"Agent {person.find('id')} does not have home activity in plan.")
        )
