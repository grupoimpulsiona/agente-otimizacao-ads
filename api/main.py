"""
FastAPI — ponto de entrada que o N8N chama via HTTP Request.

Fluxo de aprovação humana (human-in-the-loop):
  1. POST /analyze/{plataforma}  → analisa em DRY-RUN, propõe ações, salva no SQLite
  2. Usuário revisa no WhatsApp / dashboard e aprova
  3. POST /execute/{session_id}  → executa, atualiza SQLite, notifica WhatsApp + Sheets
"""

import uuid
import os
import requests as _requests
from datetime import datetime, date
from typing import Optional

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config.settings import settings
from utils.logger import get_logger
from database import db

log = get_logger("api")

app = FastAPI(title="Ads Optimization Agent API", version="2.1.0")

# CORS — dashboard frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Env vars ──────────────────────────────────────────────────────────────────
API_SECRET = os.getenv("API_SECRET", "mude-esta-chave-no-env")

# WhatsApp — Evolution API
WHATSAPP_URL    = os.getenv("WHATSAPP_URL", "")
WHATSAPP_APIKEY = os.getenv("WHATSAPP_APIKEY", "")
WHATSAPP_GROUP  = os.getenv("WHATSAPP_GROUP", "")

# N8N webhook que escreve no Google Sheets após cada execução
N8N_SHEETS_WEBHOOK = os.getenv("N8N_SHEETS_WEBHOOK", "")

# URL do dashboard (usada nos links do WhatsApp)
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://31.97.170.137:3000")


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
def startup():
    db.init_db()
    log.info("[DB] SQLite inicializado em %s", os.getenv("DB_PATH", "/app/data/ads_agent.db"))


# ── Auth ──────────────────────────────────────────────────────────────────────
def _auth(x_api_key: Optional[str]):
    if x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="Chave de API inválida")


# ── Notificações ──────────────────────────────────────────────────────────────

def _notify_whatsapp(platform: str, session_id: str, accounts: list[dict]):
    """Envia confirmação de execução no WhatsApp."""
    if not all([WHATSAPP_URL, WHATSAPP_APIKEY, WHATSAPP_GROUP]):
        log.warning("[WHATSAPP] Variáveis não configuradas — notificação ignorada.")
        return

    total = sum(len(a.get("actions_detail", [])) for a in accounts)
    names = [a.get("account_name") or a.get("customer_id") or a.get("ad_account_id", "") for a in accounts]
    label = "Google Ads" if platform == "google_ads" else "Meta Ads"
    today = date.today().strftime("%d/%m/%Y")

    text = (
        f"✅ *{label} — Execução Concluída*\n"
        f"📅 {today}\n\n"
        f"🏷 Conta(s): {', '.join(filter(None, names))}\n"
        f"🚀 {total} otimização(ões) aplicada(s)\n"
        f"🔖 Sessão: #{session_id}"
    ) if total > 0 else (
        f"✅ *{label} — Executado*\n"
        f"📅 {today} — Sem otimizações necessárias\n"
        f"🔖 Sessão: #{session_id}"
    )

    try:
        _requests.post(
            WHATSAPP_URL,
            headers={"apikey": WHATSAPP_APIKEY, "Content-Type": "application/json"},
            json={"number": WHATSAPP_GROUP, "text": text},
            timeout=15,
        )
        log.info("[WHATSAPP] Confirmação enviada — sessão %s", session_id)
    except Exception as e:
        log.warning("[WHATSAPP] Falha: %s", e)


def _notify_sheets(platform: str, session_id: str, accounts: list[dict], executed_at: str):
    """Chama o webhook N8N que registra a execução no Google Sheets."""
    if not N8N_SHEETS_WEBHOOK:
        log.debug("[SHEETS] N8N_SHEETS_WEBHOOK não configurado — ignorado.")
        return
    try:
        _requests.post(
            N8N_SHEETS_WEBHOOK,
            json={
                "session_id": session_id,
                "platform": platform,
                "executed_at": executed_at,
                "accounts": accounts,
            },
            timeout=15,
        )
        log.info("[SHEETS] Webhook enviado — sessão %s", session_id)
    except Exception as e:
        log.warning("[SHEETS] Falha ao chamar webhook: %s", e)


