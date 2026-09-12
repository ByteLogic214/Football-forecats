"""Salida: reporte Markdown + JSON en outputs/."""
from __future__ import annotations

import json
import os
from dataclasses import asdict


def _pct(x: float | None, digits: int = 1) -> str:
    return "-" if x is None else f"{x * 100:.{digits}f}%"


def write_reports(date_str: str, ranked: list, tracked: list,
                  diagnostics: list[str], outdir: str = "outputs") -> tuple[str, str]:
    os.makedirs(outdir, exist_ok=True)
    md_path = os.path.join(outdir, f"picks-{date_str}.md")
    json_path = os.path.join(outdir, f"picks-{date_str}.json")

    lines: list[str] = []
    lines.append(f"# Pronósticos del {date_str}")
    lines.append("")
    lines.append("> Modelo Poisson sobre estadísticas reales (TheStatsAPI) y cuotas reales "
                 "(TheOddsAPI + TheStatsAPI). Stakes con Kelly fraccionado. "
                 "**Ningún pick es una garantía: gestiona tu banca.**")
    lines.append("")

    if ranked:
        lines.append(f"## Picks de valor (edge >= filtro, ordenados por prioridad) — {len(ranked)}")
        lines.append("")
        lines.append("| # | Kickoff UTC | Partido | Mercado | Selección | Prob. modelo | Cuota | Implícita | Edge | Confianza | Stake |")
        lines.append("|---|-------------|---------|---------|-----------|--------------|-------|-----------|------|-----------|-------|")
        for i, c in enumerate(ranked, 1):
            implied = f"{(1 / c.odds) * 100:.1f}%" if c.odds else "-"
            lines.append(
                f"| {i} | {c.kickoff} | {c.match} | {c.market} | {c.selection} "
                f"| {_pct(c.model_prob)} | {c.odds} | {implied} | {_pct(c.edge)} "
                f"| {_pct(c.confidence, 0)} | {c.stake_pct} |"
            )
        lines.append("")
        best = ranked[0]
        lines.append(f"**Pick más seguro del día:** {best.selection} ({best.match}) — "
                     f"prob. modelo {_pct(best.model_prob)}, cuota {best.odds}, edge {_pct(best.edge)}.")
        lines.append("")
    else:
        lines.append("## Picks de valor")
        lines.append("")
        lines.append("Sin picks que superen los filtros de edge/probabilidad hoy. **No forzar apuestas.**")
        lines.append("")

    if tracked:
        lines.append(f"## Seguimiento del modelo (sin cuota disponible en las fuentes) — {len(tracked)}")
        lines.append("")
        lines.append("| Kickoff UTC | Partido | Mercado | Selección | Prob. modelo | Cuota justa |")
        lines.append("|-------------|---------|---------|-----------|--------------|-------------|")
        for c in tracked:
            lines.append(f"| {c.kickoff} | {c.match} | {c.market} | {c.selection} "
                         f"| {_pct(c.model_prob)} | {c.fair_odds} |")
        lines.append("")

    lines.append("## Diagnóstico")
    lines.append("")
    for d in diagnostics:
        lines.append(f"- {d}")
    lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    payload = {
        "date": date_str,
        "picks": [asdict(c) for c in ranked],
        "tracked": [asdict(c) for c in tracked],
        "diagnostics": diagnostics,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return md_path, json_path
