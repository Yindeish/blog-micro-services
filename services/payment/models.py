from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class InitiatePaymentRequest(BaseModel):
    amount: float = Field(..., gt=0.0, description="Amount in Naira (NGN)")
    email: EmailStr = Field(..., description="Customer email address")
    payment_for: str = Field("wallet_topup", description="'wallet_topup' or 'unlock_post'")
    post_id: Optional[int] = Field(None, description="Required if payment_for is unlock_post")
    callback_url: Optional[str] = Field(None, description="URL redirect after payment")


class InitiatePaymentResponse(BaseModel):
    checkout_url: str
    transaction_ref: str
    amount: float
    currency: str = "NGN"


class VerifyPaymentResponse(BaseModel):
    transaction_ref: str
    status: str
    is_paid: bool
    amount: float
    description: Optional[str] = None


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
    currency: str = "NGN"
    updated_at: str


class TransactionResponse(BaseModel):
    id: int
    user_id: int
    type: str
    amount: float
    counterparty_id: Optional[int] = None
    reference_id: Optional[str] = None
    description: Optional[str] = None
    status: str = "success"
    created_at: str


class AccessPassResponse(BaseModel):
    id: int
    user_id: int
    post_id: int
    amount_paid: float
    created_at: str
