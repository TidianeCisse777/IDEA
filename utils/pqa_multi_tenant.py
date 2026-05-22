# Compatibility shim — module moved to core.rag_store.
# This file is intentionally kept to avoid breaking imports in plugins or
# third-party code that reference utils.pqa_multi_tenant.
from core.rag_store import *  # noqa: F401, F403
from core.rag_store import ensure_user_pqa_settings  # noqa: F401
