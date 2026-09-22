import logging
from typing import Any, Dict, List, Optional
import httpx

from shared.config import SUPABASE_KEY, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL

logger = logging.getLogger("supabase_client")


class SupabaseClient:
    """
    Lightweight, high-performance async client for Supabase PostgREST endpoints.
    Uses httpx to perform CRUD operations without cumbersome heavyweight SDKs.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.base_url = (base_url or SUPABASE_URL).rstrip("/") + "/rest/v1"
        self.api_key = api_key or SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY

    def _get_headers(self, prefer_return: bool = True) -> Dict[str, str]:
        headers = {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if prefer_return:
            headers["Prefer"] = "return=representation"
        return headers

    async def select(
        self,
        table: str,
        query_params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Query rows from table with optional query parameters (e.g. {'id': 'eq.1'})."""
        url = f"{self.base_url}/{table}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=self._get_headers(prefer_return=False), params=query_params or {})
            if resp.status_code == 200:
                return resp.json()
            logger.warning("Supabase SELECT failed [%s]: %s", resp.status_code, resp.text)
            return []

    async def single(
        self,
        table: str,
        match: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Find a single row by matching column equality."""
        params = {col: f"eq.{val}" for col, val in match.items()}
        params["limit"] = "1"
        rows = await self.select(table, params)
        return rows[0] if rows else None

    async def insert(
        self,
        table: str,
        data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Insert row and return the inserted representation."""
        url = f"{self.base_url}/{table}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=self._get_headers(prefer_return=True), json=data)
            if resp.status_code in (200, 201):
                result = resp.json()
                return result[0] if isinstance(result, list) and result else result
            logger.warning("Supabase INSERT failed [%s]: %s", resp.status_code, resp.text)
            return None

    async def update(
        self,
        table: str,
        match: Dict[str, Any],
        data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Update row matching conditions and return representation."""
        url = f"{self.base_url}/{table}"
        params = {col: f"eq.{val}" for col, val in match.items()}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.patch(url, headers=self._get_headers(prefer_return=True), params=params, json=data)
            if resp.status_code == 200:
                result = resp.json()
                return result[0] if isinstance(result, list) and result else result
            logger.warning("Supabase UPDATE failed [%s]: %s", resp.status_code, resp.text)
            return None

    async def delete(
        self,
        table: str,
        match: Dict[str, Any],
    ) -> bool:
        """Delete row matching conditions."""
        url = f"{self.base_url}/{table}"
        params = {col: f"eq.{val}" for col, val in match.items()}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(url, headers=self._get_headers(prefer_return=False), params=params)
            return resp.status_code in (200, 204)


supabase = SupabaseClient()
