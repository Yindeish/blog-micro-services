from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

from services.user.database import init_db
from services.user.routes import router
from shared.config import USER_PORT


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="User Microservice",
    description="Manages users, authentication, and profiles.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


if __name__ == "__main__":
    uvicorn.run("services.user.main:app", host="0.0.0.0", port=USER_PORT, reload=True)
