from typing import Optional
from pydantic import BaseModel, Field


class TopUpRequest(BaseModel):
    amount: float = Field(..., gt=0.0, description="Amount to top up into wallet")
    payment_method: str = Field("card", description="Payment method: card, bank_transfer, crypto")


class TipRequest(BaseModel):
    recipient_user_id: int
    amount: float = Field(..., gt=0.0)
    post_id: Optional[int] = None
    note: Optional[str] = None


class UnlockPostRequest(BaseModel):
    post_id: int


class WalletResponse(BaseModel):
    user_id: int
    balance: float
    updated_at: str


class TransactionResponse(BaseModel):
    id: int
    user_id: int
    type: str
    amount: float
    counterparty_id: Optional[int] = None
    reference_id: Optional[str] = None
    description: Optional[str] = None
    created_at: str


class AccessPassResponse(BaseModel):
    id: int
    user_id: int
    post_id: int
    amount_paid: float
    created_at: str
