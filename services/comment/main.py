from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

from services.comment.database import init_db
from services.comment.routes import router
from shared.config import COMMENT_PORT


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Comment Microservice",
    description="Manages comments, threads, and moderation for blog posts.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


if __name__ == "__main__":
    uvicorn.run("services.comment.main:app", host="0.0.0.0", port=COMMENT_PORT, reload=True)
