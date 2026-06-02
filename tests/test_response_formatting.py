from core.response_formatting import format_assistant_text


def test_format_assistant_text_collapses_blank_lines_and_trailing_whitespace():
    raw = "First line.  \n\n\nSecond line.\t\n"
    assert format_assistant_text(raw) == "First line.\n\nSecond line."


def test_format_assistant_text_fixes_obvious_punctuation_spacing():
    raw = "Bonjour,monde!Comment ca va?"
    assert format_assistant_text(raw) == "Bonjour, monde! Comment ca va?"


def test_format_assistant_text_preserves_fenced_code_blocks():
    raw = "Intro.\n```python\nprint('hi')\n```\nOutro."
    assert format_assistant_text(raw) == raw
