"""Persistence contracts for deterministic source affinity."""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from tools.session_store import SessionStore


def test_explicit_source_persists_to_following_turn(tmp_path):
    from tools.source_scope import read_source_affinity, source_decision_for_turn

    store = SessionStore(tmp_path)
    first = source_decision_for_turn(
        store,
        "thread",
        [HumanMessage(content="Explore EcoTaxa")],
    )
    second = source_decision_for_turn(
        store,
        "thread",
        [HumanMessage(content="montre le projet 17498")],
    )

    assert first.authorized_sources == ("ecotaxa",)
    assert second.authorized_sources == ("ecotaxa",)
    assert second.evidence == "inherited_affinity"
    assert read_source_affinity(store, "thread").active_sources == ("ecotaxa",)


def test_affinity_survives_session_store_recreation(tmp_path):
    from tools.source_scope import source_decision_for_turn

    source_decision_for_turn(
        SessionStore(tmp_path),
        "thread",
        [HumanMessage(content="Explore EcoTaxa")],
    )

    reopened = SessionStore(tmp_path)
    decision = source_decision_for_turn(
        reopened,
        "thread",
        [HumanMessage(content="résume le projet 17498")],
    )

    assert decision.authorized_sources == ("ecotaxa",)


def test_comparison_persists_combined_sources(tmp_path):
    from tools.source_scope import read_source_affinity, source_decision_for_turn

    store = SessionStore(tmp_path)
    source_decision_for_turn(store, "thread", [HumanMessage(content="Explore EcoTaxa")])
    decision = source_decision_for_turn(
        store,
        "thread",
        [HumanMessage(content="compare avec EcoPart")],
    )

    assert decision.authorized_sources == ("ecotaxa", "ecopart")
    assert read_source_affinity(store, "thread").active_sources == (
        "ecotaxa",
        "ecopart",
    )


def test_explicit_switch_replaces_persisted_source(tmp_path):
    from tools.source_scope import read_source_affinity, source_decision_for_turn

    store = SessionStore(tmp_path)
    source_decision_for_turn(store, "thread", [HumanMessage(content="Explore EcoTaxa")])
    source_decision_for_turn(store, "thread", [HumanMessage(content="passe à EcoPart")])

    assert read_source_affinity(store, "thread").active_sources == ("ecopart",)


def test_file_activation_replaces_external_affinity(tmp_path):
    from tools.source_scope import (
        activate_file_source,
        read_source_affinity,
        source_decision_for_turn,
    )

    store = SessionStore(tmp_path)
    source_decision_for_turn(store, "thread", [HumanMessage(content="Explore EcoTaxa")])

    activate_file_source(store, "thread", origin_user_text="data/table.tsv")

    affinity = read_source_affinity(store, "thread")
    assert affinity.active_sources == ("file",)
    assert affinity.evidence == "file_loaded"


def test_corrupt_affinity_is_ignored_fail_closed(tmp_path):
    from tools.source_scope import read_source_affinity, source_affinity_key

    store = SessionStore(tmp_path)
    store.set(
        source_affinity_key("thread"),
        None,
        {"source_affinity": {"active_sources": ["obis"], "evidence": "guess"}},
    )

    assert read_source_affinity(store, "thread") is None


def test_repeated_same_explicit_turn_is_idempotent(tmp_path):
    from tools.source_scope import read_source_affinity, source_decision_for_turn

    store = SessionStore(tmp_path)
    messages = [HumanMessage(content="Explore EcoTaxa")]
    source_decision_for_turn(store, "thread", messages)
    before = read_source_affinity(store, "thread")

    source_decision_for_turn(store, "thread", messages)

    assert read_source_affinity(store, "thread") == before
