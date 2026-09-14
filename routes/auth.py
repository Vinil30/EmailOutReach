from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from database.fxns import (
    authenticate_user,
    create_access_token,
    create_user,
    get_current_user,
    public_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterIn):
    user = create_user(payload.email, payload.password, payload.name)
    token = create_access_token(user["id"])
    return {"access_token": token, "token_type": "bearer", "user": user}


@router.post("/login")
async def login(payload: LoginIn):
    user = authenticate_user(payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    public = public_user(user)
    token = create_access_token(public["id"])
    return {"access_token": token, "token_type": "bearer", "user": public}


@router.get("/me")
async def me(current_user=Depends(get_current_user)):
    return public_user(current_user)
