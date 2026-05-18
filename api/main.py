"""
FastAPI — ponto de entrada que o N8N chama via HTTP Request.

Fluxo de aprovação humana (human-in-the-loop):
  1. POST /analyze/{plataforma}  → analisa em DRY-RUN, propõe ações, retorna session_id
  2. Usuário revisa no WhatsApp e aprova via link
  3. POST /execute/{session_id}  → executa as ações aprovadas em produção
"""

import uuid
import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

from config.settings import settings
from utils.logger import get_logger

log = get_logger("api")

app = FastAPI(title="Ads Optimization Agent API", version="2.0.0")

# Autenticação simples via header
API_SECRET = os.getenv("API_SECRET", "mude-esta-chave-no-env")

# Sessões pendentes de aprovação (em memória — reinicia com o container)
_pending_sessions: dict = {}


def _auth(x_api_key: Optional[str]):
    if x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="Chave de API inválida")


def _format_actions_whatsapp(platform: str, accounts: list[dict]) -> str:
    """Formata apenas as ações de otimização (não consultas) em texto legível para WhatsApp."""
    from datetime import date
    today = date.today().strftime("%d/%m/%Y")
    lines = [f"🤖 *{platform} — Otimização {today}*\n"]
    total_actions = 0

    for acc in accounts:
        account_id = acc.get("customer_id") or acc.get("ad_account_id", "")
        account_name = acc.get("account_name", "")
        label = f"*{account_name}*" if account_name else f"*Conta {account_id}*"

        if acc.get("status") == "error":
            lines.append(f"📋 {label}: ⚠️ erro ao analisar")
            continue

        actions = acc.get("actions_detail", [])
        total_actions += len(actions)

        if not actions:
            lines.append(f"📋 {label}: ✅ nenhuma otimização necessária")
            continue

        lines.append(f"\n📋 {label} — {len(actions)} otimização(ões):")
        for i, action in enumerate(actions, 1):
            desc = action.get("description", "ação sem descrição")
            lines.append(f"  {i}. {desc}")

    lines.append(
        f"\n📊 *{total_actions} otimização(ões)* em {len(accounts)} conta(s)"
        if total_actions > 0
        else f"\n✅ *Nenhuma otimização necessária hoje* em {len(accounts)} conta(s)"
    )
    return "\n".join(lines)


# ─── Schemas ─────────────────────────────────────────────────────────────────

class GoogleAdsRequest(BaseModel):
    customer_id: Optional[str] = None   # None = todas as contas do .env
    date_range: str = "LAST_7_DAYS"


class MetaAdsRequest(BaseModel):
    ad_account_id: Optional[str] = None  # None = todas as contas do .env
    date_preset: str = "last_7d"


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "dry_run": settings.dry_run, "version": "2.0.0"}


# ─── Fase 1: Analisar (sempre DRY-RUN) ───────────────────────────────────────

@app.post("/analyze/google-ads")
def analyze_google_ads(
    req: GoogleAdsRequest = GoogleAdsRequest(),
    x_api_key: Optional[str] = Header(None),
):
    """Analisa performance e propõe ações SEM executar. Retorna session_id para aprovação."""
    _auth(x_api_key)

    original_dry_run = settings.dry_run
    settings.dry_run = True  # garante modo análise

    try:
        from agents import google_ads_agent
        customer_ids = [req.customer_id] if req.customer_id else settings.google_customer_ids

        accounts_results = []
        for cid in customer_ids:
            log.info(f"[ANALYZE] Google Ads | conta={cid}")
            result = google_ads_agent.run(cid, req.date_range)
            accounts_results.append({"customer_id": cid, **result})

        session_id = str(uuid.uuid4())[:8].upper()
        _pending_sessions[session_id] = {
            "platform": "google_ads",
            "accounts": accounts_results,
            "customer_ids": customer_ids,
            "date_range": req.date_range,
            "created_at": datetime.now().isoformat(),
            "approved": False,
            "executed": False,
        }

        actions_text = _format_actions_whatsapp("Google Ads", accounts_results)

        log.info(f"[ANALYZE] Sessão criada: {session_id}")
        return {
            "status": "pending_approval",
            "session_id": session_id,
            "accounts": accounts_results,
            "actions_text": actions_text,
        }
    finally:
        settings.dry_run = original_dry_run


