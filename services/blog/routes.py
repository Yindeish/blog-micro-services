import time
from typing import List, Optional
from fastapi import APIRouter, Header, HTTPException, Query, status
from prisma import Json

from services.blog.models import PostCreate, PostResponse, PostUpdate, generate_slug
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


def prisma_to_post(p) -> PostResponse:
    tags = p.tags if isinstance(p.tags, list) else []
    return PostResponse(
        id=p.id,
        author_id=p.author_id,
        title=p.title,
        slug=p.slug,
        content=p.content,
        summary=p.summary,
        tags=tags,
        is_published=p.is_published,
        is_premium=p.is_premium,
        price=float(p.price) if p.price is not None else 0.0,
        created_at=str(p.created_at),
        updated_at=str(p.updated_at),
    )


@router.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(
        service="blog-service",
        status="healthy",
        details={"orm": "Prisma", "database": "Supabase PostgreSQL"},
    )


@router.post("/posts", response_model=APIResponse[PostResponse], status_code=status.HTTP_201_CREATED)
async def create_post(
    post_data: PostCreate,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    author_id = get_current_user_id(authorization, x_user_id)
    base_slug = generate_slug(post_data.title)
    slug = f"{base_slug}-{int(time.time())}"
    summary = post_data.summary or (post_data.content[:150] + "..." if len(post_data.content) > 150 else post_data.content)

    db = await get_prisma()
    created = await db.post.create(
        data={
            "author_id": author_id,
            "title": post_data.title,
            "slug": slug,
            "content": post_data.content,
            "summary": summary,
            "tags": Json(post_data.tags),
            "is_published": post_data.is_published,
            "is_premium": post_data.is_premium,
            "price": float(post_data.price),
        }
    )

    return APIResponse(
        message="Post created successfully",
        data=prisma_to_post(created),
    )


@router.get("/posts", response_model=APIResponse[List[PostResponse]])
@router.get("/blogs", response_model=APIResponse[List[PostResponse]])
async def list_posts(
    author_id: Optional[int] = Query(None),
    tag: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    db = await get_prisma()
    where = {"is_published": True}
    if author_id is not None:
        where["author_id"] = author_id

    posts = await db.post.find_many(
        where=where,
        take=limit,
        skip=offset,
        order={"created_at": "desc"},
    )

    # Filter by tag in python if requested
    if tag:
        posts = [p for p in posts if isinstance(p.tags, list) and tag in p.tags]

    return APIResponse(message="Posts retrieved", data=[prisma_to_post(p) for p in posts])


@router.get("/posts/{post_id}", response_model=APIResponse[PostResponse])
@router.get("/blogs/{post_id}", response_model=APIResponse[PostResponse])
async def get_post(post_id: int):
    db = await get_prisma()
    post = await db.post.find_unique(where={"id": post_id})
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post with ID {post_id} not found",
        )
    return APIResponse(message="Post retrieved", data=prisma_to_post(post))


@router.put("/posts/{post_id}", response_model=APIResponse[PostResponse])
async def update_post(
    post_id: int,
    post_data: PostUpdate,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    user_id = get_current_user_id(authorization, x_user_id)
    db = await get_prisma()

    existing = await db.post.find_unique(where={"id": post_id})
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post with ID {post_id} not found",
        )
    if existing.author_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to update this post",
        )

    data = {}
    if post_data.title is not None:
        data["title"] = post_data.title
    if post_data.content is not None:
        data["content"] = post_data.content
    if post_data.summary is not None:
        data["summary"] = post_data.summary
    if post_data.tags is not None:
        data["tags"] = Json(post_data.tags)
    if post_data.is_published is not None:
        data["is_published"] = post_data.is_published
    if post_data.is_premium is not None:
        data["is_premium"] = post_data.is_premium
    if post_data.price is not None:
        data["price"] = float(post_data.price)

    updated = await db.post.update(where={"id": post_id}, data=data)
    return APIResponse(message="Post updated", data=prisma_to_post(updated))


@router.delete("/posts/{post_id}", response_model=APIResponse[dict])
async def delete_post(
    post_id: int,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    user_id = get_current_user_id(authorization, x_user_id)
    db = await get_prisma()

    existing = await db.post.find_unique(where={"id": post_id})
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post with ID {post_id} not found",
        )
    if existing.author_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to delete this post",
        )

    await db.post.delete(where={"id": post_id})
    return APIResponse(message="Post deleted successfully", data={"post_id": post_id})
