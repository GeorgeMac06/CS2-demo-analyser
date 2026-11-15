"""Plotly figure specs, built in Python (ADR-001). The same specs serve app and export.

Colours: a colour-vision-safe sequential scale (Cividis) for heatmaps and a blue/orange pair
for T/CT, so no chart relies on red/green (C-3). Every chart is shown with a table too.
"""

from __future__ import annotations

import polars as pl

SIDE_COLOURS = {"T": "#E69F00", "CT": "#0072B2"}  # Okabe-Ito orange / blue
# Yellow-orange-red: ordered by lightness, so it reads without colour vision (C-3). Opacity
# rises with the value, so rarely visited cells leave the radar visible underneath.
HEAT_SCALE = [
    [0.0, "rgba(255,255,204,0)"], [0.02, "rgba(255,237,160,0.15)"],
    [0.2, "rgba(254,217,118,0.45)"], [0.45, "rgba(253,141,60,0.65)"],
    [0.7, "rgba(240,59,32,0.8)"], [1.0, "rgba(189,0,38,0.92)"],
]  # fmt: skip
HEAT_CAP_PERCENTILE = 0.95  # spawns would otherwise wash out every other area
BUY_ORDER = ["all", "pistol", "eco", "force", "full"]


def _base_layout(**extra) -> dict:
    return {
        "margin": {"l": 40, "r": 10, "t": 10, "b": 40},
        "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": "system-ui, sans-serif", "size": 12},
        "showlegend": True, "legend": {"orientation": "h", "y": -0.2},
    } | extra  # fmt: skip


def winrate_figure(findings: list[dict]) -> dict:
    rows = [f for f in findings if f["kind"] == "team.winrate"]
    data = []
    for side in ("T", "CT"):
        mine = {f["params"]["buy"]: f for f in rows if f["params"]["side"] == side}
        buys = [b for b in BUY_ORDER if b in mine]
        data.append({
            "type": "bar", "name": side, "x": buys,
            "y": [mine[b]["params"]["win_pct"] for b in buys],
            "text": [f"{mine[b]['support']['k']}/{mine[b]['support']['n']}" for b in buys],
            "textposition": "outside", "marker": {"color": SIDE_COLOURS[side]},
            "hovertemplate": "%{x}: %{y}% won (%{text} rounds)<extra>" + side + "</extra>",
        })  # fmt: skip
    layout = _base_layout(
        barmode="group", height=280,
        yaxis={"title": "rounds won (%)", "range": [0, 110], "gridcolor": "rgba(128,128,128,0.25)"},
    )  # fmt: skip
    return {"data": data, "layout": layout}


def heatmap_figure(meta: dict, cells: pl.DataFrame, radar_url: str | None) -> dict:
    """``cells``: rows (cx, cy, count) of one grid. Values are % of the grid's samples."""
    n = meta["shape"][0]
    x0, x1, y0, y1 = meta["extent"]
    z = [[0.0] * n for _ in range(n)]
    total = max(meta["samples"], 1)
    for cx, cy, count in cells.select("cx", "cy", "count").iter_rows():
        z[cy][cx] = round(100 * count / total, 2)
    values = sorted(v for row in z for v in row if v > 0)
    zmax = values[int(HEAT_CAP_PERCENTILE * (len(values) - 1))] if values else 1.0
    step_x, step_y = (x1 - x0) / n, (y1 - y0) / n
    trace = {
        "type": "heatmap", "z": z, "zsmooth": "best", "colorscale": HEAT_SCALE,
        "zmin": 0, "zmax": max(zmax, 0.01),
        "x": [round(x0 + (i + 0.5) * step_x, 1) for i in range(n)],
        "y": [round(y0 + (j + 0.5) * step_y, 1) for j in range(n)],
        "colorbar": {"title": {"text": "% of time<br>per spot"}, "thickness": 12},
        "hovertemplate": "%{z}% of time<extra></extra>",
    }  # fmt: skip
    hidden = {"visible": False, "constrain": "domain"}
    layout = _base_layout(
        height=560, showlegend=False, margin={"l": 0, "r": 0, "t": 0, "b": 0},
        xaxis={**hidden, "range": [x0, x1]},
        yaxis={**hidden, "range": [y1, y0], "scaleanchor": "x"},  # radar y grows downwards
    )  # fmt: skip
    if meta["space"] == "world":
        layout["yaxis"]["range"] = [y0, y1]  # world y grows upwards; no picture behind it
    if radar_url:
        layout["images"] = [{
            "source": radar_url, "xref": "x", "yref": "y", "x": x0, "y": y0,
            "sizex": x1 - x0, "sizey": y1 - y0, "sizing": "stretch", "layer": "below",
        }]  # fmt: skip
    return {"data": [trace], "layout": layout}
