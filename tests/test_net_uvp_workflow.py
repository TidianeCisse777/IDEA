"""Persisted Net↔UVP workflow progress."""

import pytest

from tools.session_store import SessionStore


def _store_with_certified_audit(tmp_path) -> SessionStore:
    store = SessionStore(tmp_path / "sessions")
    store.set(
        "thread-1:dataset:net-table",
        None,
        {"source": "file:net.tsv", "variable_name": "net-table"},
    )
    store.set(
        "thread-1:dataset:audit-table",
        None,
        {
            "source": "net_uvp_match",
            "variable_name": "audit-table",
            "net_variable_name": "net-table",
            "ctd_verification": "verified",
            "exploratory": False,
        },
    )
    store.set(
        "thread-1:selection:certified-selection",
        None,
        {
            "source": "net_uvp_certified_selection",
            "selection_name": "certified-selection",
            "audit_variable": "audit-table",
            "net_variable_name": "net-table",
            "ctd_verification": "verified",
            "exploratory": False,
        },
    )
    return store


def _store_with_exploratory_audit(tmp_path) -> SessionStore:
    store = SessionStore(tmp_path / "sessions")
    store.set(
        "thread-1:dataset:net-table",
        None,
        {"source": "file:net.tsv", "variable_name": "net-table"},
    )
    store.set(
        "thread-1:dataset:audit-table",
        None,
        {
            "source": "net_uvp_match",
            "variable_name": "audit-table",
            "net_variable_name": "net-table",
            "ctd_verification": "unavailable",
            "exploratory": True,
        },
    )
    store.set(
        "thread-1:selection:exploratory-selection",
        None,
        {
            "source": "net_uvp_exploratory_selection",
            "selection_name": "exploratory-selection",
            "audit_variable": "audit-table",
            "net_variable_name": "net-table",
            "ctd_verification": "unavailable",
            "exploratory": True,
        },
    )
    return store


def test_progress_after_certified_audit_is_not_a_single_next_tool(tmp_path):
    from tools.net_uvp_workflow import resolve_net_uvp_progress

    progress = resolve_net_uvp_progress(_store_with_certified_audit(tmp_path), "thread-1")

    assert progress.phase == "audited"
    assert {"inspect", "visualize", "export"} <= progress.allowed_capabilities
    assert progress.ctd_status == "verified"


def test_progress_marks_ctd_unavailable_as_exploratory_not_no_match(tmp_path):
    from tools.net_uvp_workflow import resolve_net_uvp_progress

    progress = resolve_net_uvp_progress(_store_with_exploratory_audit(tmp_path), "thread-1")

    assert progress.phase == "audited"
    assert progress.ctd_status == "unavailable"
    assert "prepare_provisional_export" in progress.allowed_capabilities


def test_completed_combined_audit_satisfies_its_persisted_scope_refs(tmp_path):
    """Leaf zone/time subsets are inputs of one combined audit, not extra work."""
    from tools.net_uvp_workflow import resolve_net_uvp_progress

    store = SessionStore(tmp_path / "sessions")
    store.set(
        "thread-1:dataset:net-table",
        None,
        {"source": "file:net.tsv", "variable_name": "net-table"},
    )
    store.set(
        "thread-1:dataset:scope-baffin-2024",
        None,
        {
            "source": "net_uvp_audit_subset",
            "variable_name": "scope-baffin-2024",
            "parent_variable": "net-table",
        },
    )
    store.set(
        "thread-1:dataset:combined-audit-input",
        None,
        {
            "source": "net_uvp_audit_subset",
            "variable_name": "combined-audit-input",
            "net_uvp_audit_input": True,
            "parent_variable": "net-table",
            "scope_refs": ["scope-baffin-2024"],
        },
    )
    store.set(
        "thread-1:dataset:df_net_uvp_matches",
        None,
        {
            "source": "net_uvp_match",
            "variable_name": "df_net_uvp_matches",
            "net_variable_name": "combined-audit-input",
            "net_dataframe_fingerprint": "net-v1",
            "ctd_verification": "verified",
            "exploratory": False,
        },
    )
    store.set(
        "thread-1:selection:certified-selection",
        None,
        {
            "source": "net_uvp_certified_selection",
            "selection_name": "certified-selection",
            "audit_variable": "df_net_uvp_matches",
            "net_variable_name": "combined-audit-input",
            "net_dataframe_fingerprint": "net-v1",
            "ctd_verification": "verified",
            "exploratory": False,
        },
    )

    progress = resolve_net_uvp_progress(store, "thread-1")

    assert progress.phase == "audited"
    assert progress.audit_ref == "df_net_uvp_matches"
    assert progress.selection_name == "certified-selection"


