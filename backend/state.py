import os
from pathlib import Path
from typing import Dict

import redis
from interpreter.core.core import OpenInterpreter
from slowapi import Limiter
from slowapi.util import get_remote_address

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# Redis client
redis_client = redis.Redis(host="redis", port=6379, db=0)

# In-memory interpreter instances keyed by session_key (user_id:session_id)
interpreter_instances: Dict[str, OpenInterpreter] = {}

# Session / idle-cleanup constants
IDLE_TIMEOUT = 3600            # 1 hour in seconds
INTERPRETER_PREFIX = "interpreter:"
LAST_ACTIVE_PREFIX = "last_active:"
CLEANUP_INTERVAL = 1800        # Run cleanup every 30 minutes

# Guest user constants
GUEST_EXPIRY_CHECK_INTERVAL_SECONDS = int(os.getenv("GUEST_EXPIRY_CHECK_INTERVAL_SECONDS", "60"))
GUEST_USER_EXPIRY_ZSET = "guest_user_expirations"
GUEST_EMAIL_DOMAIN = "temporary.com"
GUEST_NAME = "Guest User"

# File upload constants
STATIC_DIR = Path("./static")
UPLOAD_DIR = Path("uploads")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_EXTENSIONS = {
    '.csv', '.txt', '.json', '.nc',
    '.xls', '.xlsx', '.doc', '.docx',
    '.ppt', '.pptx', '.pdf', '.md',
    '.mat', '.tif', '.png', '.jpg',
    '.svg', '.py',
}

# Rate limit strings
UPLOAD_RATE_LIMIT = "25/minute"
MAX_UPLOADS_PER_SESSION = 100
CHAT_RATE_LIMIT = "10/minute"


def make_session_key(user_id: str | int, session_id: str) -> str:
    return f"{user_id}:{session_id}"
