from typing import Dict, List, Optional
from fastapi import APIRouter, Header, HTTPException, status
import httpx

from services.comment.models import CommentCreate, CommentResponse
from shared.config import BLOG_SERVICE_URL
from shared.prisma_client import get_prisma
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
        return True


@router.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(
        service="comment-service",
        status="healthy",
        details={"orm": "Prisma", "database": "Supabase PostgreSQL"},
    )


@router.post("/comments", response_model=APIResponse[CommentResponse], status_code=status.HTTP_201_CREATED)
async def create_comment(
    comment_data: CommentCreate,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    user_id = get_current_user_id(authorization, x_user_id)

    post_exists = await verify_post_exists(comment_data.post_id)
    if not post_exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target post {comment_data.post_id} does not exist",
        )

    db = await get_prisma()

    if comment_data.parent_id is not None:
        parent = await db.comment.find_unique(where={"id": comment_data.parent_id})
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Parent comment {comment_data.parent_id} not found",
            )
        if parent.post_id != comment_data.post_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent comment belongs to a different post",
            )

    created = await db.comment.create(
        data={
            "post_id": comment_data.post_id,
            "user_id": user_id,
            "content": comment_data.content,
            "parent_id": comment_data.parent_id,
        }
    )

    return APIResponse(
        message="Comment added successfully",
        data=CommentResponse(
            id=created.id,
            post_id=created.post_id,
            user_id=created.user_id,
            content=created.content,
            parent_id=created.parent_id,
            created_at=str(created.created_at),
            replies=[],
        ),
    )


@router.get("/posts/{post_id}/comments", response_model=APIResponse[List[CommentResponse]])
async def get_post_comments(post_id: int):
    db = await get_prisma()
    rows = await db.comment.find_many(
        where={"post_id": post_id},
        order={"created_at": "asc"},
    )

    comment_map: Dict[int, CommentResponse] = {}
    top_level: List[CommentResponse] = []

    for r in rows:
        c = CommentResponse(
            id=r.id,
            post_id=r.post_id,
            user_id=r.user_id,
            content=r.content,
            parent_id=r.parent_id,
            created_at=str(r.created_at),
            replies=[],
        )
        comment_map[c.id] = c

    for c in comment_map.values():
        if c.parent_id is not None and c.parent_id in comment_map:
            comment_map[c.parent_id].replies.append(c)
        else:
            top_level.append(c)

    return APIResponse(message="Comments retrieved", data=top_level)


@router.get("/comments/{comment_id}", response_model=APIResponse[CommentResponse])
async def get_comment(comment_id: int):
    db = await get_prisma()
    row = await db.comment.find_unique(where={"id": comment_id})
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Comment with ID {comment_id} not found",
        )
    return APIResponse(
        message="Comment retrieved",
        data=CommentResponse(
            id=row.id,
            post_id=row.post_id,
            user_id=row.user_id,
            content=row.content,
            parent_id=row.parent_id,
            created_at=str(row.created_at),
        ),
    )


@router.delete("/comments/{comment_id}", response_model=APIResponse[dict])
async def delete_comment(
    comment_id: int,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    user_id = get_current_user_id(authorization, x_user_id)
    db = await get_prisma()

    existing = await db.comment.find_unique(where={"id": comment_id})
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Comment with ID {comment_id} not found",
        )
    if existing.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to delete this comment",
        )

    await db.comment.delete(where={"id": comment_id})
    return APIResponse(message="Comment deleted successfully", data={"comment_id": comment_id})
