"""Graphiques PNG déterministes, bornés et écrits atomiquement."""

from __future__ import annotations

import asyncio
import math
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any


_resolve_path: Callable[[str], str] | None = None
_default_output: Callable[[], Path] | None = None
_CHART_TYPES = {
    "bar",
    "horizontal_bar",
    "pie",
    "donut",
    "line",
    "area",
    "multi_line",
    "scatter",
    "radar",
    "grouped_bar",
    "stacked_bar",
}
_DEFAULT_COLORS = [
    "#c9a84c",
    "#e8c96d",
    "#5b9bd5",
    "#70ad47",
    "#ed7d31",
    "#a07830",
    "#d4b060",
    "#7030a0",
    "#c0504d",
    "#4bacc6",
]


def configure(
    *,
    resolve_path: Callable[[str], str],
    default_output: Callable[[], Path],
) -> None:
    global _resolve_path, _default_output
    _resolve_path = resolve_path
    _default_output = default_output


def _number_list(raw: Any, *, name: str, expected: int) -> list[float]:
    if not isinstance(raw, list):
        raise ValueError(f"'{name}' doit être une liste.")
    if len(raw) != expected:
        raise ValueError(
            f"'{name}' doit contenir exactement {expected} valeurs."
        )
    values: list[float] = []
    for item in raw:
        if isinstance(item, bool):
            raise ValueError(f"'{name}' contient une valeur non numérique.")
        try:
            value = float(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"'{name}' contient une valeur non numérique.") from exc
        if not math.isfinite(value):
            raise ValueError(f"'{name}' contient une valeur non finie.")
        values.append(value)
    return values


def _validated(args: dict) -> dict[str, Any]:
    if _resolve_path is None or _default_output is None:
        raise RuntimeError("Le domaine Graphiques n'est pas configuré.")
    chart_type = str(args.get("chart_type") or "bar").strip().lower()
    if chart_type not in _CHART_TYPES:
        raise ValueError(f"Type de graphique invalide : {chart_type}.")
    raw_labels = args.get("labels")
    if not isinstance(raw_labels, list) or not 1 <= len(raw_labels) <= 100:
        raise ValueError("'labels' doit contenir entre 1 et 100 éléments.")
    labels = [str(item).strip()[:200] for item in raw_labels]
    if any(not label for label in labels):
        raise ValueError("Chaque label doit être non vide.")

    raw_values = args.get("values")
    values = (
        _number_list(raw_values, name="values", expected=len(labels))
        if raw_values not in (None, [])
        else []
    )
    raw_series = args.get("series") or []
    if not isinstance(raw_series, list) or len(raw_series) > 20:
        raise ValueError("'series' doit être une liste de 20 séries maximum.")
    series = []
    for index, item in enumerate(raw_series):
        if not isinstance(item, dict):
            raise ValueError(f"La série {index + 1} doit être un objet.")
        series.append(
            {
                "name": str(item.get("name") or f"Série {index + 1}")[:200],
                "values": _number_list(
                    item.get("values"),
                    name=f"series[{index}].values",
                    expected=len(labels),
                ),
            }
        )
    if not values and not series:
        raise ValueError("Fournir 'values' ou au moins une série.")
    if chart_type in {"pie", "donut", "scatter"} and not values:
        raise ValueError(f"Le type '{chart_type}' exige 'values'.")
    if chart_type in {"grouped_bar", "stacked_bar"} and not series:
        raise ValueError(f"Le type '{chart_type}' exige 'series'.")
    if chart_type in {"pie", "donut"} and any(value < 0 for value in values):
        raise ValueError("Un graphique circulaire refuse les valeurs négatives.")
    if chart_type in {"pie", "donut"} and sum(values) <= 0:
        raise ValueError("La somme d'un graphique circulaire doit être positive.")
    if chart_type == "radar" and len(labels) < 3:
        raise ValueError("Un graphique radar exige au moins trois labels.")

    x_values = None
    if chart_type == "scatter" and args.get("x_values") not in (None, []):
        x_values = _number_list(
            args.get("x_values"),
            name="x_values",
            expected=len(labels),
        )
    raw_colors = args.get("colors")
    if raw_colors is not None:
        if not isinstance(raw_colors, list) or not 1 <= len(raw_colors) <= 100:
            raise ValueError("'colors' doit contenir entre 1 et 100 couleurs.")
        colors = [str(color).strip()[:50] for color in raw_colors]
    else:
        colors = list(_DEFAULT_COLORS)

    raw_output = str(args.get("output_path") or "").strip()
    output = (
        Path(_resolve_path(raw_output)).resolve()
        if raw_output
        else _default_output().resolve()
    )
    if output.suffix.lower() != ".png":
        output = output.with_suffix(".png")
    return {
        "chart_type": chart_type,
        "title": str(args.get("title") or "Graphique").strip()[:500],
        "subtitle": str(args.get("subtitle") or "").strip()[:1000],
        "theme": str(args.get("theme") or "dark").strip().lower(),
        "labels": labels,
        "values": values,
        "series": series,
        "x_values": x_values,
        "colors": colors,
        "output": output,
    }


