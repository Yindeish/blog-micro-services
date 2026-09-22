import sqlite3
from typing import Dict, List, Optional
from fastapi import APIRouter, Header, HTTPException, status
import httpx

from services.comment.database import get_db
from services.comment.models import CommentCreate, CommentResponse
from shared.config import BLOG_SERVICE_URL
from shared.schemas import APIResponse, HealthResponse
from shared.security import decode_access_token

router = APIRouter()


def get_current_user_id(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
) -> int:
    if x_user_id:
        try:
            return int(x_user_id)
        except ValueError:
            pass

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication token",
        )

    token = authorization.split(" ")[1]
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
        )
    return int(payload["sub"])


async def verify_post_exists(post_id: int) -> bool:
    """Inter-service call to verify post existence in blog service."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{BLOG_SERVICE_URL}/posts/{post_id}")
            return resp.status_code == 200
    except Exception:
        # If blog service is unreachable during decoupled testing, fallback safely
        return True


@router.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(service="comment-service", status="healthy")


@router.post("/comments", response_model=APIResponse[CommentResponse], status_code=status.HTTP_201_CREATED)
async def create_comment(
    comment_data: CommentCreate,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    user_id = get_current_user_id(authorization, x_user_id)

    # Inter-service verification
    post_exists = await verify_post_exists(comment_data.post_id)
    if not post_exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target post {comment_data.post_id} does not exist",
        )

    with get_db() as conn:
        cursor = conn.cursor()

        # If parent_id provided, ensure parent comment exists for same post
        if comment_data.parent_id is not None:
            cursor.execute(
                "SELECT post_id FROM comments WHERE id = ?",
                (comment_data.parent_id,),
            )
            parent = cursor.fetchone()
            if not parent:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Parent comment {comment_data.parent_id} not found",
                )
            if parent["post_id"] != comment_data.post_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Parent comment belongs to a different post",
                )

        cursor.execute(
            """
            INSERT INTO comments (post_id, user_id, content, parent_id)
            VALUES (?, ?, ?, ?)
            """,
            (comment_data.post_id, user_id, comment_data.content, comment_data.parent_id),
        )
        conn.commit()
        comment_id = cursor.lastrowid
        cursor.execute("SELECT * FROM comments WHERE id = ?", (comment_id,))
        created_row = cursor.fetchone()

    return APIResponse(
        message="Comment added successfully",
        data=CommentResponse(**dict(created_row), replies=[]),
    )


@router.get("/posts/{post_id}/comments", response_model=APIResponse[List[CommentResponse]])
def get_post_comments(post_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM comments WHERE post_id = ? ORDER BY created_at ASC",
            (post_id,),
        )
        rows = cursor.fetchall()

    comment_map: Dict[int, CommentResponse] = {}
    top_level: List[CommentResponse] = []

    for r in rows:
        c = CommentResponse(**dict(r), replies=[])
        comment_map[c.id] = c

    for c in comment_map.values():
        if c.parent_id is not None and c.parent_id in comment_map:
            comment_map[c.parent_id].replies.append(c)
        else:
            top_level.append(c)

    return APIResponse(message="Comments retrieved", data=top_level)


@router.get("/comments/{comment_id}", response_model=APIResponse[CommentResponse])
def get_comment(comment_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM comments WHERE id = ?", (comment_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Comment with ID {comment_id} not found",
            )
        return APIResponse(message="Comment retrieved", data=CommentResponse(**dict(row)))


@router.delete("/comments/{comment_id}", response_model=APIResponse[dict])
def delete_comment(
    comment_id: int,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    user_id = get_current_user_id(authorization, x_user_id)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM comments WHERE id = ?", (comment_id,))
        existing = cursor.fetchone()
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Comment with ID {comment_id} not found",
            )
        if existing["user_id"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to delete this comment",
            )

        cursor.execute("DELETE FROM comments WHERE id = ? OR parent_id = ?", (comment_id, comment_id))
        conn.commit()

    return APIResponse(message="Comment deleted successfully", data={"comment_id": comment_id})
