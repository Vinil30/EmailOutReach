from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from database.fxns import (
    create_project,
    delete_project,
    get_current_user,
    list_projects,
    public_user,
    set_suppressed_emails,
    update_project,
    update_user_profile,
)
from utils.contacts import EMAIL_PATTERN

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfileIn(BaseModel):
    role: str | None = None
    profile: dict[str, Any] = Field(default_factory=dict)


class ProjectIn(BaseModel):
    name: str
    summary: str
    tech: str = ""
    impact: str = ""
    link: str = ""


class SuppressionIn(BaseModel):
    emails: list[str] = Field(default_factory=list)


@router.get("")
async def get_profile(current_user=Depends(get_current_user)):
    user_id = str(current_user["_id"])
    return {
        "user": public_user(current_user),
        "projects": list_projects(user_id),
        "suppressed_emails": current_user.get("suppressed_emails") or [],
    }


@router.put("")
async def save_profile(payload: ProfileIn, current_user=Depends(get_current_user)):
    return {"user": update_user_profile(str(current_user["_id"]), payload.role, payload.profile)}


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def add_project(payload: ProjectIn, current_user=Depends(get_current_user)):
    return create_project(str(current_user["_id"]), payload.model_dump())


@router.post("/projects/import", status_code=status.HTTP_201_CREATED)
async def import_projects(payload: list[ProjectIn], current_user=Depends(get_current_user)):
    user_id = str(current_user["_id"])
    return {"projects": [create_project(user_id, project.model_dump()) for project in payload[:50]]}


@router.put("/projects/{project_id}")
async def edit_project(project_id: str, payload: ProjectIn, current_user=Depends(get_current_user)):
    return update_project(str(current_user["_id"]), project_id, payload.model_dump())


@router.delete("/projects/{project_id}")
async def remove_project(project_id: str, current_user=Depends(get_current_user)):
    delete_project(str(current_user["_id"]), project_id)
    return {"deleted": project_id}


@router.put("/suppression")
async def save_suppression(payload: SuppressionIn, current_user=Depends(get_current_user)):
    emails = sorted({email.strip().lower() for email in payload.emails if EMAIL_PATTERN.match(email.strip())})
    set_suppressed_emails(str(current_user["_id"]), emails)
    return {"suppressed_emails": emails}
