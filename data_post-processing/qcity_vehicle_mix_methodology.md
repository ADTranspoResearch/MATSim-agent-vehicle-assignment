# Quebec City EV Body-Type Split Methodology

The total EV share in each plot comes from `data/vehicles/val_outputs/bau/H0H_predicted_fleet_mix.csv`.

To split the EV share into body types, Quebec battery-electric registration counts were taken from `data/2310030801-eng.numbers`, which corresponds to Statistics Canada Table 23-10-0308-01, "Vehicle registrations, by type of vehicle and fuel type": https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=2310030801

Three EV categories were used:

- Passenger cars: battery-electric passenger cars.
- Multi-purpose vehicles: battery-electric multi-purpose vehicles, including SUVs and crossovers.
- Van/Pickup: battery-electric pickup trucks plus battery-electric vans.

For each historical year, the three category counts were normalized so they sum to 100% of the selected EV categories. The total EV share from the model was then multiplied by these normalized category shares. For 2021-2024, the historical year-specific shares were used. For 2025-2040, the 2024 EV body-type split was held constant.

The plotted EV data points and labels remain the total EV share, not the individual body-type shares.
