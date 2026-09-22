from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status

from services.user.models import TokenResponse, UserLogin, UserRegister, UserResponse
from shared.prisma_client import get_prisma
from shared.schemas import APIResponse, HealthResponse
from shared.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

router = APIRouter()


async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
        )
    token = authorization.split(" ")[1]
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    db = await get_prisma()
    user = await db.user.find_unique(where={"id": int(payload["sub"])})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "bio": user.bio,
        "created_at": str(user.created_at),
    }


@router.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(
        service="user-service",
        status="healthy",
        details={"orm": "Prisma", "database": "Supabase PostgreSQL"},
    )


@router.post("/register", response_model=APIResponse[TokenResponse], status_code=status.HTTP_201_CREATED)
async def register(user_data: UserRegister):
    hashed_pwd = hash_password(user_data.password)
    db = await get_prisma()

    # Check existing user
    existing = await db.user.find_first(
        where={
            "OR": [
                {"username": user_data.username},
                {"email": user_data.email},
            ]
        }
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered",
        )

    created_user = await db.user.create(
        data={
            "username": user_data.username,
            "email": user_data.email,
            "hashed_password": hashed_pwd,
            "full_name": user_data.full_name,
            "bio": user_data.bio,
        }
    )

    user_resp = UserResponse(
        id=created_user.id,
        username=created_user.username,
        email=created_user.email,
        full_name=created_user.full_name,
        bio=created_user.bio,
        created_at=str(created_user.created_at),
    )
    token = create_access_token({"sub": created_user.id, "username": created_user.username})

    return APIResponse(
        message="User registered successfully",
        data=TokenResponse(access_token=token, user=user_resp),
    )


@router.post("/login", response_model=APIResponse[TokenResponse])
async def login(credentials: UserLogin):
    db = await get_prisma()
    user = await db.user.find_first(
        where={
            "OR": [
                {"username": credentials.username_or_email},
                {"email": credentials.username_or_email},
            ]
        }
    )
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username/email or password",
        )

    user_resp = UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        bio=user.bio,
        created_at=str(user.created_at),
    )
    token = create_access_token({"sub": user.id, "username": user.username})

    return APIResponse(
        message="Login successful",
        data=TokenResponse(access_token=token, user=user_resp),
    )


@router.get("/me", response_model=APIResponse[UserResponse])
def get_me(current_user: dict = Depends(get_current_user)):
    return APIResponse(message="Profile retrieved", data=UserResponse(**current_user))


@router.get("/{user_id}", response_model=APIResponse[UserResponse])
async def get_user_by_id(user_id: int):
    db = await get_prisma()
    user = await db.user.find_unique(where={"id": user_id})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found",
        )
    return APIResponse(
        message="User found",
        data=UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            bio=user.bio,
            created_at=str(user.created_at),
        ),
    )