def test_stale_selection_and_unrelated_enrichment_do_not_advance_current_audit(tmp_path):
    """A fixed audit variable name cannot reconnect records from old attempts."""
    from tools.net_uvp_workflow import resolve_net_uvp_progress

    store = SessionStore(tmp_path / "sessions")
    store.set(
        "thread-1:dataset:net-table-current",
        None,
        {"source": "file:net.tsv", "variable_name": "net-table-current"},
    )
    store.set(
        "thread-1:dataset:df_net_uvp_matches",
        None,
        {
            "source": "net_uvp_match",
            "variable_name": "df_net_uvp_matches",
            "net_variable_name": "net-table-current",
            "net_dataframe_fingerprint": "net-current",
            "ctd_verification": "verified",
            "exploratory": False,
        },
    )
    store.set(
        "thread-1:selection:old-selection",
        None,
        {
            "source": "net_uvp_exploratory_selection",
            "selection_name": "old-selection",
            "audit_variable": "df_net_uvp_matches",
            "net_variable_name": "net-table-old",
            "net_dataframe_fingerprint": "net-old",
            "ctd_verification": "unavailable",
            "exploratory": True,
        },
    )
    store.set(
        "thread-1:dataset:old-export",
        None,
        {
            "source": "ecotaxa_export_campaign",
            "variable_name": "old-export",
            "selection_name": "old-selection",
        },
    )
    store.set(
        "thread-1:dataset:unrelated-enrichment",
        None,
        {
            "source": "join:ecotaxa+ecopart",
            "variable_name": "unrelated-enrichment",
            "source_variable": "another-export",
        },
    )

    progress = resolve_net_uvp_progress(store, "thread-1")

    assert progress.phase == "audited"
    assert progress.selection_name is None
    assert progress.ctd_status == "verified"


def test_fresh_no_match_audit_does_not_reuse_old_same_input_selection(tmp_path):
    """A new no-match audit wins even when its input table is unchanged."""
    from tools.net_uvp_workflow import resolve_net_uvp_progress

    store = SessionStore(tmp_path / "sessions")
    store.set(
        "thread-1:dataset:net-table",
        None,
        {"source": "file:net.tsv", "variable_name": "net-table"},
    )
    store.set(
        "thread-1:dataset:df_net_uvp_matches",
        None,
        {
            "source": "net_uvp_match",
            "variable_name": "df_net_uvp_matches",
            "net_variable_name": "net-table",
            "net_dataframe_fingerprint": "unchanged-net",
            "ctd_verification": "no_match",
            "exploratory": False,
        },
    )
    store.set(
        "thread-1:selection:old-certified",
        None,
        {
            "source": "net_uvp_certified_selection",
            "selection_name": "old-certified",
            "audit_variable": "df_net_uvp_matches",
            "net_variable_name": "net-table",
            "net_dataframe_fingerprint": "unchanged-net",
            "ctd_verification": "verified",
            "exploratory": False,
        },
    )
    store.set(
        "thread-1:dataset:old-export",
        None,
        {
            "source": "ecotaxa_export_campaign",
            "variable_name": "old-export",
            "selection_name": "old-certified",
        },
    )

    progress = resolve_net_uvp_progress(store, "thread-1")

    assert progress.phase == "audited"
    assert progress.selection_name is None
    assert progress.ctd_status == "no_match"


