"""
FastAPI — ponto de entrada que o N8N chama via HTTP Request.
"""

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
import os

from config.settings import settings
from utils.logger import get_logger

log = get_logger("api")

app = FastAPI(title="Ads Optimization Agent API", version="1.0.0")

# Autenticação simples via header — configure API_SECRET no .env
API_SECRET = os.getenv("API_SECRET", "mude-esta-chave-no-env")


def _auth(x_api_key: Optional[str]):
    if x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="Chave de API inválida")


# ─── Schemas de request ───────────────────────────────────────────────────────

class GoogleAdsRequest(BaseModel):
    customer_id: Optional[str] = None   # None = todas as contas do .env
    date_range: str = "LAST_7_DAYS"
    dry_run: Optional[bool] = None


class MetaAdsRequest(BaseModel):
    ad_account_id: Optional[str] = None  # None = todas as contas do .env
    date_preset: str = "last_7d"
    dry_run: Optional[bool] = None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "dry_run": settings.dry_run}


@app.post("/optimize/google-ads")
def optimize_google_ads(req: GoogleAdsRequest = GoogleAdsRequest(), x_api_key: Optional[str] = Header(None)):
    _auth(x_api_key)

    if req.dry_run is not None:
        settings.dry_run = req.dry_run

    from agents import google_ads_agent

    # Se não veio customer_id, roda todas as contas configuradas no .env
    customer_ids = [req.customer_id] if req.customer_id else settings.google_customer_ids
    results = []
    for cid in customer_ids:
        log.info(f"POST /optimize/google-ads | customer={cid}")
        results.append({"customer_id": cid, **google_ads_agent.run(cid, req.date_range)})

    return {"status": "ok", "platform": "google_ads", "accounts": results, "dry_run": settings.dry_run}


@app.post("/optimize/meta-ads")
def optimize_meta_ads(req: MetaAdsRequest = MetaAdsRequest(), x_api_key: Optional[str] = Header(None)):
    _auth(x_api_key)

    if req.dry_run is not None:
        settings.dry_run = req.dry_run

    from agents import meta_ads_agent

    # Se não veio ad_account_id, roda todas as contas configuradas no .env
    account_ids = [req.ad_account_id] if req.ad_account_id else settings.meta_account_ids
    results = []
    for aid in account_ids:
        log.info(f"POST /optimize/meta-ads | account={aid}")
        results.append({"ad_account_id": aid, **meta_ads_agent.run(aid, req.date_preset)})

    return {"status": "ok", "platform": "meta_ads", "accounts": results, "dry_run": settings.dry_run}


@app.post("/optimize/all")
def optimize_all(x_api_key: Optional[str] = Header(None)):
    """Roda todos os agentes em sequência. Ideal para o trigger diário do N8N."""
    _auth(x_api_key)

    from agents import google_ads_agent, meta_ads_agent

    results = {"google_ads": [], "meta_ads": []}

    for customer_id in settings.google_customer_ids:
        log.info(f"Rodando Google Ads | conta={customer_id}")
        results["google_ads"].append({
            "customer_id": customer_id,
            **google_ads_agent.run(customer_id),
        })

    for account_id in settings.meta_account_ids:
        log.info(f"Rodando Meta Ads | conta={account_id}")
        results["meta_ads"].append({
            "ad_account_id": account_id,
            **meta_ads_agent.run(account_id),
        })

    return results
