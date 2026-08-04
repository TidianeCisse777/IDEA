"""Security boundary contracts for controlled analysis execution."""

from tools.code_sandbox import apply_restricted_builtins


def test_controlled_execution_allows_standard_time_module():
    """Matplotlib helpers may use time without granting filesystem access."""
    namespace: dict[str, object] = {}
    apply_restricted_builtins(namespace)

    exec("import time\nresult = time.monotonic()", namespace)  # noqa: S102

    assert isinstance(namespace["result"], float)
