"""Configuración central — todo llega por variables de entorno (.env local / GitHub Secrets)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# Deportes TheOddsAPI asociados por nombre de equipo (matching por nombre normalizado).
DEFAULT_ODDS_SPORT_KEYS = [
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
]

# Liga por defecto: comp_3039 = Premier League (según docs de TheStatsAPI).
DEFAULT_COMPETITIONS = "comp_3039"


def _csv(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, ""))
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, ""))
    except ValueError:
        return default


@dataclass
class Settings:
    stats_api_key: str
    stats_base_url: str = "https://api.thestatsapi.com/api"
    odds_api_key: str = ""
    competition_ids: list[str] = field(default_factory=lambda: [DEFAULT_COMPETITIONS])
    odds_sport_keys: list[str] = field(default_factory=lambda: list(DEFAULT_ODDS_SPORT_KEYS))
    regions: str = "eu,uk"
    # Modelo
    sot_lookback: int = 5       # partidos previos para medias de remates al arco / córners
    form_weight: float = 0.60   # peso de forma reciente vs temporada completa
    home_boost: float = 1.12    # ventaja de localía (multiplicador de goles esperados)
    # Filtros de valor
    min_edge: float = 0.04      # edge mínimo vs probabilidad implícita sin vig
    min_prob: float = 0.55
    max_picks: int = 8
    # Banca
    bankroll: float = 1000.0
    kelly_fraction: float = 0.25
    max_stake_pct: float = 0.03
    # Infra
    timeout: int = 30
    retries: int = 3
    output_dir: str = "outputs"
    fixture_date: str = ""      # YYYY-MM-DD; vacío = hoy UTC

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            stats_api_key=os.getenv("STATS_API_KEY", "").strip(),
            stats_base_url=os.getenv("STATS_API_BASE_URL", "https://api.thestatsapi.com/api").strip(),
            odds_api_key=os.getenv("ODDS_API_KEY", "").strip(),
            competition_ids=_csv("COMPETITION_IDS", DEFAULT_COMPETITIONS),
            odds_sport_keys=_csv("ODDS_SPORT_KEYS", ",".join(DEFAULT_ODDS_SPORT_KEYS)),
            regions=os.getenv("ODDS_REGIONS", "eu,uk"),
            sot_lookback=_i("SOT_LOOKBACK", 5),
            form_weight=_f("FORM_WEIGHT", 0.60),
            home_boost=_f("HOME_BOOST", 1.12),
            min_edge=_f("MIN_EDGE", 0.04),
            min_prob=_f("MIN_PROB", 0.55),
            max_picks=_i("MAX_PICKS", 8),
            bankroll=_f("BANKROLL", 1000.0),
            kelly_fraction=_f("KELLY_FRACTION", 0.25),
            max_stake_pct=_f("MAX_STAKE_PCT", 0.03),
            timeout=_i("REQUEST_TIMEOUT", 30),
            retries=_i("REQUEST_RETRIES", 3),
            output_dir=os.getenv("OUTPUT_DIR", "outputs"),
            fixture_date=os.getenv("FIXTURE_DATE", "").strip(),
        )

    def validate(self) -> None:
        if not self.stats_api_key:
            raise RuntimeError(
                "Falta STATS_API_KEY. Configúrala en .env (local) o en GitHub Secrets (Actions)."
            )
