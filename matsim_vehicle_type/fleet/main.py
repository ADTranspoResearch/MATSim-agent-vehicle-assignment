"""
Reads historic population trends and vehicle ownership. Calculates
expected vehicle growth based on population growth and ownership rates.
Returns a dataframe containing each year's fleet size, expected growth,
expected new vehicles, and expected old vehicles.
"""

from matsim_vehicle_type.fleet.growth import (
    get_historic_fleet_size,
    read_historic_population,
)

def main(fsa_codes): 
    # Find alpha (veh_per_person) and beta (new_veh_per_person)
    fleet_size = get_historic_fleet_size(fsa_codes)
    pop_filname = f"fsa_projected_pop/{fsa_codes}_projected_pop.csv"  

    historic_pop = read_historic_population(pop_filname)
    historic_pop = historic_pop.merge(
        fleet_size, how="left", left_index=True, right_on="year"
    )
    historic_pop.set_index("year", inplace=True)
    historic_pop.rename(columns={"size": "fleet_size"}, inplace=True)
    historic_pop["veh_per_pers"] = historic_pop["fleet_size"] / historic_pop["persons"]
    historic_pop["new_per_pers"] = historic_pop["new"] / historic_pop["persons"]
    veh_per_pers = historic_pop["veh_per_pers"].mean()
    new_per_pers = historic_pop["new_per_pers"].mean()

    # Calculate projected fleet size
    mask = historic_pop["fleet_size"].isna()

    historic_pop.loc[mask, "fleet_size"] = (
        historic_pop.loc[mask, "persons"] * veh_per_pers
    ).round()
    historic_pop["fleet_growth"] = historic_pop["fleet_size"] - historic_pop[
        "fleet_size"
    ].shift(1)
    historic_pop.loc[mask, "new"] = (
        historic_pop.loc[mask, "persons"] * new_per_pers
    ).round()
    historic_pop["implied_exit"] = historic_pop["new"] - historic_pop["fleet_growth"]
    # print(historic_pop)
    return historic_pop