def test_fresh_ctd_unavailable_audit_requires_a_new_exploratory_opt_in(tmp_path):
    """A prior provisional export cannot satisfy a new CTD outage."""
    from tools.net_uvp_workflow import resolve_net_uvp_progress

    store = SessionStore(tmp_path / "sessions")
    store.set(
        "thread-1:dataset:net-table",
        None,
        {"source": "file:net.tsv", "variable_name": "net-table"},
    )
    store.set(
        "thread-1:dataset:df_net_uvp_matches",
        None,
        {
            "source": "net_uvp_match",
            "variable_name": "df_net_uvp_matches",
            "net_variable_name": "net-table",
            "net_dataframe_fingerprint": "unchanged-net",
            "ctd_verification": "unavailable",
            "exploratory": False,
            "allow_unverified_ctd": False,
        },
    )
    store.set(
        "thread-1:selection:old-exploratory",
        None,
        {
            "source": "net_uvp_exploratory_selection",
            "selection_name": "old-exploratory",
            "audit_variable": "df_net_uvp_matches",
            "net_variable_name": "net-table",
            "net_dataframe_fingerprint": "unchanged-net",
            "ctd_verification": "unavailable",
            "exploratory": True,
            "allow_unverified_ctd": True,
        },
    )
    store.set(
        "thread-1:dataset:old-export",
        None,
        {
            "source": "ecotaxa_export_campaign",
            "variable_name": "old-export",
            "selection_name": "old-exploratory",
        },
    )

    progress = resolve_net_uvp_progress(store, "thread-1")

    assert progress.phase == "audited"
    assert progress.selection_name is None
    assert progress.ctd_status == "unavailable"
    assert "prepare_provisional_export" in progress.allowed_capabilities


@pytest.mark.parametrize(
    ("source_variable", "expected_phase"),
    [
        ("df_uvp_export_current", "enriched"),
        (None, "exported"),
        ("df_uvp_export_stale", "exported"),
    ],
)
def test_progress_reaches_enriched_only_through_persisted_export_edge(
    tmp_path,
    source_variable,
    expected_phase,
):
    """A complete current chain ignores stale or unlinked enrichments."""
    from tools.net_uvp_workflow import resolve_net_uvp_progress

    store = SessionStore(tmp_path / "sessions")
    store.set(
        "thread-1:dataset:net-table",
        None,
        {"source": "file:net.tsv", "variable_name": "net-table"},
    )
    store.set(
        "thread-1:dataset:audit-table",
        None,
        {
            "source": "net_uvp_match",
            "variable_name": "audit-table",
            "net_variable_name": "net-table",
            "net_dataframe_fingerprint": "net-v1",
            "ctd_verification": "verified",
            "exploratory": False,
        },
    )
    store.set(
        "thread-1:selection:certified-selection",
        None,
        {
            "source": "net_uvp_certified_selection",
            "selection_name": "certified-selection",
            "audit_variable": "audit-table",
            "net_variable_name": "net-table",
            "net_dataframe_fingerprint": "net-v1",
            "ctd_verification": "verified",
            "exploratory": False,
        },
    )
    store.set(
        "thread-1:dataset:df_uvp_export_current",
        None,
        {
            "source": "ecotaxa_export_campaign",
            "variable_name": "df_uvp_export_current",
            "selection_name": "certified-selection",
        },
    )
    store.set(
        "thread-1:dataset:df_uvp_enriched",
        None,
        {
            "source": "join:ecotaxa_campaign+ecopart",
            "variable_name": "df_uvp_enriched",
            **(
                {"source_variable": source_variable}
                if source_variable is not None
                else {}
            ),
        },
    )
    store.set(
        "thread-1:dataset:df_uvp_export_stale",
        None,
        {
            "source": "ecotaxa_export_campaign",
            "variable_name": "df_uvp_export_stale",
            "selection_name": "stale-selection",
        },
    )
    store.set(
        "thread-1:dataset:df_uvp_enriched_unlinked",
        None,
        {
            "source": "join:ecotaxa_campaign+ecopart",
            "variable_name": "df_uvp_enriched_unlinked",
            "source_variable": "df_uvp_export_stale",
        },
    )

    progress = resolve_net_uvp_progress(store, "thread-1")

    assert progress.phase == expected_phase
