from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

from services.payment.database import close_db, init_db
from services.payment.routes import router
from shared.config import PAYMENT_PORT


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title="Payment Microservice",
    description="Manages wallets, tipping, post unlocking, and Squad payments via Prisma & Supabase.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


if __name__ == "__main__":
    uvicorn.run("services.payment.main:app", host="0.0.0.0", port=PAYMENT_PORT, reload=True)
