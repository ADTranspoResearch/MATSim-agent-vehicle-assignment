from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_DIR / ".cache"
DATASET_DIR = PROJECT_DIR / "datasets"
OUTPUT_DIR = PROJECT_DIR / "outputs"

EXTERNAL_FILE = DATASET_DIR / "Fig1-NMVRegist.xlsx"
POPULATION_FILE = DATASET_DIR / "1710000901-eng.csv"

VEHICLE_TYPES = [
    "electric",
    "hev_sedan",
    "hev_suv",
    "ice_sedan",
    "ice_suv",
    "ice_van/pickup",
]
QUARTER_ORDER = ["T1", "T2", "T3", "T4"]


@dataclass(frozen=True)
class ModelConfig:
    forecast_end_year: int = 2035
    observed_share_end_year: int = 2025
    weighted_delta_start_year: int = 2017
    weighted_delta_growth: float = 0.35
    population_growth_window: tuple[int, int] = (2021, 2026)
    turnover_model: str = "average"
    turnover_rate_clip: tuple[float, float] = (0.03, 0.12)
    share_delta_clip: tuple[float, float] = (-0.05, 0.05)
    damping_end_factor: float = 0.35
    max_electric_entry_share: float = 0.45
    shrinkage_k: float = 500.0
    fsa_share_window: int = 3
    entry_flag: str = "Entrant"
    exit_flag: str = "Sortant"
    selected_year: int = 2035


DEFAULT_CONFIG = ModelConfig()