def _format_whatsapp_proposal(platform: str, session_id: str, accounts: list[dict]) -> str:
    """Formata a mensagem de proposta com links de aprovação."""
    today   = date.today().strftime("%d/%m/%Y")
    label   = "Google Ads" if platform == "google_ads" else "Meta Ads"
    webhook = "aprovar-google-ads" if platform == "google_ads" else "aprovar-meta-ads"

    lines = [f"🤖 *{label} — Análise {today}*\n"]
    total = 0

    for acc in accounts:
        account_id   = acc.get("customer_id") or acc.get("ad_account_id", "")
        account_name = acc.get("account_name", "")
        lbl = f"*{account_name}*" if account_name else f"*Conta {account_id}*"

        if acc.get("status") == "error":
            lines.append(f"📋 {lbl}: ⚠️ erro ao analisar")
            continue

        actions = acc.get("actions_detail", [])
        total  += len(actions)

        if not actions:
            lines.append(f"📋 {lbl}: ✅ nenhuma otimização necessária")
            continue

        lines.append(f"\n📋 {lbl} — {len(actions)} otimização(ões):")
        for i, action in enumerate(actions, 1):
            lines.append(f"  {i}. {action.get('description', '')}")

    lines.append(
        f"\n📊 *{total} otimização(ões)* em {len(accounts)} conta(s)"
        if total > 0 else
        f"\n✅ *Nenhuma otimização necessária* em {len(accounts)} conta(s)"
    )
    lines.append(
        f"\n━━━━━━━━━━━━━━━━━━━\n"
        f"📱 *Revisar no dashboard:*\n"
        f"{DASHBOARD_URL}/approvals/{session_id}\n\n"
        f"✅ *Aprovar diretamente:*\n"
        f"https://n8n.impulsionatm.com.br/webhook/{webhook}?session_id={session_id}\n\n"
        f"❌ Para REJEITAR, ignore esta mensagem."
    )
    return "\n".join(lines)


# ── Schemas ───────────────────────────────────────────────────────────────────

class GoogleAdsRequest(BaseModel):
    customer_id: Optional[str] = None
    date_range: str = "LAST_7_DAYS"


class MetaAdsRequest(BaseModel):
    ad_account_id: Optional[str] = None
    date_preset: str = "last_7d"


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "dry_run": settings.dry_run, "version": "2.1.0"}


# ── Fase 1: Analisar (sempre DRY-RUN) ────────────────────────────────────────

@app.post("/analyze/google-ads")
def analyze_google_ads(
    req: GoogleAdsRequest = GoogleAdsRequest(),
    x_api_key: Optional[str] = Header(None),
):
    _auth(x_api_key)
    original_dry_run = settings.dry_run
    settings.dry_run = True

    try:
        from agents import google_ads_agent
        customer_ids = [req.customer_id] if req.customer_id else settings.google_customer_ids

        accounts_results = []
        for cid in customer_ids:
            log.info("[ANALYZE] Google Ads | conta=%s", cid)
            result = google_ads_agent.run(cid, req.date_range)
            accounts_results.append({"customer_id": cid, **result})

        session_id = str(uuid.uuid4())[:8].upper()
        db.create_session(
            session_id=session_id,
            platform="google_ads",
            accounts=accounts_results,
            customer_ids=customer_ids,
            date_range=req.date_range,
        )
        log.info("[ANALYZE] Sessão Google Ads criada: %s", session_id)

        return {
            "status": "pending_approval",
            "session_id": session_id,
            "accounts": accounts_results,
            "actions_text": _format_whatsapp_proposal("google_ads", session_id, accounts_results),
        }
    finally:
        settings.dry_run = original_dry_run


@app.post("/analyze/meta-ads")
def analyze_meta_ads(
    req: MetaAdsRequest = MetaAdsRequest(),
    x_api_key: Optional[str] = Header(None),
):
    _auth(x_api_key)
    original_dry_run = settings.dry_run
    settings.dry_run = True

    try:
        from agents import meta_ads_agent
        account_ids = [req.ad_account_id] if req.ad_account_id else settings.meta_account_ids

        accounts_results = []
        for aid in account_ids:
            log.info("[ANALYZE] Meta Ads | conta=%s", aid)
            result = meta_ads_agent.run(aid, req.date_preset)
            accounts_results.append({"ad_account_id": aid, **result})

        session_id = str(uuid.uuid4())[:8].upper()
        db.create_session(
            session_id=session_id,
            platform="meta_ads",
            accounts=accounts_results,
            account_ids=account_ids,
            date_preset=req.date_preset,
        )
        log.info("[ANALYZE] Sessão Meta Ads criada: %s", session_id)

        return {
            "status": "pending_approval",
            "session_id": session_id,
            "accounts": accounts_results,
            "actions_text": _format_whatsapp_proposal("meta_ads", session_id, accounts_results),
        }
    finally:
        settings.dry_run = original_dry_run


# ── Fase 2: Executar (após aprovação) ────────────────────────────────────────

