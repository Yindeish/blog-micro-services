import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status

from services.user.database import get_db
from services.user.models import TokenResponse, UserLogin, UserRegister, UserResponse
from shared.schemas import APIResponse, HealthResponse
from shared.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

router = APIRouter()


def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
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
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, full_name, bio, created_at FROM users WHERE id = ?", (payload["sub"],))
        user = cursor.fetchone()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        return dict(user)


@router.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(service="user-service", status="healthy")


@router.post("/register", response_model=APIResponse[TokenResponse], status_code=status.HTTP_201_CREATED)
def register(user_data: UserRegister):
    hashed_pwd = hash_password(user_data.password)
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO users (username, email, hashed_password, full_name, bio)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_data.username, user_data.email, hashed_pwd, user_data.full_name, user_data.bio),
            )
            conn.commit()
            user_id = cursor.lastrowid
            
            cursor.execute("SELECT id, username, email, full_name, bio, created_at FROM users WHERE id = ?", (user_id,))
            created_user = dict(cursor.fetchone())
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered",
        )

    token = create_access_token({"sub": created_user["id"], "username": created_user["username"]})
    return APIResponse(
        message="User registered successfully",
        data=TokenResponse(
            access_token=token,
            user=UserResponse(**created_user),
        ),
    )


@router.post("/login", response_model=APIResponse[TokenResponse])
def login(credentials: UserLogin):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, email, hashed_password, full_name, bio, created_at
            FROM users
            WHERE username = ? OR email = ?
            """,
            (credentials.username_or_email, credentials.username_or_email),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username/email or password",
            )
        
        user_dict = dict(row)
        if not verify_password(credentials.password, user_dict["hashed_password"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username/email or password",
            )

    token = create_access_token({"sub": user_dict["id"], "username": user_dict["username"]})
    del user_dict["hashed_password"]
    return APIResponse(
        message="Login successful",
        data=TokenResponse(
            access_token=token,
            user=UserResponse(**user_dict),
        ),
    )


@router.get("/me", response_model=APIResponse[UserResponse])
def get_me(current_user: dict = Depends(get_current_user)):
    return APIResponse(message="Profile retrieved", data=UserResponse(**current_user))


@router.get("/{user_id}", response_model=APIResponse[UserResponse])
def get_user_by_id(user_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, full_name, bio, created_at FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found",
            )
        return APIResponse(message="User found", data=UserResponse(**dict(row)))
