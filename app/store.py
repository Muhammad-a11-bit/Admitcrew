"""Small async PostgREST client. Secret keys are only read by the backend."""
import os
from urllib.parse import quote
import httpx
from fastapi import HTTPException

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "") or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

async def request(method: str, table: str, *, params=None, body=None, prefer=None):
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY or SUPABASE_SECRET_KEY.startswith("replace-"):
        raise HTTPException(503, "Supabase is not configured. Add SUPABASE_URL and SUPABASE_SECRET_KEY to .env.")
    headers = {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.request(method, f"{SUPABASE_URL}/rest/v1/{quote(table, safe='')}" if table else f"{SUPABASE_URL}/rest/v1/", params=params, json=body, headers=headers)
    if response.status_code >= 400:
        detail = "Supabase request failed"
        try:
            payload = response.json()
            detail = payload.get("message") or payload.get("details") or payload.get("hint") or detail
        except Exception:
            pass
        raise HTTPException(502, f"Supabase error ({response.status_code}): {detail}")
    if response.status_code == 204 or not response.content:
        return []
    return response.json()

async def select(table, *, params=None):
    return await request("GET", table, params={"select":"*", **(params or {})})

async def insert(table, row, *, params=None):
    data = await request("POST", table, params=params, body=row, prefer="return=representation")
    return data[0] if data else None

async def patch(table, filters, row):
    params = {**filters, "select":"*"}
    return await request("PATCH", table, params=params, body=row, prefer="return=representation")

async def delete(table, filters):
    return await request("DELETE", table, params=filters, prefer="return=representation")
