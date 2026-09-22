from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

from services.payment.database import init_db
from services.payment.routes import router
from shared.config import PAYMENT_PORT


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Payment Microservice",
    description="Manages wallets, tipping, post unlocking, and transaction audit trails.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


if __name__ == "__main__":
    uvicorn.run("services.payment.main:app", host="0.0.0.0", port=PAYMENT_PORT, reload=True)
