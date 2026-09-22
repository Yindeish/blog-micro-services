import time
import uuid
from typing import List, Optional
from fastapi import APIRouter, Header, HTTPException, Request, status
import httpx

from services.payment.models import (
    AccessPassResponse,
    InitiatePaymentRequest,
    InitiatePaymentResponse,
    TipRequest,
    TopUpRequest,
    TransactionResponse,
    UnlockPostRequest,
    VerifyPaymentResponse,
    WalletResponse,
)
from services.payment.squad import squad_gateway
from shared.config import BLOG_SERVICE_URL
from shared.prisma_client import get_prisma
from shared.schemas import APIResponse, HealthResponse
from shared.security import decode_access_token

router = APIRouter()


def get_current_user_id(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
) -> int:
    if x_user_id:
        try:
            return int(x_user_id)
        except ValueError:
            pass

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication token",
        )

    token = authorization.split(" ")[1]
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
        )
    return int(payload["sub"])


async def get_or_create_wallet(user_id: int):
    """Fetch wallet via Prisma ORM, or create one if not existing."""
    db = await get_prisma()
    wallet = await db.wallet.find_unique(where={"user_id": user_id})
    if not wallet:
        wallet = await db.wallet.create(
            data={"user_id": user_id, "balance": 0.0, "currency": "NGN"}
        )
    return wallet


async def credit_wallet(user_id: int, amount: float, ref_id: str, description: str):
    """Credit user wallet balance and record transaction using Prisma."""
    db = await get_prisma()
    await get_or_create_wallet(user_id)
    updated = await db.wallet.update(
        where={"user_id": user_id},
        data={"balance": {"increment": amount}},
    )
    await db.transaction.create(
        data={
            "user_id": user_id,
            "type": "topup",
            "amount": amount,
            "reference_id": ref_id,
            "description": description,
            "status": "success",
        }
    )
    return updated


@router.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(
        service="payment-service",
        status="healthy",
        details={"orm": "Prisma", "provider": "Squad (GTCO)", "database": "Supabase PostgreSQL"},
    )


# --- Squad Live Payment Integration ---

@router.post("/initiate-payment", response_model=APIResponse[InitiatePaymentResponse])
async def initiate_squad_payment(
    req: InitiatePaymentRequest,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    """
    Initiate checkout with Squad payment gateway.
    Returns Squad hosted checkout_url for card/bank/transfer payments.
    """
    user_id = get_current_user_id(authorization, x_user_id)
    tx_ref = f"SQ-{user_id}-{int(time.time())}-{uuid.uuid4().hex[:6]}"

    metadata = {
        "user_id": user_id,
        "payment_for": req.payment_for,
        "post_id": req.post_id,
    }

    result = await squad_gateway.initiate_transaction(
        email=req.email,
        amount_naira=req.amount,
        transaction_ref=tx_ref,
        callback_url=req.callback_url,
        metadata=metadata,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Failed to initiate payment with Squad"),
        )

    return APIResponse(
        message="Squad payment initiated successfully",
        data=InitiatePaymentResponse(
            checkout_url=result["checkout_url"],
            transaction_ref=tx_ref,
            amount=req.amount,
            currency="NGN",
        ),
    )


@router.get("/verify/{transaction_ref}", response_model=APIResponse[VerifyPaymentResponse])
async def verify_squad_payment(transaction_ref: str):
    """
    Verify payment status with Squad using transaction_ref.
    Credits user wallet or unlocks premium post when verified.
    """
    result = await squad_gateway.verify_transaction(transaction_ref)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Could not verify transaction with Squad"),
        )

    is_paid = result.get("is_paid", False)
    amount = result.get("amount_naira", 0.0)

    # Extract user_id from transaction reference (format: SQ-{user_id}-...)
    parts = transaction_ref.split("-")
    user_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None

    if is_paid and user_id:
        await credit_wallet(
            user_id=user_id,
            amount=amount,
            ref_id=transaction_ref,
            description=f"Squad payment received: {transaction_ref}",
        )

    return APIResponse(
        message="Transaction verification complete",
        data=VerifyPaymentResponse(
            transaction_ref=transaction_ref,
            status=result.get("status", "unknown"),
            is_paid=is_paid,
            amount=amount,
            description=f"Squad payment status: {result.get('status')}",
        ),
    )


