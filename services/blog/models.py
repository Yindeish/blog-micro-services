import re
from typing import List, Optional
from pydantic import BaseModel, Field


def generate_slug(text: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", cleaned)


class PostCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    content: str = Field(..., min_length=10)
    summary: Optional[str] = None
    tags: List[str] = []
    is_published: bool = True
    is_premium: bool = False
    price: float = Field(0.0, ge=0.0)


class PostUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=200)
    content: Optional[str] = Field(None, min_length=10)
    summary: Optional[str] = None
    tags: Optional[List[str]] = None
    is_published: Optional[bool] = None
    is_premium: Optional[bool] = None
    price: Optional[float] = Field(None, ge=0.0)


class PostResponse(BaseModel):
    id: int
    author_id: int
    title: str
    slug: str
    content: str
    summary: Optional[str] = None
    tags: List[str] = []
    is_published: bool
    is_premium: bool
    price: float
    created_at: str
    updated_at: str
