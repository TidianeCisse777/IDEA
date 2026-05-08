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

# HPC cluster configuration
HPC_HOST = os.getenv("HPC_HOST")
HPC_USER = os.getenv("HPC_USER")
HPC_SSH_KEY_PATH = os.getenv("HPC_SSH_KEY_PATH")
HPC_SSH_PORT = int(os.getenv("HPC_SSH_PORT", "22"))
HPC_SCRATCH_DIR = os.getenv("HPC_SCRATCH_DIR", "/scratch/idea_jobs")
HPC_DEFAULT_PARTITION = os.getenv("HPC_DEFAULT_PARTITION", "shared")
HPC_DEFAULT_ACCOUNT = os.getenv("HPC_DEFAULT_ACCOUNT", "")
HPC_DEFAULT_WALLTIME = os.getenv("HPC_DEFAULT_WALLTIME", "01:00:00")
HPC_DEFAULT_MEMORY = os.getenv("HPC_DEFAULT_MEMORY", "8G")
HPC_CONDA_ENV = os.getenv("HPC_CONDA_ENV", "")
HPC_MODULES = os.getenv("HPC_MODULES", "")
HPC_MAX_JOBS_PER_USER = int(os.getenv("HPC_MAX_JOBS_PER_USER", "5"))
_HPC_ENABLED_FLAG = os.getenv("HPC_ENABLED", "false").strip().lower()
HPC_ENABLED = _HPC_ENABLED_FLAG == "true" and bool(HPC_HOST and HPC_USER and HPC_SSH_KEY_PATH)


def make_session_key(user_id: str | int, session_id: str) -> str:
    return f"{user_id}:{session_id}"
