from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

from services.blog.database import close_db, init_db
from services.blog.routes import router
from shared.config import BLOG_PORT


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title="Blog Microservice",
    description="Manages blog posts, publishing, and tags via Prisma & Supabase.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


if __name__ == "__main__":
    uvicorn.run("services.blog.main:app", host="0.0.0.0", port=BLOG_PORT, reload=True)
