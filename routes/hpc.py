import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import get_auth_token, get_current_user
from backend.auth_helpers import _ensure_superuser
from backend.hpc_manager import (
    cancel_hpc_job,
    check_hpc_connection,
    list_hpc_jobs,
)
from backend.state import HPC_ENABLED

router = APIRouter(prefix="/hpc", tags=["hpc"])
logger = logging.getLogger(__name__)


@router.get("/status")
async def hpc_status(token: str = Depends(get_auth_token)):
    """
    Test SSH connectivity to the HPC cluster and return basic cluster info.
    Superuser only.
    """
    user = get_current_user(token)
    _ensure_superuser(user)
    if not HPC_ENABLED:
        return {
            "enabled": False,
            "message": "HPC not configured. Set HPC_HOST, HPC_USER, and HPC_SSH_KEY_PATH.",
        }
    try:
        result = await asyncio.to_thread(check_hpc_connection)
        return {"enabled": True, **result}
    except Exception as exc:
        logger.error("HPC status check error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/jobs")
async def hpc_list_jobs(token: str = Depends(get_auth_token)):
    """
    List all active SLURM jobs for the configured HPC user.
    Superuser only.
    """
    user = get_current_user(token)
    _ensure_superuser(user)
    if not HPC_ENABLED:
        raise HTTPException(status_code=503, detail="HPC not configured.")
    try:
        result = await asyncio.to_thread(list_hpc_jobs)
        return result
    except Exception as exc:
        logger.error("HPC list jobs error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/jobs/{job_id}")
async def hpc_cancel_job(job_id: str, token: str = Depends(get_auth_token)):
    """
    Cancel a running or pending SLURM job by ID.
    Superuser only.
    """
    user = get_current_user(token)
    _ensure_superuser(user)
    if not HPC_ENABLED:
        raise HTTPException(status_code=503, detail="HPC not configured.")
    try:
        result = await asyncio.to_thread(cancel_hpc_job, job_id)
        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("HPC cancel job error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
