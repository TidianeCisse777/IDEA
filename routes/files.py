import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from backend.auth import get_auth_token, get_current_user
from backend.state import (
    limiter,
    STATIC_DIR,
    UPLOAD_DIR,
    MAX_FILE_SIZE,
    ALLOWED_EXTENSIONS,
    MAX_UPLOADS_PER_SESSION,
    UPLOAD_RATE_LIMIT,
)

router = APIRouter(tags=["files"])
logger = logging.getLogger(__name__)


async def has_executable_header(file_path: Path) -> bool:
    """Check for executable file headers"""
    with open(file_path, "rb") as f:
        header = f.read(4)
        if header.startswith(b'MZ'):
            return True
        if header.startswith(b'\x7fELF'):
            return True
    return False


async def scan_file(file_path: Path) -> tuple[bool, str]:
    """Scan a file for viruses using ClamAV (stub — not yet implemented)"""
    return True, "Virus scan skipped (ClamAV unavailable)"


async def check_session_upload_limit(user_id: str, session_id: str) -> bool:
    """Check if session has reached upload limit"""
    session_dir = STATIC_DIR / str(user_id) / session_id / UPLOAD_DIR
    if not session_dir.exists():
        return True
    file_count = sum(1 for _ in session_dir.glob("*") if _.is_file())
    return file_count < MAX_UPLOADS_PER_SESSION


@router.get("/share/{share_token}")
async def shared_conversation_page(share_token: str):
    """Serve the shared conversation page"""
    frontend_dir = Path(__file__).parent.parent / "frontend"
    share_html_path = frontend_dir / "share.html"

    if not share_html_path.exists():
        raise HTTPException(status_code=404, detail="Share page not found")

    return FileResponse(share_html_path, media_type="text/html")


@router.post("/upload")
@limiter.limit(UPLOAD_RATE_LIMIT)
async def upload_file(
    file: UploadFile = File(...),
    request: Request = None,
    token: str = Depends(get_auth_token),
):
    try:
        session_id = request.headers.get("x-session-id")
        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID required")

        user = get_current_user(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        if not await check_session_upload_limit(str(user.id), session_id):
            raise HTTPException(
                status_code=429,
                detail=f"Upload limit reached. Maximum {MAX_UPLOADS_PER_SESSION} files per session",
            )

        session_dir = STATIC_DIR / str(user.id) / session_id / UPLOAD_DIR
        session_dir.mkdir(parents=True, exist_ok=True)

        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"File type not allowed. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}",
            )

        temp_file = session_dir / f"temp_{file.filename}"
        try:
            file_size = 0
            with temp_file.open("wb") as buffer:
                while chunk := await file.read(8192):
                    file_size += len(chunk)
                    if file_size > MAX_FILE_SIZE:
                        buffer.close()
                        temp_file.unlink()
                        raise HTTPException(
                            status_code=400,
                            detail=f"File too large. Maximum size: {MAX_FILE_SIZE / 1024 / 1024}MB",
                        )
                    buffer.write(chunk)

            if await has_executable_header(temp_file):
                temp_file.unlink()
                raise HTTPException(status_code=400, detail="Executable file detected")

            is_clean, scan_result = await scan_file(temp_file)
            if not is_clean:
                temp_file.unlink()
                raise HTTPException(status_code=400, detail=scan_result)

            final_path = session_dir / file.filename
            temp_file.rename(final_path)

            return {
                "filename": file.filename,
                "size": file_size,
                "path": str(final_path.relative_to(STATIC_DIR / str(user.id) / session_id / UPLOAD_DIR)),
                "scan_result": scan_result,
            }

        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            raise e

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/files/{filename}")
async def delete_file(filename: str, request: Request, token: str = Depends(get_auth_token)):
    try:
        session_id = request.headers.get("x-session-id")
        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID required")

        user = get_current_user(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        file_path = STATIC_DIR / str(user.id) / session_id / UPLOAD_DIR / filename

        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        try:
            file_path.relative_to(STATIC_DIR / str(user.id) / session_id / UPLOAD_DIR)
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        file_path.unlink()
        return {"message": "File deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete file error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/files")
async def list_files(request: Request, token: str = Depends(get_auth_token)):
    try:
        session_id = request.headers.get("x-session-id")
        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID required")

        user = get_current_user(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        session_dir = STATIC_DIR / str(user.id) / session_id / UPLOAD_DIR
        if not session_dir.exists():
            return []

        files = []
        for file_path in session_dir.glob("*"):
            if file_path.is_file():
                files.append({
                    "name": file_path.name,
                    "size": file_path.stat().st_size,
                    "path": str(file_path.relative_to(STATIC_DIR / str(user.id) / session_id / UPLOAD_DIR)),
                })
        return files

    except Exception as e:
        logger.error(f"List files error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/files")
async def delete_all_files(request: Request, token: str = Depends(get_auth_token)):
    try:
        session_id = request.headers.get("x-session-id")
        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID required")

        user = get_current_user(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        session_dir = STATIC_DIR / str(user.id) / session_id / UPLOAD_DIR
        if session_dir.exists():
            for file_path in session_dir.glob("*"):
                if file_path.is_file():
                    file_path.unlink()
            session_dir.rmdir()

        return {"message": "All files deleted successfully"}

    except Exception as e:
        logger.error(f"Delete all files error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
