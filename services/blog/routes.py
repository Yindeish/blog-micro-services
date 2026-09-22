import json
import sqlite3
import time
from typing import List, Optional
from fastapi import APIRouter, Header, HTTPException, Query, status

from services.blog.database import get_db
from services.blog.models import PostCreate, PostResponse, PostUpdate, generate_slug
from shared.schemas import APIResponse, HealthResponse
from shared.security import decode_access_token

router = APIRouter()


def get_current_user_id(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
) -> int:
    # Check gateway forwarded user id first
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


def row_to_post(row: sqlite3.Row) -> PostResponse:
    d = dict(row)
    d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
    d["is_published"] = bool(d["is_published"])
    d["is_premium"] = bool(d["is_premium"])
    return PostResponse(**d)


@router.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(service="blog-service", status="healthy")


@router.post("/posts", response_model=APIResponse[PostResponse], status_code=status.HTTP_201_CREATED)
def create_post(
    post_data: PostCreate,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    author_id = get_current_user_id(authorization, x_user_id)
    base_slug = generate_slug(post_data.title)
    slug = f"{base_slug}-{int(time.time())}"
    tags_json = json.dumps(post_data.tags)
    summary = post_data.summary or (post_data.content[:150] + "..." if len(post_data.content) > 150 else post_data.content)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO posts (author_id, title, slug, content, summary, tags, is_published, is_premium, price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                author_id,
                post_data.title,
                slug,
                post_data.content,
                summary,
                tags_json,
                int(post_data.is_published),
                int(post_data.is_premium),
                post_data.price,
            ),
        )
        conn.commit()
        post_id = cursor.lastrowid
        cursor.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
        created_row = cursor.fetchone()

    return APIResponse(
        message="Post created successfully",
        data=row_to_post(created_row),
    )


@router.get("/posts", response_model=APIResponse[List[PostResponse]])
@router.get("/blogs", response_model=APIResponse[List[PostResponse]])
def list_posts(
    author_id: Optional[int] = Query(None),
    tag: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    query = "SELECT * FROM posts WHERE is_published = 1"
    params = []

    if author_id is not None:
        query += " AND author_id = ?"
        params.append(author_id)

    if tag:
        query += " AND tags LIKE ?"
        params.append(f'%"{tag}"%')

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

    posts = [row_to_post(r) for r in rows]
    return APIResponse(message="Posts retrieved", data=posts)


@router.get("/posts/{post_id}", response_model=APIResponse[PostResponse])
@router.get("/blogs/{post_id}", response_model=APIResponse[PostResponse])
def get_post(post_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Post with ID {post_id} not found",
            )
        return APIResponse(message="Post retrieved", data=row_to_post(row))


@router.put("/posts/{post_id}", response_model=APIResponse[PostResponse])
def update_post(
    post_id: int,
    post_data: PostUpdate,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    user_id = get_current_user_id(authorization, x_user_id)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
        existing = cursor.fetchone()
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Post with ID {post_id} not found",
            )
        if existing["author_id"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to update this post",
            )

        updates = []
        params = []
        if post_data.title is not None:
            updates.append("title = ?")
            params.append(post_data.title)
        if post_data.content is not None:
            updates.append("content = ?")
            params.append(post_data.content)
        if post_data.summary is not None:
            updates.append("summary = ?")
            params.append(post_data.summary)
        if post_data.tags is not None:
            updates.append("tags = ?")
            params.append(json.dumps(post_data.tags))
        if post_data.is_published is not None:
            updates.append("is_published = ?")
            params.append(int(post_data.is_published))
        if post_data.is_premium is not None:
            updates.append("is_premium = ?")
            params.append(int(post_data.is_premium))
        if post_data.price is not None:
            updates.append("price = ?")
            params.append(post_data.price)

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            sql = f"UPDATE posts SET {', '.join(updates)} WHERE id = ?"
            params.append(post_id)
            cursor.execute(sql, params)
            conn.commit()

        cursor.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
        updated_row = cursor.fetchone()

    return APIResponse(message="Post updated", data=row_to_post(updated_row))


@router.delete("/posts/{post_id}", response_model=APIResponse[dict])
def delete_post(
    post_id: int,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    user_id = get_current_user_id(authorization, x_user_id)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
        existing = cursor.fetchone()
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Post with ID {post_id} not found",
            )
        if existing["author_id"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to delete this post",
            )

        cursor.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        conn.commit()

    return APIResponse(message="Post deleted successfully", data={"post_id": post_id})