@router.post("/webhook")
async def squad_webhook(request: Request):
    """
    Squad webhook endpoint for asynchronous payment confirmation.
    """
    body = await request.body()
    signature = request.headers.get("x-squad-encrypted-body")

    if not squad_gateway.verify_webhook_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    payload = await request.json()
    event_data = payload.get("data", {})
    transaction_ref = event_data.get("transaction_ref")

    if event_data.get("transaction_status") == "success" and transaction_ref:
        amount_kobo = event_data.get("transaction_amount", 0)
        amount_naira = float(amount_kobo) / 100.0 if amount_kobo else 0.0
        parts = transaction_ref.split("-")
        user_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        if user_id:
            await credit_wallet(
                user_id=user_id,
                amount=amount_naira,
                ref_id=transaction_ref,
                description=f"Squad Webhook Credit ({transaction_ref})",
            )

    return {"status": "success"}


# --- Wallet & Internal Payment Endpoints ---

@router.get("/wallet", response_model=APIResponse[WalletResponse])
async def get_wallet(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    user_id = get_current_user_id(authorization, x_user_id)
    wallet = await get_or_create_wallet(user_id)
    return APIResponse(
        message="Wallet retrieved",
        data=WalletResponse(
            user_id=wallet.user_id,
            balance=float(wallet.balance),
            currency=wallet.currency,
            updated_at=str(wallet.updated_at),
        ),
    )


@router.post("/topup", response_model=APIResponse[WalletResponse])
async def top_up_wallet(
    req: TopUpRequest,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    user_id = get_current_user_id(authorization, x_user_id)
    ref_id = f"TOP-{uuid.uuid4().hex[:10].upper()}"
    updated = await credit_wallet(user_id, req.amount, ref_id, f"Direct wallet top-up via {req.payment_method}")
    return APIResponse(
        message="Wallet top-up successful",
        data=WalletResponse(
            user_id=updated.user_id,
            balance=float(updated.balance),
            currency=updated.currency,
            updated_at=str(updated.updated_at),
        ),
    )


@router.post("/tip", response_model=APIResponse[dict])
async def send_tip(
    req: TipRequest,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    sender_id = get_current_user_id(authorization, x_user_id)
    if sender_id == req.recipient_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot send a tip to yourself",
        )

    db = await get_prisma()
    sender_wallet = await get_or_create_wallet(sender_id)
    if float(sender_wallet.balance) < req.amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient wallet balance. Current balance: ₦{sender_wallet.balance}",
        )

    ref_id = f"TIP-{uuid.uuid4().hex[:10].upper()}"
    desc = req.note or f"Tip for author #{req.recipient_user_id}"

    # Ensure recipient wallet exists
    await get_or_create_wallet(req.recipient_user_id)

    # Perform tip transfer
    await db.wallet.update(where={"user_id": sender_id}, data={"balance": {"decrement": req.amount}})
    await db.wallet.update(where={"user_id": req.recipient_user_id}, data={"balance": {"increment": req.amount}})

    # Record transactions
    await db.transaction.create(
        data={
            "user_id": sender_id,
            "type": "tip_sent",
            "amount": -req.amount,
            "counterparty_id": req.recipient_user_id,
            "reference_id": ref_id,
            "description": desc,
            "status": "success",
        }
    )
    await db.transaction.create(
        data={
            "user_id": req.recipient_user_id,
            "type": "tip_received",
            "amount": req.amount,
            "counterparty_id": sender_id,
            "reference_id": ref_id,
            "description": desc,
            "status": "success",
        }
    )

    return APIResponse(
        message=f"Tip of ₦{req.amount} sent successfully",
        data={"reference_id": ref_id, "amount": req.amount, "recipient_id": req.recipient_user_id},
    )


@router.post("/unlock-post", response_model=APIResponse[AccessPassResponse])
async def unlock_post(
    req: UnlockPostRequest,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    user_id = get_current_user_id(authorization, x_user_id)
    db = await get_prisma()

    existing = await db.accesspass.find_unique(where={"user_id_post_id": {"user_id": user_id, "post_id": req.post_id}})
    if existing:
        return APIResponse(
            message="Post already unlocked",
            data=AccessPassResponse(
                id=existing.id,
                user_id=existing.user_id,
                post_id=existing.post_id,
                amount_paid=float(existing.amount_paid),
                created_at=str(existing.created_at),
            ),
        )

    price = 0.0
    author_id = 0
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{BLOG_SERVICE_URL}/posts/{req.post_id}")
            if resp.status_code == 200:
                post_data = resp.json().get("data", {})
                price = float(post_data.get("price", 0.0))
                author_id = int(post_data.get("author_id", 0))
    except Exception:
        pass

    ref_id = f"POST-{uuid.uuid4().hex[:10].upper()}"

    if price > 0.0:
        wallet = await get_or_create_wallet(user_id)
        if float(wallet.balance) < price:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient balance (₦{wallet.balance}) to unlock post priced at ₦{price}",
            )

        await db.wallet.update(where={"user_id": user_id}, data={"balance": {"decrement": price}})
        if author_id and author_id != user_id:
            await get_or_create_wallet(author_id)
            await db.wallet.update(where={"user_id": author_id}, data={"balance": {"increment": price}})
            await db.transaction.create(
                data={
                    "user_id": author_id,
                    "type": "post_sale",
                    "amount": price,
                    "counterparty_id": user_id,
                    "reference_id": ref_id,
                    "description": f"Sold access to post #{req.post_id}",
                    "status": "success",
                }
            )

        await db.transaction.create(
            data={
                "user_id": user_id,
                "type": "post_purchase",
                "amount": -price,
                "counterparty_id": author_id,
                "reference_id": ref_id,
                "description": f"Unlocked post #{req.post_id}",
                "status": "success",
            }
        )

    created_pass = await db.accesspass.create(
        data={
            "user_id": user_id,
            "post_id": req.post_id,
            "amount_paid": price,
        }
    )

    return APIResponse(
        message="Post unlocked successfully",
        data=AccessPassResponse(
            id=created_pass.id,
            user_id=created_pass.user_id,
            post_id=created_pass.post_id,
            amount_paid=float(created_pass.amount_paid),
            created_at=str(created_pass.created_at),
        ),
    )


@router.get("/access/{post_id}", response_model=APIResponse[dict])
async def check_post_access(
    post_id: int,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    try:
        user_id = get_current_user_id(authorization, x_user_id)
    except HTTPException:
        return APIResponse(message="Access checked", data={"has_access": False, "post_id": post_id})

    db = await get_prisma()
    row = await db.accesspass.find_unique(where={"user_id_post_id": {"user_id": user_id, "post_id": post_id}})
    return APIResponse(message="Access checked", data={"has_access": row is not None, "post_id": post_id})


@router.get("/transactions", response_model=APIResponse[List[TransactionResponse]])
async def get_transactions(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    user_id = get_current_user_id(authorization, x_user_id)
    db = await get_prisma()
    rows = await db.transaction.find_many(where={"user_id": user_id}, order={"created_at": "desc"})

    txs = [
        TransactionResponse(
            id=r.id,
            user_id=r.user_id,
            type=r.type,
            amount=float(r.amount),
            counterparty_id=r.counterparty_id,
            reference_id=r.reference_id,
            description=r.description,
            status=r.status,
            created_at=str(r.created_at),
        )
        for r in rows
    ]
    return APIResponse(message="Transactions retrieved", data=txs)
