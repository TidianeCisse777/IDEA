import scripts.evals.run_copepod_graph_happy_path_multiturn_eval as multiturn_eval
from core.session_store import InMemorySessionStore
import core.session_store as session_store_module


def test_multiturn_runner_exposes_uvp_validation_followup_slug():
    slugs = {scenario.slug for scenario in multiturn_eval.MULTITURN_SCENARIOS}
    assert "uvp_enriched_after_validation_clarification" in slugs


def test_multiturn_runner_exposes_neolabs_validation_followup_slug():
    slugs = {scenario.slug for scenario in multiturn_eval.MULTITURN_SCENARIOS}
    assert "neolabs_ctd_after_validation_clarification" in slugs


def test_build_column_context_note_uses_exact_fact_label():
    store = InMemorySessionStore()
    store.store_inspection_data(
        "s1",
        "sample.csv",
        {"columns": [{"name": "sample_id"}, {"name": "station"}, {"name": "depth"}]},
    )
    store.write_working_set(
        "s1",
        {"latest_inspection_by_file": {"sample.csv": "sample.csv | likely_neolabs_taxon | 120 × 12"}},
    )

    previous = session_store_module.session_store
    session_store_module.session_store = store
    try:
        note = multiturn_eval._build_column_context_note("s1", ["sample.csv"])
    finally:
        session_store_module.session_store = previous

    assert "Inspected file columns (exact facts available for readback and graph_readiness):" in note
    assert "sample.csv : sample_id, station, depth" in note
    assert "do not narrate to user" not in note
