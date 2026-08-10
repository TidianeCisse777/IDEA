"""Regression coverage for the offline checkpoint projection campaign."""

from tempfile import TemporaryDirectory

from scripts.dev import run_context_projection_campaign as campaign
from tools.session_store import SessionStore


def test_long_turn_checks_report_missing_snapshots_without_raising():
    """A truncated run must return normalized failures, not indexing errors."""
    checks = campaign._long_turn_checks(
        (),
        campaign._long_turn_questions(),
        "missing-snapshot-thread",
    )

    assert checks
    assert all(not check.passed for check in checks)
    assert any(check.turn_range == "turn 1" for check in checks)
    assert all(len(check.evidence) <= campaign._MAX_EVIDENCE_CHARS for check in checks)


def test_forced_dependency_continuations_retain_every_provider_capture():
    """Turns with a pending dependency retain every model-bound request."""
    with TemporaryDirectory(prefix="idea-context-projection-test-") as directory:
        store = SessionStore(directory)
        thread_id = "capture-continuations-thread"
        with campaign.offline_only():
            campaign.seed_six_dataframes(store, thread_id)
            snapshots = campaign.run_checkpointed_projection(
                store,
                thread_id,
                campaign._long_turn_questions(20),
                answer_chars=800,
                mutate_before_turn=campaign._mutate_long_turn_context(thread_id),
            )

    continuation_captures = snapshots[-1].captures
    assert len(continuation_captures) > 1
    assert all(
        capture.system == continuation_captures[0].system
        and capture.exact_user_request == campaign.PENDING_WINDOW_QUESTION
        and f"Objective: {campaign.PENDING_WINDOW_QUESTION}" in capture.task_context
        for capture in continuation_captures
    )
    for capture in continuation_captures:
        humans = campaign._human_messages(capture)
        assert sum(
            campaign._content_text(message).count("<application_turn_context>")
            for message in capture.messages
        ) == 1
        assert campaign._content_text(humans[-1]).count(
            "<application_turn_context>"
        ) == 1
        assert all(
            "<application_turn_context>" not in campaign._content_text(message)
            for message in humans[:-1]
        )
