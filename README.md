# Sistema de pronósticos de fútbol (TheStatsAPI + TheOddsAPI)

Modelo Poisson sobre **estadísticas reales** (goles, remates, remates al arco y
córners de los últimos N partidos + temporada) y **cuotas reales** en tiempo
casi real (TheOddsAPI como fuente principal, TheStatsAPI como respaldo, sobre
todo para córners). Prioriza: remates al arco > córners > BTTS > totales de
goles > goles por equipo > 1X2.

> **Aviso:** ningún modelo garantiza beneficios. Este sistema busca valor
> esperado positivo y gestiona la banca (Kelly fraccionado con tope). Apuesta
> con responsabilidad y solo dinero que puedas permitirte perder.

## Flujo

1. `fixtures` de hoy (TheStatsAPI `/football/matches`, status=scheduled).
2. Por partido: stats de temporada + últimos 5 partidos terminados
   (`/football/matches/{id}/stats` → goles, total_shots, shots_on_target, corner_kicks).
3. Lambdas Poisson (goles, SOT, remates, córners) con ajuste de localía.
4. Cuotas: TheOddsAPI (`h2h, totals, btts, team_totals`) + TheStatsAPI
   (`/football/matches/{id}/odds` → incluye `match_corners`).
5. Edge = prob. modelo − prob. implícita sin margen. Filtros MIN_EDGE/MIN_PROB.
6. Reporte `outputs/picks-YYYY-MM-DD.md/.json` + artefacto + commit al repo.

## Despliegue 100% móvil (sin terminal)

1. Crea el repo vacío en **github.com** desde el móvil (botón `+` → New repository → `football-forecasts`).
2. Por cada archivo: **Add file → Create new file**, pega el contenido y pon la ruta exacta
   (ej. `src/engine.py`). GitHub crea las carpetas automáticamente.
3. **Settings → Secrets and variables → Actions → Secrets**: añade
   `STATS_API_KEY` y `ODDS_API_KEY`.
4. Misma sección, pestaña **Variables**: añade `COMPETITION_IDS` (ej. `comp_3039`),
   y opcionalmente `MIN_EDGE`, `BANKROLL`, etc. (ver `.env.example`).
5. **Actions → pronosticos-futbol → Run workflow** (o espera al cron).
   Los reportes quedan en `outputs/` y como artefacto descargable.

## Ajuste fino

| Variable | Default | Efecto |
|---|---|---|
| `MIN_EDGE` | 0.04 | Edge mínimo para emitir pick (sube = menos picks, más selectivo) |
| `MIN_PROB` | 0.55 | Probabilidad mínima del modelo |
| `SOT_LOOKBACK` | 5 | Partidos recientes para remates/córners |
| `FORM_WEIGHT` | 0.60 | Peso de la forma reciente vs temporada |
| `KELLY_FRACTION` | 0.25 | Fracción Kelly (0.25–0.5 prudente) |
| `MAX_STAKE_PCT` | 0.03 | Tope de stake por pick (% de banca) |

## Costes de API

- **TheOddsAPI**: cada llamada cuesta regiones × mercados créditos; revisa el
  header `x-requests-remaining` (aparece en el diagnóstico del reporte).
  Reduce `ODDS_SPORT_KEYS`/`ODDS_REGIONS` si tu plan es pequeño.
- **TheStatsAPI**: `recent_stats` hace 1 + N llamadas por equipo
  (lista de partidos + stats de cada uno). Con `SOT_LOOKBACK=5` son ~11
  llamadas por equipo. Ajusta según tu plan.

## Roadmap sugerido

- Backtesting contra cuotas históricas (TheOddsAPI `/v4/historical`).
- Dixon-Coles y xG (`/football/matches/{id}/shotmap`) en vez de goles reales.
- Tracking de resultados (grading) de los picks para medir ROI real.
