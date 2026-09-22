from typing import Any, Dict, Generic, Optional, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    success: bool = True
    message: str = "Success"
    data: Optional[T] = None


class HealthResponse(BaseModel):
    service: str
    status: str = "healthy"
    version: str = "1.0.0"
    details: Optional[Dict[str, Any]] = None
