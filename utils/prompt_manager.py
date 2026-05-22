# Compatibility shim — module moved to core.prompt_store.
# This file is intentionally kept to avoid breaking imports in plugins or
# third-party code that reference utils.prompt_manager.
from core.prompt_store import *  # noqa: F401, F403
from core.prompt_store import init_prompt_manager, get_prompt_manager  # noqa: F401
