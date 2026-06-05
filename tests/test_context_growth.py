"""Tests for scripts/context_growth.py — _parse_turns_log and helpers."""

import textwrap
from pathlib import Path

import pytest

# Import the functions under test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from context_growth import _parse_turns_log, _bar, _fmt


# ---------------------------------------------------------------------------
# Fixtures — synthetic turns.log content
# ---------------------------------------------------------------------------

def _make_turn(
    idx: int,
    user: str = "test message",
    had_code: bool = False,
    ctx_tok: int | None = None,
    ctx_chars: int | None = None,
    prompt_tok: int | None = None,
    completion_tok: int | None = None,
    duration_ms: float = 1000.0,
) -> str:
    code_section = "  [CODE]  import pandas as pd" if had_code else "  []"
    ctx_part = ""
    if ctx_tok is not None and ctx_chars is not None:
        ctx_part += f" ctx_payload≈{ctx_tok}tok ({ctx_chars}ch)"
    if prompt_tok is not None:
        ctx_part += f" | prompt={prompt_tok}tok"
    if completion_tok is not None:
        ctx_part += f" | completion={completion_tok}tok"
    return textwrap.dedent(f"""\
        === TURN {idx} session=session-test agent=copepod ===
        --- USER ---
        {user}

        --- TOOL CALLS ---
          []

        --- TOOL STATUS ---
          []

        --- GENERATED CODE ---
        {code_section}

        --- ARTIFACTS ---
          []

        --- ERRORS ---
          []

        --- ASSISTANT ---
        Some assistant response.

        --- TURN END ---
        status=ok duration_ms={duration_ms} retries=0{ctx_part}

    """)


@pytest.fixture()
def log_with_ctx(tmp_path: Path) -> Path:
    content = (
        _make_turn(1, "upload file", had_code=True, ctx_tok=4200, ctx_chars=16800, prompt_tok=4500, completion_tok=300)
        + _make_turn(2, "trace salinité vs temp", had_code=False, ctx_tok=9800, ctx_chars=39200, prompt_tok=10200, completion_tok=180)
        + _make_turn(3, "ok vasy", had_code=True, ctx_tok=14100, ctx_chars=56400, prompt_tok=14600, completion_tok=420)
    )
    p = tmp_path / "turns.log"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture()
def log_without_ctx(tmp_path: Path) -> Path:
    content = (
        _make_turn(1, "upload file", had_code=True)
        + _make_turn(2, "trace salinité vs temp", had_code=False)
    )
    p = tmp_path / "turns.log"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture()
def log_partial_ctx(tmp_path: Path) -> Path:
    """Some turns have ctx data, some don't (mixed log — old + new format)."""
    content = (
        _make_turn(1, "old turn", had_code=True)
        + _make_turn(2, "new turn", had_code=False, ctx_tok=8000, ctx_chars=32000, prompt_tok=8400, completion_tok=200)
    )
    p = tmp_path / "turns.log"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# _parse_turns_log
# ---------------------------------------------------------------------------

class TestParseTurnsLog:
    def test_returns_correct_turn_count(self, log_with_ctx):
        turns = _parse_turns_log(log_with_ctx)
        assert len(turns) == 3

    def test_turns_sorted_by_index(self, log_with_ctx):
        turns = _parse_turns_log(log_with_ctx)
        assert [t["turn"] for t in turns] == [1, 2, 3]

    def test_user_message_extracted(self, log_with_ctx):
        turns = _parse_turns_log(log_with_ctx)
        assert turns[1]["user"] == "trace salinité vs temp"

    def test_had_code_true_when_code_block_present(self, log_with_ctx):
        turns = _parse_turns_log(log_with_ctx)
        assert turns[0]["had_code"] is True

    def test_had_code_false_when_no_code_block(self, log_with_ctx):
        turns = _parse_turns_log(log_with_ctx)
        assert turns[1]["had_code"] is False

    def test_ctx_tok_parsed(self, log_with_ctx):
        turns = _parse_turns_log(log_with_ctx)
        assert turns[0]["ctx_tok"] == 4200
        assert turns[1]["ctx_tok"] == 9800
        assert turns[2]["ctx_tok"] == 14100

    def test_ctx_chars_parsed(self, log_with_ctx):
        turns = _parse_turns_log(log_with_ctx)
        assert turns[0]["ctx_chars"] == 16800

    def test_prompt_tok_parsed(self, log_with_ctx):
        turns = _parse_turns_log(log_with_ctx)
        assert turns[0]["prompt_tok"] == 4500
        assert turns[1]["prompt_tok"] == 10200

    def test_completion_tok_parsed(self, log_with_ctx):
        turns = _parse_turns_log(log_with_ctx)
        assert turns[0]["completion_tok"] == 300

    def test_duration_ms_parsed(self, log_with_ctx):
        turns = _parse_turns_log(log_with_ctx)
        assert turns[0]["duration_ms"] == 1000.0

    def test_no_ctx_data_returns_none(self, log_without_ctx):
        turns = _parse_turns_log(log_without_ctx)
        assert turns[0]["ctx_tok"] is None
        assert turns[0]["prompt_tok"] is None
        assert turns[0]["completion_tok"] is None

    def test_partial_ctx_mixed_none_and_values(self, log_partial_ctx):
        turns = _parse_turns_log(log_partial_ctx)
        assert turns[0]["ctx_tok"] is None
        assert turns[1]["ctx_tok"] == 8000

    def test_empty_file_returns_empty_list(self, tmp_path):
        p = tmp_path / "turns.log"
        p.write_text("", encoding="utf-8")
        assert _parse_turns_log(p) == []

    def test_user_message_truncated_at_60_chars(self, tmp_path):
        long_msg = "a" * 100
        p = tmp_path / "turns.log"
        p.write_text(_make_turn(1, long_msg), encoding="utf-8")
        turns = _parse_turns_log(p)
        assert len(turns[0]["user"]) == 60

    def test_context_grows_across_turns(self, log_with_ctx):
        turns = _parse_turns_log(log_with_ctx)
        ctx_values = [t["ctx_tok"] for t in turns]
        assert ctx_values == sorted(ctx_values), "context should grow monotonically"


# ---------------------------------------------------------------------------
# _bar
# ---------------------------------------------------------------------------

class TestBar:
    def test_full_bar_at_max(self):
        bar = _bar(100, 100, width=10)
        assert bar == "█" * 10

    def test_empty_bar_at_zero(self):
        bar = _bar(0, 100, width=10)
        assert bar == "░" * 10

    def test_half_bar(self):
        bar = _bar(50, 100, width=10)
        assert bar.count("█") == 5
        assert bar.count("░") == 5

    def test_none_value_returns_spaces(self):
        bar = _bar(None, 100, width=10)
        assert bar == " " * 10

    def test_zero_max_returns_spaces(self):
        bar = _bar(50, 0, width=10)
        assert bar == " " * 10

    def test_bar_length_always_equals_width(self):
        for v in [0, 1, 50, 99, 100]:
            bar = _bar(v, 100, width=20)
            assert len(bar) == 20


# ---------------------------------------------------------------------------
# _fmt
# ---------------------------------------------------------------------------

class TestFmt:
    def test_none_returns_dash(self):
        assert "—" in _fmt(None)

    def test_number_formatted(self):
        result = _fmt(1234)
        assert "1234" in result

    def test_unit_appended(self):
        result = _fmt(42, "tok")
        assert "42" in result
        assert "tok" in result
