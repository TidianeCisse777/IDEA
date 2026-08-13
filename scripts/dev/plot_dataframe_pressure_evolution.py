#!/usr/bin/env python3
"""Render evolution graphs from the real offline DataFrame pressure harness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.dev.run_context_projection_campaign import (  # noqa: E402
    run_dataframe_pressure_timeline,
)


def _series(timeline: list[dict[str, int]], name: str) -> list[int]:
    return [item[name] for item in timeline]


def _style_axis(axis, *, title: str, ylabel: str) -> None:  # noqa: ANN001
    axis.set_title(title, loc="left", fontsize=13, fontweight="bold")
    axis.set_xlabel("Tour de conversation")
    axis.set_ylabel(ylabel)
    axis.grid(axis="y", alpha=0.22, linewidth=0.8)
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(frameon=False, ncols=2, fontsize=9, loc="best")


def render_dataframe_evolution(
    timeline: list[dict[str, int]],
    destination: Path,
) -> None:
    """Plot stored, visible, archived and model-detailed DataFrame counts."""

    turns = _series(timeline, "turn")
    figure, axis = plt.subplots(figsize=(12, 6.6), constrained_layout=True)
    axis.plot(
        turns,
        _series(timeline, "dataframes_stored_total"),
        color="#374151",
        linewidth=2.4,
        label="Payloads stockés (courants + versions)",
    )
    axis.plot(
        turns,
        _series(timeline, "derived_versions_superseded"),
        color="#d97706",
        linewidth=2.1,
        label="Versions superseded archivées",
    )
    axis.plot(
        turns,
        _series(timeline, "derived_dataframes_archived"),
        color="#9333ea",
        linewidth=2.1,
        label="Dérivés courants archivés",
    )
    axis.plot(
        turns,
        _series(timeline, "derived_dataframes_visible"),
        color="#2563eb",
        linewidth=2.4,
        label="Dérivés visibles au runtime",
    )
    axis.plot(
        turns,
        _series(timeline, "dataframe_detailed_count"),
        color="#059669",
        linewidth=2.4,
        label="Cartes détaillées dans le prompt",
    )
    axis.axhline(
        20,
        color="#2563eb",
        linestyle="--",
        linewidth=1.2,
        alpha=0.65,
        label="Plafond runtime = 20",
    )
    axis.axhline(
        8,
        color="#059669",
        linestyle=":",
        linewidth=1.4,
        alpha=0.8,
        label="Plafond détaillé = 8",
    )
    _style_axis(
        axis,
        title="Évolution des DataFrames — scénario 34 tables / 50 tours",
        ylabel="Nombre de DataFrames ou versions",
    )
    axis.annotate(
        f"{timeline[-1]['dataframes_stored_total']} payloads stockés",
        xy=(turns[-1], timeline[-1]["dataframes_stored_total"]),
        xytext=(-118, -4),
        textcoords="offset points",
        fontsize=9,
        color="#374151",
    )
    figure.savefig(destination, dpi=170)
    plt.close(figure)


def render_context_evolution(
    timeline: list[dict[str, int]],
    destination: Path,
) -> None:
    """Plot checkpoint/provider message counts and model-context token counts."""

    turns = _series(timeline, "turn")
    figure, axes = plt.subplots(
        2,
        1,
        figsize=(12, 8.2),
        sharex=True,
        constrained_layout=True,
    )
    message_axis, token_axis = axes
    message_axis.plot(
        turns,
        _series(timeline, "checkpoint_messages_before"),
        color="#dc2626",
        linewidth=1.8,
        label="Checkpoint observé avant compaction",
    )
    message_axis.plot(
        turns,
        _series(timeline, "checkpoint_messages_after"),
        color="#2563eb",
        linewidth=2.4,
        label="Checkpoint durable après compaction",
    )
    message_axis.plot(
        turns,
        _series(timeline, "provider_messages"),
        color="#059669",
        linewidth=2.0,
        label="Messages réellement envoyés au modèle",
    )
    message_axis.axhline(
        40,
        color="#2563eb",
        linestyle="--",
        linewidth=1.2,
        alpha=0.7,
        label="Plafond checkpoint = 40",
    )
    _style_axis(
        message_axis,
        title="Historique durable et vue fournisseur",
        ylabel="Nombre de messages",
    )
    message_axis.set_xlabel("")

    token_axis.plot(
        turns,
        _series(timeline, "model_request_tokens"),
        color="#374151",
        linewidth=2.3,
        label="Requête modèle totale estimée",
    )
    token_axis.plot(
        turns,
        _series(timeline, "dynamic_context_tokens"),
        color="#d97706",
        linewidth=2.2,
        label="Contexte dynamique",
    )
    _style_axis(
        token_axis,
        title="Évolution du contexte réellement projeté",
        ylabel="Tokens approximatifs",
    )
    figure.savefig(destination, dpi=170)
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate graphs from IDEA's offline DataFrame pressure harness."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "output" / "dataframe-pressure",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    timeline = run_dataframe_pressure_timeline()
    report_path = output_dir / "dataframe_pressure_timeline.json"
    dataframe_graph = output_dir / "dataframe_pressure_evolution.png"
    context_graph = output_dir / "context_pressure_evolution.png"
    report_path.write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    render_dataframe_evolution(timeline, dataframe_graph)
    render_context_evolution(timeline, context_graph)
    print(
        "50 tours validés; "
        f"métriques={report_path}; graphes={dataframe_graph},{context_graph}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
