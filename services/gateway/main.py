import asyncio
from typing import Any, Dict, Optional
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
import httpx
import uvicorn

from shared.config import (
    BLOG_SERVICE_URL,
    COMMENT_SERVICE_URL,
    GATEWAY_PORT,
    PAYMENT_SERVICE_URL,
    USER_SERVICE_URL,
)
from shared.schemas import APIResponse
from shared.security import decode_access_token

app = FastAPI(
    title="Microservices Blog Platform - API Gateway",
    description="Central entrypoint for User, Blog, Comment, and Payment microservices.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SERVICES = {
    "user": USER_SERVICE_URL,
    "blog": BLOG_SERVICE_URL,
    "comment": COMMENT_SERVICE_URL,
    "payment": PAYMENT_SERVICE_URL,
}


async def forward_request(
    target_base_url: str,
    path: str,
    request: Request,
) -> Response:
    """Forward an incoming client request to a downstream microservice."""
    client = httpx.AsyncClient(base_url=target_base_url, timeout=10.0)
    try:
        url = f"{path}"
        if request.url.query:
            url += f"?{request.url.query}"

        # Prepare headers
        headers = dict(request.headers)
        headers.pop("host", None)
        headers.pop("content-length", None)

        # Inject X-User-Id if bearer token is valid
        auth_header = headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            payload = decode_access_token(token)
            if payload and "sub" in payload:
                headers["x-user-id"] = str(payload["sub"])

        body = await request.body()
        resp = await client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=body,
        )

        response_headers = dict(resp.headers)
        response_headers.pop("content-length", None)
        response_headers.pop("content-encoding", None)

        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=response_headers,
            media_type=resp.headers.get("content-type"),
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service unavailable at {target_base_url}: {str(exc)}",
        )
    finally:
        await client.aclose()


@app.get("/")
def gateway_root():
    return {
        "service": "api-gateway",
        "status": "online",
        "documentation": "/docs",
        "services": SERVICES,
    }


@app.get("/health")
async def aggregated_health():
    """Check health of the gateway and all downstream microservices."""
    async with httpx.AsyncClient(timeout=3.0) as client:
        async def check(name: str, base_url: str) -> Dict[str, Any]:
            try:
                r = await client.get(f"{base_url}/health")
                return {"name": name, "url": base_url, "status": "healthy" if r.status_code == 200 else "unhealthy", "code": r.status_code}
            except Exception as e:
                return {"name": name, "url": base_url, "status": "down", "error": str(e)}

        results = await asyncio.gather(*(check(k, v) for k, v in SERVICES.items()))

    overall = "healthy" if all(r["status"] == "healthy" for r in results) else "degraded"
    return {
        "gateway": "healthy",
        "overall_status": overall,
        "services": {r["name"]: r for r in results},
    }


# Aggregated Composite Endpoint (Backend-For-Frontend pattern)
@app.get("/api/feed/post/{post_id}")
async def get_composite_post_details(
    post_id: int,
    authorization: Optional[str] = Header(None),
):
    """Aggregates post data, author profile, comments, and payment access status in one call."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        # 1. Fetch post
        try:
            post_resp = await client.get(f"{BLOG_SERVICE_URL}/posts/{post_id}")
            if post_resp.status_code != 200:
                raise HTTPException(status_code=post_resp.status_code, detail=f"Post {post_id} not found")
            post_data = post_resp.json().get("data", {})
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Blog service unavailable")

        author_id = post_data.get("author_id")

        # 2. Parallel fetch author profile, comments, and access status
        async def fetch_author():
            try:
                resp = await client.get(f"{USER_SERVICE_URL}/{author_id}")
                return resp.json().get("data") if resp.status_code == 200 else None
            except Exception:
                return None

        async def fetch_comments():
            try:
                resp = await client.get(f"{COMMENT_SERVICE_URL}/posts/{post_id}/comments")
                return resp.json().get("data", []) if resp.status_code == 200 else []
            except Exception:
                return []

        async def fetch_access():
            if not authorization:
                return False
            try:
                resp = await client.get(
                    f"{PAYMENT_SERVICE_URL}/access/{post_id}",
                    headers={"authorization": authorization},
                )
                return resp.json().get("data", {}).get("has_access", False) if resp.status_code == 200 else False
            except Exception:
                return False

        author, comments, has_access = await asyncio.gather(
            fetch_author(),
            fetch_comments(),
            fetch_access(),
        )

    # Protect premium content if user does not own it or has not unlocked it
    content_preview = post_data.get("content")
    if post_data.get("is_premium") and not has_access:
        content_preview = post_data.get("summary") or (content_preview[:200] + "... [Unlock to read full story]")

    return APIResponse(
        message="Composite post details retrieved",
        data={
            "post": {**post_data, "content": content_preview},
            "author": author,
            "comments": comments,
            "has_access": has_access,
        },
    )


# --- Microservice Proxy Routes ---

# User Service Proxy
@app.api_route("/api/users/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def user_proxy(path: str, request: Request):
    return await forward_request(USER_SERVICE_URL, f"/{path}", request)


# Blog Service Proxy
@app.api_route("/api/posts/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
@app.api_route("/api/blogs/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def blog_proxy(path: str, request: Request):
    return await forward_request(BLOG_SERVICE_URL, f"/posts/{path}", request)


@app.api_route("/api/posts", methods=["GET", "POST"])
@app.api_route("/api/blogs", methods=["GET", "POST"])
async def blog_proxy_root(request: Request):
    return await forward_request(BLOG_SERVICE_URL, "/posts", request)


# Comment Service Proxy
@app.api_route("/api/comments/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def comment_proxy(path: str, request: Request):
    return await forward_request(COMMENT_SERVICE_URL, f"/comments/{path}", request)


@app.api_route("/api/comments", methods=["GET", "POST"])
async def comment_proxy_root(request: Request):
    return await forward_request(COMMENT_SERVICE_URL, "/comments", request)


# Payment Service Proxy
@app.api_route("/api/payments/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def payment_proxy(path: str, request: Request):
    return await forward_request(PAYMENT_SERVICE_URL, f"/{path}", request)


if __name__ == "__main__":
    uvicorn.run("services.gateway.main:app", host="0.0.0.0", port=GATEWAY_PORT, reload=True)
