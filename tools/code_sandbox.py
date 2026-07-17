"""Restricted execution namespace for agent-authored pandas/matplotlib code.

Defense-in-depth, not a full sandbox. `run_pandas` / `run_graph` execute code
written by the LLM. Without a restricted namespace that code can reach process
secrets (`os.environ`), the network (`socket`, `urllib`), subprocesses
(`subprocess`) or the filesystem (`open`). This module removes those obvious
paths by:

- replacing `__import__` with a guard that only allows an allowlist of
  scientific/data modules (`pandas`, `numpy`, `matplotlib`, `cartopy`, …);
- dropping dangerous builtins (`open`, `eval`, `exec`, `compile`, `input`,
  `breakpoint`) from the execution namespace.

It is *not* a security boundary against a determined adversary crafting Python
introspection escapes (`().__class__.__bases__…`); the threat model here is the
model's own generated code taking an obvious dangerous path. True process-level
isolation (separate worker, no network, FS quotas) remains the Step 9 goal and
is tracked as such. Notably, library-level egress such as `pd.read_csv(url)` is
NOT blocked by this layer.
"""

from __future__ import annotations

import builtins as _builtins
from typing import Any

# Root modules the executed code may import. Their transitive internal imports
# use the real import machinery (unaffected by this guard); only the top-level
# `import X` statements written by the model are gated here.
ALLOWED_ROOT_MODULES = frozenset(
    {
        "pandas",
        "numpy",
        "math",
        "statistics",
        "datetime",
        "calendar",
        "decimal",
        "fractions",
        "random",
        "string",
        "textwrap",
        "collections",
        "itertools",
        "functools",
        "operator",
        "json",
        "re",
        "warnings",
        "typing",
        "matplotlib",
        "mpl_toolkits",
        "cartopy",
        "shapely",
        "pyproj",
        "scipy",
        "sklearn",
        "statsmodels",
    }
)

# Project analysis contracts the executed code may import. These are pure,
# credential-free scientific helpers. The rest of `core.*` (LLM config, source
# clients, MCP servers, environment resolver) is deliberately NOT reachable, so
# the executed code cannot pull a module that holds connection secrets.
ALLOWED_CORE_MODULES = frozenset(
    {
        "core.copepod_abundance_analysis",
        "core.copepod_sample_depth",
        "core.copepod_taxonomy",
        "core.neolabs_abundance",
    }
)

# Builtins removed from the execution namespace: filesystem and code-eval paths.
BLOCKED_BUILTINS = frozenset(
    {"open", "eval", "exec", "compile", "input", "breakpoint"}
)


class BlockedImportError(ImportError):
    """Raised when executed code imports a module outside the allowlist."""


def _core_module_allowed(name: str) -> bool:
    return any(
        name == allowed or name.startswith(allowed + ".")
        for allowed in ALLOWED_CORE_MODULES
    )


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".", 1)[0]
    permitted = level == 0 and (
        root in ALLOWED_ROOT_MODULES
        or (root == "core" and _core_module_allowed(name))
    )
    if not permitted:
        raise BlockedImportError(
            f"Import of {name!r} is not permitted in controlled execution "
            "(secrets, network, subprocess and filesystem modules are blocked)."
        )
    return _builtins.__import__(name, globals, locals, fromlist, level)


def safe_builtins() -> dict[str, Any]:
    """Return a builtins mapping with dangerous names removed and guarded import."""
    raw = dict(_builtins.__dict__)
    for name in BLOCKED_BUILTINS:
        raw.pop(name, None)
    raw["__import__"] = _guarded_import
    return raw


def apply_restricted_builtins(namespace: dict[str, Any]) -> dict[str, Any]:
    """Install the restricted builtins into an exec namespace, in place.

    Returns the same dict so the caller can still read `result` and other
    variables the executed code assigns.
    """
    namespace["__builtins__"] = safe_builtins()
    return namespace
