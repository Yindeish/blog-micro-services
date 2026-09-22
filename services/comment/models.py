from typing import List, Optional
from pydantic import BaseModel, Field


class CommentCreate(BaseModel):
    post_id: int
    content: str = Field(..., min_length=1, max_length=2000)
    parent_id: Optional[int] = None


class CommentResponse(BaseModel):
    id: int
    post_id: int
    user_id: int
    content: str
    parent_id: Optional[int] = None
    created_at: str
    replies: Optional[List["CommentResponse"]] = []
