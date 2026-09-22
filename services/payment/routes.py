import sqlite3
import uuid
from typing import List, Optional
from fastapi import APIRouter, Header, HTTPException, status
import httpx

from services.payment.database import get_db
from services.payment.models import (
    AccessPassResponse,
    TipRequest,
    TopUpRequest,
    TransactionResponse,
    UnlockPostRequest,
    WalletResponse,
)
from shared.config import BLOG_SERVICE_URL
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


def get_or_create_wallet(cursor: sqlite3.Cursor, user_id: int) -> dict:
    cursor.execute("SELECT user_id, balance, updated_at FROM wallets WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO wallets (user_id, balance) VALUES (?, 0.0)", (user_id,))
        cursor.execute("SELECT user_id, balance, updated_at FROM wallets WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
    return dict(row)


@router.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(service="payment-service", status="healthy")


@router.get("/wallet", response_model=APIResponse[WalletResponse])
def get_wallet(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    user_id = get_current_user_id(authorization, x_user_id)
    with get_db() as conn:
        cursor = conn.cursor()
        wallet = get_or_create_wallet(cursor, user_id)
        conn.commit()
    return APIResponse(message="Wallet retrieved", data=WalletResponse(**wallet))


@router.post("/topup", response_model=APIResponse[WalletResponse])
def top_up_wallet(
    req: TopUpRequest,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    user_id = get_current_user_id(authorization, x_user_id)
    ref_id = f"TOP-{uuid.uuid4().hex[:10].upper()}"

    with get_db() as conn:
        cursor = conn.cursor()
        wallet = get_or_create_wallet(cursor, user_id)
        new_balance = round(wallet["balance"] + req.amount, 2)

        cursor.execute(
            "UPDATE wallets SET balance = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (new_balance, user_id),
        )
        cursor.execute(
            """
            INSERT INTO transactions (user_id, type, amount, reference_id, description)
            VALUES (?, 'topup', ?, ?, ?)
            """,
            (user_id, req.amount, ref_id, f"Wallet top-up via {req.payment_method}"),
        )
        conn.commit()
        updated_wallet = get_or_create_wallet(cursor, user_id)

    return APIResponse(message="Wallet top-up successful", data=WalletResponse(**updated_wallet))


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
        sender_wallet = get_or_create_wallet(cursor, sender_id)
        if sender_wallet["balance"] < req.amount:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient wallet balance. Current balance: {sender_wallet['balance']}",
            )

        recipient_wallet = get_or_create_wallet(cursor, req.recipient_user_id)

        # Update balances
        cursor.execute(
            "UPDATE wallets SET balance = balance - ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (req.amount, sender_id),
        )
        cursor.execute(
            "UPDATE wallets SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (req.amount, req.recipient_user_id),
        )

        # Audit transactions
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
        message=f"Tip of {req.amount} sent successfully",
        data={"reference_id": ref_id, "amount": req.amount, "recipient_id": req.recipient_user_id},
    )


@router.post("/unlock-post", response_model=APIResponse[AccessPassResponse])
async def unlock_post(
    req: UnlockPostRequest,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
):
    user_id = get_current_user_id(authorization, x_user_id)

    # Check if already unlocked
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, user_id, post_id, amount_paid, created_at FROM access_passes WHERE user_id = ? AND post_id = ?",
            (user_id, req.post_id),
        )
        existing = cursor.fetchone()
        if existing:
            return APIResponse(message="Post already unlocked", data=AccessPassResponse(**dict(existing)))

    # Fetch post metadata from blog service
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
            wallet = get_or_create_wallet(cursor, user_id)
            if wallet["balance"] < price:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Insufficient balance ({wallet['balance']}) to unlock post priced at {price}",
                )

            # Deduct from user
            cursor.execute(
                "UPDATE wallets SET balance = balance - ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (price, user_id),
            )
            # Credit author if known
            if author_id and author_id != user_id:
                get_or_create_wallet(cursor, author_id)
                cursor.execute(
                    "UPDATE wallets SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                    (price, author_id),
                )
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
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        rows = cursor.fetchall()

    txs = [TransactionResponse(**dict(r)) for r in rows]
    return APIResponse(message="Transactions retrieved", data=txs)
