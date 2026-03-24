import pandas as pd

year = 2018
csv_path = f"vehicle_data/ownership/McGill_SAAQ_{year}_2024-01-10.csv"
df = (
    pd.read_csv(csv_path, sep=";", encoding="utf-16")
    .loc[
        :,
        [
            "RTA",
            "Hybrid Type",
            "Motorisation",
            "Classe principale",
            "Usage",
        ],
    ]
    .rename(columns={"RTA": "fsa"})
    .query("Usage != 'Commercial'")
    .dropna(subset=["Classe principale"])
    .drop(columns=["Usage"])
    .copy()
)


def get_vehicle_type(row):

    h_type = str(row.get("Hybrid Type")).lower().strip()
    motor = str(row.get("Motorisation", "")).lower().strip()
    c_main = str(row.get("Classe principale", "")).lower().strip()

    is_sedan = any(
        x in c_main
        for x in [
            "compacte",
            "sous-sompacte",
            "intermediaire",
            "minicompacte",
            "grande berline",
            "deux places",
        ]
    )
    is_suv = any(x in c_main for x in ["familiale", "fourgonnette", "vus"])
    is_pickup_van = any(
        x in c_main for x in ["camionnette", "vehicule à usage spécial", "fourgon"]
    )

    if h_type == "" and motor == "":
        return "unknow"

    if motor == "electrique":
        return "electric"

    is_hybrid = (motor in ["hybride", "hybride branchable"]) or (
        motor == "" and h_type != ""
    )

    is_icev = motor in ["diesel", "essence", "gaz naturel"]

    if is_hybrid:
        if is_suv:
            return "hev_suv"
        if is_sedan:
            return "hev_sedan"
        if is_pickup_van:
            return "hev_van/pickup"

    elif is_icev:
        if is_pickup_van:
            return "ice_van/pickup"
        if is_suv:
            return "ice_suv"
        if is_sedan:
            return "ice_sedan"


df["vehicle_type"] = df.apply(get_vehicle_type, axis=1)
df = df.drop(columns=["Hybrid Type", "Motorisation", "Classe principale"]).query(
    "vehicle_type != 'hev_van/pickup' and vehicle_type != 'unknow'"
)


veh_dist = (
    df.groupby(["fsa"])["vehicle_type"]
    .value_counts(normalize=True)
    .reset_index(name="proportion")
)

pivot_veh_dist = veh_dist.pivot_table(
    index=["fsa"],
    columns="vehicle_type",
    values="proportion",
    fill_value=0,
)
pivot_veh_dist = pivot_veh_dist.sort_index()

if __name__ == "__main__":
    print("Testing distribution output...")
    print(pivot_veh_dist.head())
    pivot_veh_dist.to_parquet(f"vehicle_data/fsa_vehicle_share_{year}.parquet")
    pivot_veh_dist.to_csv(f"vehicle_data/fsa_vehicle_share_{year}.csv")
