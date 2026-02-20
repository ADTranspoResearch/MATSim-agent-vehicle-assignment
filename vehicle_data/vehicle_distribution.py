import pandas as pd
import os
base_dir = os.path.dirname(os.path.abspath(__file__))
csv_path = os.path.join(base_dir, "ownership/McGill_SAAQ_2013_2024-01-10.csv")
df = (pd.read_csv(csv_path, sep=";", encoding="utf-16")
      .loc[:, ['RTA', 'Genre', 'AgeProprio (groupes)', 'Hybrid Type', 'Motorisation', 'Classe principale', 'Usage']]
      .rename(columns={'RTA': 'fsa', 'Genre': 'gender', 'AgeProprio (groupes)': 'age_group'})
      .query("Usage != 'Commercial' and age_group != 'Commercial'")
      .dropna(subset=['gender', 'Classe principale'])
      .drop(columns=['Usage'])
      .copy())

age_mapping = {
    '19 ans et moins': pd.Interval(0, 20, closed='left'),
    '20 à 29 ans': pd.Interval(20, 30, closed='left'),
    '30 à 39 ans': pd.Interval(30, 40, closed='left'),
    '40 à 49 ans': pd.Interval(40, 50, closed='left'),
    '50 à 59 ans': pd.Interval(50, 60, closed='left'),
    '60 ans et plus': pd.Interval(60, 120, closed='left')
}
df['age_group'] = df['age_group'].map(age_mapping)


def get_vehicle_type(row):

    h_type = str(row.get('Hybrid Type')).lower().strip()
    motor = str(row.get('Motorisation', '')).lower().strip()
    c_main = str(row.get('Classe principale', '')).lower().strip()

    is_sedan = any(x in c_main for x in ['compacte', 'sous-sompacte', 'intermediaire', 'minicompacte', 'grande berline', 'deux places'])
    is_suv = any(x in c_main for x in ['familiale', 'fourgonnette', 'vus'])
    is_pickup_van = any(x in c_main for x in ['camionnette', 'vehicule à usage spécial', 'fourgon'])

    if h_type == "" and motor == "":
        return 'unknow'
    
    if motor == 'electrique':
        return 'electric'

    is_hybrid = (motor in ['hybride', 'hybride branchable']) or (motor == "" and h_type != "") 

    is_icev = motor in ['diesel', 'essence', 'gaz naturel']

    if is_hybrid:
        if is_suv:
            return 'hev_suv'
        if is_sedan:
            return 'hev_sedan'
        if is_pickup_van:
            return 'hev_van/pickup'
    
    elif is_icev:
        if is_pickup_van:
            return 'ice_van/pickup'
        if is_suv:
            return 'ice_suv'
        if is_sedan:
            return 'ice_sedan'
    


df['vehicle_type'] = df.apply(get_vehicle_type, axis=1)
df = df.drop(columns=['Hybrid Type', 'Motorisation', 'Classe principale']).query("vehicle_type != 'hev_van/pickup' and vehicle_type != 'unknow'")


veh_dist = (
    df.groupby(['fsa', 'gender', 'age_group'])['vehicle_type']
    .value_counts(normalize=True)
    .reset_index(name='proportion')
)

pivot_veh_dist = veh_dist.pivot_table(
    index=['fsa', 'gender', 'age_group'], 
    columns='vehicle_type', 
    values='proportion', 
    fill_value=0
)
pivot_veh_dist = pivot_veh_dist.sort_index()

if __name__ == "__main__":
    print("Testing distribution output...")
    print(pivot_veh_dist.head())
    pivot_veh_dist.to_parquet(os.path.join(base_dir, 'veh_dist.parquet'))


