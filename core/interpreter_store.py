"""
Shared interpreter instance store.

A single module-level dict is used so that routers/chat_routes.py and
cleanup helpers can all reference the same mapping without circular imports.
"""
from typing import Dict
from interpreter.core.core import OpenInterpreter

# Global dictionary to store interpreter instances.
# Not thread-safe, but acceptable for the current proof-of-concept scale.
interpreter_instances: Dict[str, OpenInterpreter] = {}