def _render(spec: dict[str, Any]) -> None:
    import numpy as np
    from matplotlib.colors import is_color_like
    from matplotlib.figure import Figure

    if spec["theme"] not in {"dark", "light"}:
        raise ValueError("Le thème attendu est 'dark' ou 'light'.")
    if any(not is_color_like(color) for color in spec["colors"]):
        raise ValueError("Une couleur fournie n'est pas reconnue par Matplotlib.")

    chart_type = spec["chart_type"]
    labels = spec["labels"]
    values = spec["values"]
    series = spec["series"]
    colors = spec["colors"]
    background, text_color, grid_color = (
        ("#ffffff", "#222222", "#dddddd")
        if spec["theme"] == "light"
        else ("#111111", "#c3c3c3", "#2a2a2a")
    )
    gold = "#c9a84c"
    figure = Figure(figsize=(10, 6), facecolor=background)
    axis = figure.subplots()
    axis.set_facecolor(background)
    x_axis = np.arange(len(labels))

    def color(index: int) -> str:
        return colors[index % len(colors)]

    def style_axes(grid_axis: str = "y") -> None:
        axis.set_xticks(x_axis)
        axis.set_xticklabels(labels, color=text_color, fontsize=9)
        axis.tick_params(colors=text_color)
        axis.grid(axis=grid_axis, color=grid_color, linewidth=0.7)
        for spine in axis.spines.values():
            spine.set_color(grid_color)

    if chart_type in {"pie", "donut"}:
        wedges, _texts, auto_texts = axis.pie(
            values,
            labels=labels,
            colors=[color(index) for index in range(len(labels))],
            autopct="%1.1f%%",
            startangle=140,
            pctdistance=0.8,
            textprops={"color": text_color, "fontsize": 10},
            wedgeprops={"width": 0.42} if chart_type == "donut" else None,
        )
        del wedges
        for auto_text in auto_texts:
            auto_text.set_color(
                background if spec["theme"] == "dark" else "#ffffff"
            )
            auto_text.set_fontweight("bold")
        if chart_type == "donut":
            axis.text(
                0,
                0,
                f"{sum(values):g}",
                ha="center",
                va="center",
                color=gold,
                fontsize=16,
                fontweight="bold",
            )
    elif chart_type in {"line", "area", "multi_line"}:
        plotted = series or [{"name": "", "values": values}]
        for index, item in enumerate(plotted):
            axis.plot(
                x_axis,
                item["values"],
                color=color(index),
                linewidth=2.5,
                marker="o",
                markersize=6,
                markerfacecolor=background,
                markeredgewidth=2,
                label=item["name"],
            )
            if chart_type == "area":
                axis.fill_between(
                    x_axis,
                    item["values"],
                    alpha=0.18,
                    color=color(index),
                )
        style_axes()
        if series:
            axis.legend(
                facecolor=background,
                edgecolor=grid_color,
                labelcolor=text_color,
                fontsize=9,
            )
    elif chart_type == "scatter":
        scatter_x = spec["x_values"] or list(range(len(labels)))
        axis.scatter(
            scatter_x,
            values,
            color=gold,
            s=80,
            alpha=0.8,
            edgecolors=background,
            linewidths=1,
        )
        axis.tick_params(colors=text_color)
        axis.grid(color=grid_color, linewidth=0.7)
        for spine in axis.spines.values():
            spine.set_color(grid_color)
    elif chart_type == "radar":
        axis.remove()
        axis = figure.add_subplot(111, polar=True)
        axis.set_facecolor(background)
        angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
        plotted = series or [{"name": "", "values": values}]
        for index, item in enumerate(plotted):
            closed_values = item["values"] + item["values"][:1]
            closed_angles = angles + angles[:1]
            axis.plot(
                closed_angles,
                closed_values,
                color=color(index),
                linewidth=2,
                label=item["name"],
            )
            axis.fill(closed_angles, closed_values, color=color(index), alpha=0.15)
        axis.set_xticks(angles)
        axis.set_xticklabels(labels, color=text_color, fontsize=9)
        axis.tick_params(colors=text_color)
        if series:
            axis.legend(
                facecolor=background,
                edgecolor=grid_color,
                labelcolor=text_color,
                fontsize=8,
                loc="upper right",
            )
    elif chart_type in {"grouped_bar", "stacked_bar"} and series:
        width = 0.8 / len(series)
        bottom = np.zeros(len(labels))
        for index, item in enumerate(series):
            numeric = np.array(item["values"])
            if chart_type == "stacked_bar":
                axis.bar(
                    x_axis,
                    numeric,
                    bottom=bottom,
                    color=color(index),
                    width=0.55,
                    label=item["name"],
                )
                bottom += numeric
            else:
                axis.bar(
                    x_axis + index * width - 0.4 + width / 2,
                    numeric,
                    color=color(index),
                    width=width,
                    label=item["name"],
                )
        style_axes()
        axis.legend(
            facecolor=background,
            edgecolor=grid_color,
            labelcolor=text_color,
            fontsize=9,
        )
    elif chart_type == "horizontal_bar":
        y_axis = np.arange(len(labels))
        bars = axis.barh(
            y_axis,
            values,
            color=[color(index) for index in range(len(labels))],
            edgecolor="none",
            height=0.55,
        )
        axis.set_yticks(y_axis)
        axis.set_yticklabels(labels, color=text_color, fontsize=9)
        axis.tick_params(colors=text_color)
        axis.grid(axis="x", color=grid_color, linewidth=0.7)
        for spine in axis.spines.values():
            spine.set_color(grid_color)
        span = max(values) - min(values) or max(abs(value) for value in values) or 1
        for bar, value in zip(bars, values):
            axis.text(
                bar.get_width() + span * 0.01,
                bar.get_y() + bar.get_height() / 2,
                f"{value:g}",
                va="center",
                color=text_color,
                fontsize=8,
            )
    else:
        bars = axis.bar(
            x_axis,
            values,
            color=[color(index) for index in range(len(labels))],
            edgecolor="none",
            width=0.55,
        )
        style_axes()
        span = max(values) - min(values) or max(abs(value) for value in values) or 1
        for bar, value in zip(bars, values):
            axis.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + span * 0.01,
                f"{value:g}",
                ha="center",
                va="bottom",
                color=text_color,
                fontsize=8,
            )

    axis.set_title(
        spec["title"],
        color=gold,
        fontsize=14,
        fontweight="bold",
        pad=16,
    )
    if spec["subtitle"]:
        figure.text(
            0.5,
            0.93,
            spec["subtitle"],
            ha="center",
            color=text_color,
            fontsize=9,
        )
    figure.tight_layout()
    output = spec["output"]
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}.{uuid.uuid4().hex}.tmp.png")
    try:
        figure.savefig(
            temporary,
            dpi=150,
            bbox_inches="tight",
            facecolor=background,
            format="png",
        )
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


async def create(args: dict) -> dict:
    try:
        spec = _validated(args)
        await asyncio.to_thread(_render, spec)
        output = spec["output"]
        return {
            "success": True,
            "message": f"Infographie créée : {output}",
            "path": str(output),
            "chart_type": spec["chart_type"],
            "points": len(spec["labels"]),
            "series_count": len(spec["series"]) or 1,
        }
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return {"error": str(exc)}
