import sqlite3
import time
import uuid
from typing import List, Optional
from fastapi import APIRouter, Header, HTTPException, Request, status
import httpx

from services.payment.database import get_db
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
from shared.schemas import APIResponse, HealthResponse
from shared.security import decode_access_token
from shared.supabase_client import supabase

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


async def db_get_or_create_wallet(user_id: int) -> dict:
    """Get or create wallet from Supabase with SQLite fallback."""
    try:
        row = await supabase.single("wallets", {"user_id": user_id})
        if row:
            return row
        new_wallet = {"user_id": user_id, "balance": 0.0, "currency": "NGN"}
        inserted = await supabase.insert("wallets", new_wallet)
        if inserted:
            return inserted
    except Exception:
        pass

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, balance, 'NGN' as currency, updated_at FROM wallets WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            cursor.execute("INSERT INTO wallets (user_id, balance) VALUES (?, 0.0)", (user_id,))
            cursor.execute("SELECT user_id, balance, 'NGN' as currency, updated_at FROM wallets WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
        conn.commit()
    return dict(row)


async def db_credit_wallet(user_id: int, amount: float, ref_id: str, description: str):
    """Credit wallet and record transaction in Supabase and SQLite."""
    try:
        wallet = await db_get_or_create_wallet(user_id)
        new_bal = round(float(wallet.get("balance", 0.0)) + amount, 2)
        await supabase.update("wallets", {"user_id": user_id}, {"balance": new_bal})
        await supabase.insert(
            "transactions",
            {
                "user_id": user_id,
                "type": "topup",
                "amount": amount,
                "reference_id": ref_id,
                "description": description,
                "status": "success",
            },
        )
    except Exception:
        pass

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE wallets SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (amount, user_id))
        cursor.execute(
            """
            INSERT INTO transactions (user_id, type, amount, reference_id, description)
            VALUES (?, 'topup', ?, ?, ?)
            """,
            (user_id, amount, ref_id, description),
        )
        conn.commit()


