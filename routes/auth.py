from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from database.admin import apply_pending_premium
from database.fxns import (
    authenticate_user,
    create_access_token,
    create_user,
    get_current_user,
    get_user_by_email,
    public_user,
    sign_legal_documents,
)
from utils.legal import clean_signature

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str | None = None
    role: str = "student"
    accept_terms: bool = False
    signature: str | None = None


def client_ip(request: Request) -> str | None:
    # Render and most hosts put the real client first in X-Forwarded-For.
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else None)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterIn, request: Request):
    if not payload.accept_terms:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agree to the Terms and Privacy Policy to create an account")
    signature = clean_signature(payload.signature)
    user = create_user(payload.email, payload.password, payload.name or signature, payload.role)
    sign_legal_documents(user["id"], signature, client_ip(request), request.headers.get("user-agent"))
    apply_pending_premium(get_user_by_email(payload.email))
    user = public_user(get_user_by_email(payload.email))
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
