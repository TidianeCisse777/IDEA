"""Regression: a visual turn pre-activates graph skills without a load_skill round-trip.

Before this, a graph turn spent one model round-trip per skill on
`load_skill("graph_planner")` / `load_skill("graph_writer")` (measured in 10/15
captured graph turns, several loading twice). Both skills are fully represented
by static runtime capsules, so seeding them directly gives the model the same
rules while removing the calls. run_graph already self-heals the same capsule,
so this only removes latency and never changes output.
"""
import pandas as pd

from tools.dataset_registry import store_dataset
from tools.session_context import build_dataset_state_capsule
from tools.session_store import SessionStore
from tools.skill_tool import preseed_capsule_skills


def _store_with_df(tmp_path):
    store = SessionStore(tmp_path)
    thread_id = "graph-turn"
    df = pd.DataFrame({
        "sample_id": ["s1", "s2"],
        "latitude": [50.1, 50.2],
        "longitude": [-60.1, -60.2],
        "abundance": [12, 8],
    })
    store_dataset(
        store,
        thread_id,
        df,
        variable_name="df_stations",
        meta={"source": "file:/data/stations.tsv", "n_rows": 2, "n_cols": 4},
    )
    return store, thread_id


def test_preseed_activates_graph_skills_in_capsule(tmp_path):
    store, thread_id = _store_with_df(tmp_path)

    seeded = preseed_capsule_skills(
        store, thread_id, ("graph_planner", "graph_writer")
    )

    assert set(seeded) == {"graph_planner", "graph_writer"}

    meta = (store.get(thread_id) or {}).get("meta") or {}
    capsules = meta.get("active_skill_capsules") or {}
    assert "graph_planner" in capsules
    assert "graph_writer" in capsules

    capsule = build_dataset_state_capsule(store, thread_id)
    assert "ACTIVE SKILL RULES" in capsule
    assert "graph_planner" in capsule
    assert "graph_writer" in capsule


def test_preseed_is_idempotent(tmp_path):
    store, thread_id = _store_with_df(tmp_path)

    first = preseed_capsule_skills(store, thread_id, ("graph_planner", "graph_writer"))
    second = preseed_capsule_skills(store, thread_id, ("graph_planner", "graph_writer"))

    assert set(first) == {"graph_planner", "graph_writer"}
    # Already active on the second turn: no re-seed churn reported.
    assert second == []


def test_preseed_ignores_skills_without_runtime_capsule(tmp_path):
    store, thread_id = _store_with_df(tmp_path)

    # Only skills fully captured by a runtime capsule are eligible; a source
    # skill like ecopart_query must still be loaded explicitly when needed.
    seeded = preseed_capsule_skills(store, thread_id, ("ecopart_query",))
    assert seeded == []


def test_preseed_noop_without_thread(tmp_path):
    store = SessionStore(tmp_path)
    assert preseed_capsule_skills(store, None, ("graph_writer",)) == []


def test_graph_reference_delivers_full_reviewed_templates():
    from pathlib import Path

    from tools.skill_tool import graph_rendering_reference

    reference = graph_rendering_reference()

    # The reviewed templates the compact capsule dropped must now be present so
    # the model builds run_graph code from them instead of re-deriving from
    # memory (which drove render retries).
    assert "GRAPH RENDERING REFERENCE" in reference
    for marker in (
        "station_map",
        "Cartopy",
        "zone_polygons",
        "graph_contract",
        "Zoom to data",
    ):
        assert marker in reference, marker

    # It carries essentially the whole reviewed body, not a 1.6% summary.
    full = (
        Path("agents/skills/graph_writer.md").read_text()
        + Path("agents/skills/graph_planner.md").read_text()
    )
    assert len(reference) > 0.8 * len(full)