@app.post("/execute/{session_id}")
def execute_session(session_id: str, x_api_key: Optional[str] = Header(None)):
    _auth(x_api_key)

    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sessão '{session_id}' não encontrada.")
    if session.get("executed"):
        raise HTTPException(status_code=409, detail="Esta sessão já foi executada.")

    platform = session["platform"]
    settings.dry_run = False

    try:
        if platform == "google_ads":
            from agents import google_ads_agent
            results = []
            for cid in session["customer_ids"]:
                log.info("[EXECUTE] Google Ads | conta=%s | sessão=%s", cid, session_id)
                result = google_ads_agent.run(cid, session.get("date_range", "LAST_7_DAYS"))
                results.append({"customer_id": cid, **result})
        else:
            from agents import meta_ads_agent
            results = []
            for aid in session["account_ids"]:
                log.info("[EXECUTE] Meta Ads | conta=%s | sessão=%s", aid, session_id)
                result = meta_ads_agent.run(aid, session.get("date_preset", "last_7d"))
                results.append({"ad_account_id": aid, **result})

        executed_at = db.mark_executed(session_id, results)
        log.info("[EXECUTE] Sessão %s executada com sucesso.", session_id)

        # Notificações (independente de como a aprovação chegou)
        _notify_whatsapp(platform, session_id, results)
        _notify_sheets(platform, session_id, results, executed_at)

        return {
            "status": "ok",
            "session_id": session_id,
            "platform": platform,
            "accounts": results,
            "dry_run": False,
        }

    except Exception as e:
        log.exception("[EXECUTE] Erro na sessão %s: %s", session_id, e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        settings.dry_run = True


# ── Dashboard API ─────────────────────────────────────────────────────────────

@app.get("/sessions")
def list_sessions(x_api_key: Optional[str] = Header(None)):
    _auth(x_api_key)
    sessions = db.list_sessions()
    return {"sessions": sessions, "total": len(sessions)}


@app.get("/sessions/{session_id}")
def get_session(session_id: str, x_api_key: Optional[str] = Header(None)):
    _auth(x_api_key)
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sessão '{session_id}' não encontrada.")
    return {
        "session_id": session_id,
        "platform": session["platform"],
        "created_at": session["created_at"],
        "executed": session["executed"],
        "executed_at": session.get("executed_at"),
        "rejected": session["rejected"],
        "rejected_at": session.get("rejected_at"),
        "accounts": session["accounts"],
    }


@app.post("/sessions/{session_id}/reject")
def reject_session(session_id: str, x_api_key: Optional[str] = Header(None)):
    _auth(x_api_key)
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sessão '{session_id}' não encontrada.")
    if session.get("executed"):
        raise HTTPException(status_code=409, detail="Sessão já foi executada.")
    if session.get("rejected"):
        raise HTTPException(status_code=409, detail="Sessão já foi rejeitada.")
    db.mark_rejected(session_id)
    log.info("[REJECT] Sessão %s rejeitada.", session_id)
    return {"status": "rejected", "session_id": session_id}


@app.post("/analyze/trigger")
def trigger_analysis(x_api_key: Optional[str] = Header(None)):
    """Dispara análise para todas as plataformas (usado pelo botão no dashboard)."""
    _auth(x_api_key)
    results = {}
    original_dry_run = settings.dry_run
    settings.dry_run = True

    try:
        if settings.google_customer_ids:
            from agents import google_ads_agent
            accounts_results = []
            for cid in settings.google_customer_ids:
                result = google_ads_agent.run(cid, "LAST_7_DAYS")
                accounts_results.append({"customer_id": cid, **result})
            session_id = str(uuid.uuid4())[:8].upper()
            db.create_session(
                session_id=session_id, platform="google_ads",
                accounts=accounts_results,
                customer_ids=settings.google_customer_ids,
                date_range="LAST_7_DAYS",
            )
            results["google_ads"] = {"session_id": session_id, "accounts": len(accounts_results)}

        if settings.meta_account_ids:
            from agents import meta_ads_agent
            accounts_results = []
            for aid in settings.meta_account_ids:
                result = meta_ads_agent.run(aid, "last_7d")
                accounts_results.append({"ad_account_id": aid, **result})
            session_id = str(uuid.uuid4())[:8].upper()
            db.create_session(
                session_id=session_id, platform="meta_ads",
                accounts=accounts_results,
                account_ids=settings.meta_account_ids,
                date_preset="last_7d",
            )
            results["meta_ads"] = {"session_id": session_id, "accounts": len(accounts_results)}
    finally:
        settings.dry_run = original_dry_run

    return {"status": "ok", "triggered": results}


# ── Legado (compatibilidade) ──────────────────────────────────────────────────

@app.post("/optimize/google-ads")
def optimize_google_ads(
    req: GoogleAdsRequest = GoogleAdsRequest(),
    x_api_key: Optional[str] = Header(None),
):
    _auth(x_api_key)
    from agents import google_ads_agent
    customer_ids = [req.customer_id] if req.customer_id else settings.google_customer_ids
    results = [{"customer_id": cid, **google_ads_agent.run(cid, req.date_range)} for cid in customer_ids]
    return {"status": "ok", "platform": "google_ads", "accounts": results, "dry_run": settings.dry_run}


@app.post("/optimize/meta-ads")
def optimize_meta_ads(
    req: MetaAdsRequest = MetaAdsRequest(),
    x_api_key: Optional[str] = Header(None),
):
    _auth(x_api_key)
    from agents import meta_ads_agent
    account_ids = [req.ad_account_id] if req.ad_account_id else settings.meta_account_ids
    results = [{"ad_account_id": aid, **meta_ads_agent.run(aid, req.date_preset)} for aid in account_ids]
    return {"status": "ok", "platform": "meta_ads", "accounts": results, "dry_run": settings.dry_run}