@router.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(
        service="payment-service",
        status="healthy",
        details={"provider": "Squad (GTCO)", "database": "Supabase + SQLite fallback"},
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
        await db_credit_wallet(
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
            await db_credit_wallet(
                user_id=user_id,
                amount=amount_naira,
                ref_id=transaction_ref,
                description=f"Squad Webhook Credit ({transaction_ref})",
            )

    return {"status": "success"}


# --- Existing Wallet & Internal Flow Endpoints ---

@router.get("/wallet", response_model=APIResponse[WalletResponse])
async def get_wallet(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    user_id = get_current_user_id(authorization, x_user_id)
    wallet = await db_get_or_create_wallet(user_id)
    return APIResponse(
        message="Wallet retrieved",
        data=WalletResponse(
            user_id=wallet["user_id"],
            balance=float(wallet.get("balance", 0.0)),
            currency=wallet.get("currency", "NGN"),
            updated_at=str(wallet.get("updated_at", "")),
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
    await db_credit_wallet(user_id, req.amount, ref_id, f"Direct wallet top-up via {req.payment_method}")
    wallet = await db_get_or_create_wallet(user_id)
    return APIResponse(
        message="Wallet top-up successful",
        data=WalletResponse(
            user_id=wallet["user_id"],
            balance=float(wallet.get("balance", 0.0)),
            currency="NGN",
            updated_at=str(wallet.get("updated_at", "")),
        ),
    )


@router.post("/tip", response_model=APIResponse[dict])
def send_tip(
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

    ref_id = f"TIP-{uuid.uuid4().hex[:10].upper()}"

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, balance FROM wallets WHERE user_id = ?", (sender_id,))
        sender_row = cursor.fetchone()
        if not sender_row or sender_row["balance"] < req.amount:
            bal = sender_row["balance"] if sender_row else 0.0
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient wallet balance. Current balance: {bal}",
            )

        cursor.execute("UPDATE wallets SET balance = balance - ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (req.amount, sender_id))
        cursor.execute("INSERT OR IGNORE INTO wallets (user_id, balance) VALUES (?, 0.0)", (req.recipient_user_id,))
        cursor.execute("UPDATE wallets SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (req.amount, req.recipient_user_id))

        desc = req.note or f"Tip for author #{req.recipient_user_id}"
        cursor.execute(
            """
            INSERT INTO transactions (user_id, type, amount, counterparty_id, reference_id, description)
            VALUES (?, 'tip_sent', ?, ?, ?, ?)
            """,
            (sender_id, -req.amount, req.recipient_user_id, ref_id, desc),
        )
        cursor.execute(
            """
            INSERT INTO transactions (user_id, type, amount, counterparty_id, reference_id, description)
            VALUES (?, 'tip_received', ?, ?, ?, ?)
            """,
            (req.recipient_user_id, req.amount, sender_id, ref_id, desc),
        )
        conn.commit()

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

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, user_id, post_id, amount_paid, created_at FROM access_passes WHERE user_id = ? AND post_id = ?",
            (user_id, req.post_id),
        )
        existing = cursor.fetchone()
        if existing:
            return APIResponse(message="Post already unlocked", data=AccessPassResponse(**dict(existing)))

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

    with get_db() as conn:
        cursor = conn.cursor()
        if price > 0.0:
            cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,))
            wallet = cursor.fetchone()
            if not wallet or wallet["balance"] < price:
                bal = wallet["balance"] if wallet else 0.0
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Insufficient balance ({bal}) to unlock post priced at ₦{price}",
                )

            cursor.execute("UPDATE wallets SET balance = balance - ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (price, user_id))
            if author_id and author_id != user_id:
                cursor.execute("INSERT OR IGNORE INTO wallets (user_id, balance) VALUES (?, 0.0)", (author_id,))
                cursor.execute("UPDATE wallets SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (price, author_id))
                cursor.execute(
                    """
                    INSERT INTO transactions (user_id, type, amount, counterparty_id, reference_id, description)
                    VALUES (?, 'post_sale', ?, ?, ?, ?)
                    """,
                    (author_id, price, user_id, ref_id, f"Sold access to post #{req.post_id}"),
                )

            cursor.execute(
                """
                INSERT INTO transactions (user_id, type, amount, counterparty_id, reference_id, description)
                VALUES (?, 'post_purchase', ?, ?, ?, ?)
                """,
                (user_id, -price, author_id, ref_id, f"Unlocked post #{req.post_id}"),
            )

        cursor.execute(
            """
            INSERT INTO access_passes (user_id, post_id, amount_paid)
            VALUES (?, ?, ?)
            """,
            (user_id, req.post_id, price),
        )
        pass_id = cursor.lastrowid
        cursor.execute("SELECT id, user_id, post_id, amount_paid, created_at FROM access_passes WHERE id = ?", (pass_id,))
        created_pass = cursor.fetchone()
        conn.commit()

    return APIResponse(message="Post unlocked successfully", data=AccessPassResponse(**dict(created_pass)))


@router.get("/access/{post_id}", response_model=APIResponse[dict])
def check_post_access(
    post_id: int,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    try:
        user_id = get_current_user_id(authorization, x_user_id)
    except HTTPException:
        return APIResponse(message="Access checked", data={"has_access": False, "post_id": post_id})

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM access_passes WHERE user_id = ? AND post_id = ?",
            (user_id, post_id),
        )
        has_access = cursor.fetchone() is not None

    return APIResponse(message="Access checked", data={"has_access": has_access, "post_id": post_id})


@router.get("/transactions", response_model=APIResponse[List[TransactionResponse]])
def get_transactions(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    user_id = get_current_user_id(authorization, x_user_id)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, user_id, type, amount, counterparty_id, reference_id, description, 'success' as status, created_at FROM transactions WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        rows = cursor.fetchall()

    txs = [TransactionResponse(**dict(r)) for r in rows]
    return APIResponse(message="Transactions retrieved", data=txs)
