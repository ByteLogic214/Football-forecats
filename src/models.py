"""Modelos de datos del sistema."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Fixture:
    match_id: str
    competition_id: str
    season_id: str
    utc_date: str
    home_id: str
    home_name: str
    away_id: str
    away_name: str


@dataclass
class TeamSeasonStats:
    team_id: str
    played: int = 0
    goals_for: int = 0
    goals_against: int = 0
    form: str = ""


@dataclass
class TeamRecentStats:
    """Medias por partido calculadas desde partidos reales ya terminados."""
    matches_used: int = 0
    goals_for_pg: float = 1.30
    goals_against_pg: float = 1.10
    shots_for_pg: float = 12.0
    shots_against_pg: float = 12.0
    sot_for_pg: float = 4.2
    sot_against_pg: float = 4.2
    corners_for_pg: float = 5.0
    corners_against_pg: float = 5.0


@dataclass
class MatchOdds:
    """Cuotas normalizadas a decimal (mejor precio por lado entre casas/fuentes).

    total_goals / match_corners: {line_str: {"over": x, "under": y}}
    team_totals:                 {line_str: {team_norm: {"over": x, "under": y}}}
    """
    match_odds: dict = field(default_factory=dict)   # {"home": x, "draw": x, "away": x}
    btts: dict = field(default_factory=dict)         # {"yes": x, "no": x}
    total_goals: dict = field(default_factory=dict)
    match_corners: dict = field(default_factory=dict)
    team_totals: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)


@dataclass
class Candidate:
    market: str        # shots_on_target | corners | btts | totals | team_totals | match_odds
    selection: str     # texto legible, ej "Córners partido +9.5"
    line: float | None
    model_prob: float
    odds: float | None
    fair_odds: float
    edge: float | None  # None = sin cuota disponible
    priority: int
    confidence: float
    stake_pct: float
    has_odds: bool
    match: str = ""
    kickoff: str = ""