@app.post("/analyze/meta-ads")
def analyze_meta_ads(
    req: MetaAdsRequest = MetaAdsRequest(),
    x_api_key: Optional[str] = Header(None),
):
    """Analisa performance e propõe ações SEM executar. Retorna session_id para aprovação."""
    _auth(x_api_key)

    original_dry_run = settings.dry_run
    settings.dry_run = True

    try:
        from agents import meta_ads_agent
        account_ids = [req.ad_account_id] if req.ad_account_id else settings.meta_account_ids

        accounts_results = []
        for aid in account_ids:
            log.info(f"[ANALYZE] Meta Ads | conta={aid}")
            result = meta_ads_agent.run(aid, req.date_preset)
            accounts_results.append({"ad_account_id": aid, **result})

        session_id = str(uuid.uuid4())[:8].upper()
        _pending_sessions[session_id] = {
            "platform": "meta_ads",
            "accounts": accounts_results,
            "account_ids": account_ids,
            "date_preset": req.date_preset,
            "created_at": datetime.now().isoformat(),
            "approved": False,
            "executed": False,
        }

        actions_text = _format_actions_whatsapp("Meta Ads", accounts_results)

        log.info(f"[ANALYZE] Sessão criada: {session_id}")
        return {
            "status": "pending_approval",
            "session_id": session_id,
            "accounts": accounts_results,
            "actions_text": actions_text,
        }
    finally:
        settings.dry_run = original_dry_run


# ─── Fase 2: Executar (após aprovação) ───────────────────────────────────────

@app.post("/execute/{session_id}")
def execute_session(session_id: str, x_api_key: Optional[str] = Header(None)):
    """Executa as ações de uma sessão aprovada. Só funciona se session_id existir."""
    _auth(x_api_key)

    session = _pending_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sessão '{session_id}' não encontrada ou expirada.")
    if session.get("executed"):
        raise HTTPException(status_code=409, detail="Esta sessão já foi executada.")

    platform = session["platform"]
    settings.dry_run = False  # execução real

    try:
        if platform == "google_ads":
            from agents import google_ads_agent
            results = []
            for cid in session["customer_ids"]:
                log.info(f"[EXECUTE] Google Ads | conta={cid} | sessão={session_id}")
                result = google_ads_agent.run(cid, session.get("date_range", "LAST_7_DAYS"))
                results.append({"customer_id": cid, **result})
        else:
            from agents import meta_ads_agent
            results = []
            for aid in session["account_ids"]:
                log.info(f"[EXECUTE] Meta Ads | conta={aid} | sessão={session_id}")
                result = meta_ads_agent.run(aid, session.get("date_preset", "last_7d"))
                results.append({"ad_account_id": aid, **result})

        session["executed"] = True
        session["executed_at"] = datetime.now().isoformat()
        log.info(f"[EXECUTE] Sessão {session_id} executada com sucesso.")

        return {
            "status": "ok",
            "session_id": session_id,
            "platform": platform,
            "accounts": results,
            "dry_run": False,
        }

    except Exception as e:
        log.exception(f"[EXECUTE] Erro na sessão {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        settings.dry_run = True  # volta ao modo seguro após execução


# ─── Endpoints legados (compatibilidade) ─────────────────────────────────────

@app.post("/optimize/google-ads")
def optimize_google_ads(
    req: GoogleAdsRequest = GoogleAdsRequest(),
    x_api_key: Optional[str] = Header(None),
):
    """Legado — use /analyze/google-ads + /execute/{session_id} para ter aprovação humana."""
    _auth(x_api_key)
    from agents import google_ads_agent
    customer_ids = [req.customer_id] if req.customer_id else settings.google_customer_ids
    results = []
    for cid in customer_ids:
        result = google_ads_agent.run(cid, req.date_range)
        results.append({"customer_id": cid, **result})
    return {"status": "ok", "platform": "google_ads", "accounts": results, "dry_run": settings.dry_run}


@app.post("/optimize/meta-ads")
def optimize_meta_ads(
    req: MetaAdsRequest = MetaAdsRequest(),
    x_api_key: Optional[str] = Header(None),
):
    """Legado — use /analyze/meta-ads + /execute/{session_id} para ter aprovação humana."""
    _auth(x_api_key)
    from agents import meta_ads_agent
    account_ids = [req.ad_account_id] if req.ad_account_id else settings.meta_account_ids
    results = []
    for aid in account_ids:
        result = meta_ads_agent.run(aid, req.date_preset)
        results.append({"ad_account_id": aid, **result})
    return {"status": "ok", "platform": "meta_ads", "accounts": results, "dry_run": settings.dry_run}


@app.post("/optimize/all")
def optimize_all(x_api_key: Optional[str] = Header(None)):
    """Legado — use /analyze + /execute para ter aprovação humana."""
    _auth(x_api_key)
    from agents import google_ads_agent, meta_ads_agent
    results = {"google_ads": [], "meta_ads": []}
    for cid in settings.google_customer_ids:
        results["google_ads"].append({"customer_id": cid, **google_ads_agent.run(cid)})
    for aid in settings.meta_account_ids:
        results["meta_ads"].append({"ad_account_id": aid, **meta_ads_agent.run(aid)})
    return results
