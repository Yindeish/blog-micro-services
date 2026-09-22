from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

from services.comment.database import close_db, init_db
from services.comment.routes import router
from shared.config import COMMENT_PORT


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title="Comment Microservice",
    description="Manages comments, threads, and moderation via Prisma & Supabase.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


if __name__ == "__main__":
    uvicorn.run("services.comment.main:app", host="0.0.0.0", port=COMMENT_PORT, reload=True)
