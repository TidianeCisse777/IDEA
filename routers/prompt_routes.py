"""
Prompt-management routes.

Covers: list_prompts, get_prompt, create_prompt, update_prompt,
        delete_prompt, set_active_prompt.
"""
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from auth import get_auth_token, get_db, get_current_user
from models import (
    PromptCreateRequest,
    PromptListResponse,
    PromptResponse,
    PromptUpdateRequest,
    SetActivePromptRequest,
)
from utils.prompt_manager import get_prompt_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["prompts"])


@router.get("/prompts", response_model=List[PromptListResponse])
async def list_prompts(
    token: str = Depends(get_auth_token), db: Session = Depends(get_db)
):
    """List all available prompts for the current user"""
    try:
        user = get_current_user(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        prompts = get_prompt_manager().list_prompts(db, user.id)
        return prompts
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing prompts: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list prompts")


@router.get("/prompts/{prompt_id}", response_model=PromptResponse)
async def get_prompt(
    prompt_id: str,
    token: str = Depends(get_auth_token),
    db: Session = Depends(get_db),
):
    """Get a specific prompt by ID for the current user"""
    try:
        user = get_current_user(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        prompt = get_prompt_manager().get_prompt(db, user.id, prompt_id)
        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")
        return prompt
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting prompt {prompt_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get prompt")


@router.post("/prompts", response_model=PromptResponse)
async def create_prompt(
    prompt_data: PromptCreateRequest,
    token: str = Depends(get_auth_token),
    db: Session = Depends(get_db),
):
    """Create a new prompt for the current user"""
    try:
        user = get_current_user(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        new_prompt = get_prompt_manager().create_prompt(
            db,
            user.id,
            name=prompt_data.name,
            description=prompt_data.description,
            content=prompt_data.content,
        )
        return new_prompt
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating prompt: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create prompt")


@router.put("/prompts/{prompt_id}", response_model=PromptResponse)
async def update_prompt(
    prompt_id: str,
    prompt_data: PromptUpdateRequest,
    token: str = Depends(get_auth_token),
    db: Session = Depends(get_db),
):
    """Update an existing prompt for the current user"""
    try:
        user = get_current_user(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        updated_prompt = get_prompt_manager().update_prompt(
            db,
            user.id,
            prompt_id=prompt_id,
            name=prompt_data.name,
            description=prompt_data.description,
            content=prompt_data.content,
        )
        if not updated_prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")
        return updated_prompt
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating prompt {prompt_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update prompt")


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(
    prompt_id: str,
    token: str = Depends(get_auth_token),
    db: Session = Depends(get_db),
):
    """Delete a prompt for the current user"""
    try:
        user = get_current_user(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        success = get_prompt_manager().delete_prompt(db, user.id, prompt_id)
        if not success:
            raise HTTPException(status_code=404, detail="Prompt not found")
        return {"message": "Prompt deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting prompt {prompt_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete prompt")


@router.post("/prompts/set-active")
async def set_active_prompt(
    request: SetActivePromptRequest,
    token: str = Depends(get_auth_token),
    db: Session = Depends(get_db),
):
    """Set a prompt as the active one for the current user"""
    try:
        user = get_current_user(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        success = get_prompt_manager().set_active_prompt(db, user.id, request.prompt_id)
        if not success:
            raise HTTPException(status_code=404, detail="Prompt not found")

        # Clear all existing interpreter instances so they get recreated with the new system message
        from core.interpreter_store import interpreter_instances

        for sk, interp in list(interpreter_instances.items()):
            try:
                interp.reset()
            except Exception as exc:
                logger.error(f"Error resetting interpreter for session {sk}: {exc}")
        interpreter_instances.clear()
        logger.info("Cleared all interpreter instances due to system prompt change")

        return {"message": "Active prompt set successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting active prompt {request.prompt_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to set active prompt")
