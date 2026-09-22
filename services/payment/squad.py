import hashlib
import hmac
import logging
from typing import Any, Dict, Optional
import httpx

from shared.config import SQUAD_BASE_URL, SQUAD_PUBLIC_KEY, SQUAD_SECRET_KEY

logger = logging.getLogger("squad_gateway")


class SquadPaymentGateway:
    """
    Client for Squad Payment Gateway (by HabariPay / GTCO).
    Live Production URL: https://api-d.squadco.com
    """

    def __init__(
        self,
        base_url: str = SQUAD_BASE_URL,
        secret_key: str = SQUAD_SECRET_KEY,
        public_key: str = SQUAD_PUBLIC_KEY,
    ):
        self.base_url = base_url.rstrip("/")
        self.secret_key = secret_key
        self.public_key = public_key

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    async def initiate_transaction(
        self,
        email: str,
        amount_naira: float,
        transaction_ref: str,
        callback_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        currency: str = "NGN",
    ) -> Dict[str, Any]:
        """
        Initiate a payment transaction with Squad.
        Amount must be converted to kobo (amount * 100).
        """
        amount_kobo = int(round(amount_naira * 100))
        payload = {
            "amount": amount_kobo,
            "email": email,
            "currency": currency,
            "initiate_type": "inline",
            "transaction_ref": transaction_ref,
            "payment_channels": ["card", "bank", "ussd", "transfer"],
        }
        if callback_url:
            payload["callback_url"] = callback_url
        if metadata:
            payload["metadata"] = metadata

        url = f"{self.base_url}/transaction/initiate"
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(url, headers=self._headers(), json=payload)
                data = resp.json()
                if resp.status_code in (200, 201) and data.get("success"):
                    return {
                        "success": True,
                        "checkout_url": data.get("data", {}).get("checkout_url"),
                        "transaction_ref": transaction_ref,
                        "raw": data,
                    }
                return {
                    "success": False,
                    "error": data.get("message", "Squad initiation failed"),
                    "raw": data,
                }
            except Exception as e:
                logger.error("Error connecting to Squad: %s", str(e))
                return {"success": False, "error": str(e)}

    async def verify_transaction(self, transaction_ref: str) -> Dict[str, Any]:
        """
        Verify transaction status using Squad reference.
        """
        url = f"{self.base_url}/transaction/verify/{transaction_ref}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(url, headers=self._headers())
                data = resp.json()
                if resp.status_code == 200 and data.get("success"):
                    tx_data = data.get("data", {})
                    # Amount is returned in kobo, convert back to naira
                    amount_kobo = tx_data.get("transaction_amount") or tx_data.get("amount", 0)
                    amount_naira = float(amount_kobo) / 100.0 if amount_kobo else 0.0

                    return {
                        "success": True,
                        "is_paid": tx_data.get("transaction_status") == "success",
                        "status": tx_data.get("transaction_status"),
                        "amount_naira": amount_naira,
                        "transaction_ref": transaction_ref,
                        "raw": tx_data,
                    }
                return {
                    "success": False,
                    "is_paid": False,
                    "status": data.get("message", "Verification failed"),
                    "raw": data,
                }
            except Exception as e:
                logger.error("Error verifying Squad transaction: %s", str(e))
                return {"success": False, "is_paid": False, "error": str(e)}

    def verify_webhook_signature(self, body_bytes: bytes, signature_header: Optional[str]) -> bool:
        """Verify webhook signature using SHA512 HMAC."""
        if not signature_header:
            return False
        expected_sig = hmac.new(self.secret_key.encode("utf-8"), body_bytes, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected_sig.lower(), signature_header.lower())


squad_gateway = SquadPaymentGateway()
