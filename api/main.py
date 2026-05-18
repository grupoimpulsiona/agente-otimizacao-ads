"""
FastAPI — ponto de entrada que o N8N chama via HTTP Request.

Fluxo de aprovação humana (human-in-the-loop):
  1. POST /analyze/{plataforma}  → analisa em DRY-RUN, propõe ações, retorna session_id
  2. Usuário revisa no WhatsApp / dashboard e aprova
  3. POST /execute/{session_id}  → executa as ações aprovadas em produção
  4. Backend envia WhatsApp de confirmação automaticamente
"""

import uuid
import os
from datetime import datetime, date
from typing import Optional

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config.settings import settings
from utils.logger import get_logger

log = get_logger("api")

app = FastAPI(title="Ads Optimization Agent API", version="2.0.0")

# CORS — permite o dashboard frontend acessar a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Autenticação simples via header
API_SECRET = os.getenv("API_SECRET", "mude-esta-chave-no-env")

# WhatsApp — Evolution API
WHATSAPP_URL    = os.getenv("WHATSAPP_URL", "")
WHATSAPP_APIKEY = os.getenv("WHATSAPP_APIKEY", "")
WHATSAPP_GROUP  = os.getenv("WHATSAPP_GROUP", "")

# Dashboard URL (usado no link da mensagem de proposta)
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://31.97.170.137:3000")

# Sessões pendentes de aprovação (em memória — reinicia com o container)
_pending_sessions: dict = {}


def _auth(x_api_key: Optional[str]):
    if x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="Chave de API inválida")


def _notify_whatsapp_confirmation(platform: str, session_id: str, accounts: list[dict]):
    """Envia confirmação no WhatsApp após execução bem-sucedida."""
    if not all([WHATSAPP_URL, WHATSAPP_APIKEY, WHATSAPP_GROUP]):
        log.warning("[WHATSAPP] Variáveis não configuradas — notificação ignorada.")
        return

    total = sum(len(a.get("actions_detail", [])) for a in accounts)
    names = [
        a.get("account_name") or a.get("customer_id") or a.get("ad_account_id", "")
        for a in accounts
    ]
    platform_label = "Google Ads" if platform == "google_ads" else "Meta Ads"
    today = date.today().strftime("%d/%m/%Y")

    if total > 0:
        text = (
            f"✅ *{platform_label} — Execução Concluída*\n"
            f"📅 {today}\n\n"
            f"🏷 Conta(s): {', '.join(filter(None, names))}\n"
            f"🚀 {total} otimização(ões) aplicada(s) com sucesso\n"
            f"🔖 Sessão: #{session_id}"
        )
    else:
        text = (
            f"✅ *{platform_label} — Executado*\n"
            f"📅 {today}\n\n"
            f"Nenhuma otimização necessária em: {', '.join(filter(None, names))}\n"
            f"🔖 Sessão: #{session_id}"
        )

    try:
        import requests as _req
        _req.post(
            WHATSAPP_URL,
            headers={"apikey": WHATSAPP_APIKEY, "Content-Type": "application/json"},
            json={"number": WHATSAPP_GROUP, "text": text},
            timeout=15,
        )
        log.info(f"[WHATSAPP] Confirmação enviada — sessão {session_id}")
    except Exception as e:
        log.warning(f"[WHATSAPP] Falha ao enviar confirmação: {e}")


def _format_actions_whatsapp(platform: str, session_id: str, accounts: list[dict]) -> str:
    """Formata a proposta de otimizações em texto legível para WhatsApp."""
    today = date.today().strftime("%d/%m/%Y")
    platform_label = "Google Ads" if platform == "google_ads" else "Meta Ads"
    webhook_path   = "aprovar-google-ads" if platform == "google_ads" else "aprovar-meta-ads"

    lines = [f"🤖 *{platform_label} — Análise {today}*\n"]
    total_actions = 0

    for acc in accounts:
        account_id   = acc.get("customer_id") or acc.get("ad_account_id", "")
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

    if total_actions > 0:
        lines.append(f"\n📊 *{total_actions} otimização(ões)* em {len(accounts)} conta(s)")
    else:
        lines.append(f"\n✅ *Nenhuma otimização necessária hoje* em {len(accounts)} conta(s)")

    lines.append(
        f"\n━━━━━━━━━━━━━━━━━━━\n"
        f"📱 *Revisar no dashboard:*\n"
        f"{DASHBOARD_URL}/approvals/{session_id}\n\n"
        f"✅ *Aprovar diretamente:*\n"
        f"https://n8n.impulsionatm.com.br/webhook/{webhook_path}?session_id={session_id}\n\n"
        f"❌ Para REJEITAR, ignore esta mensagem."
    )

    return "\n".join(lines)


# ─── Schemas ─────────────────────────────────────────────────────────────────

class GoogleAdsRequest(BaseModel):
    customer_id: Optional[str] = None
    date_range: str = "LAST_7_DAYS"


class MetaAdsRequest(BaseModel):
    ad_account_id: Optional[str] = None
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
    settings.dry_run = True

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

        actions_text = _format_actions_whatsapp("google_ads", session_id, accounts_results)

        log.info(f"[ANALYZE] Sessão Google Ads criada: {session_id}")
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

        actions_text = _format_actions_whatsapp("meta_ads", session_id, accounts_results)

        log.info(f"[ANALYZE] Sessão Meta Ads criada: {session_id}")
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
    """Executa as ações aprovadas e envia confirmação no WhatsApp."""
    _auth(x_api_key)

    session = _pending_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sessão '{session_id}' não encontrada ou expirada.")
    if session.get("executed"):
        raise HTTPException(status_code=409, detail="Esta sessão já foi executada.")

    platform = session["platform"]
    settings.dry_run = False

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

        # Notifica WhatsApp com confirmação (independente de onde veio a aprovação)
        _notify_whatsapp_confirmation(platform, session_id, results)

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
        settings.dry_run = True


# ─── Dashboard API — Gerenciamento de sessões ─────────────────────────────────

@app.get("/sessions")
def list_sessions(x_api_key: Optional[str] = Header(None)):
    """Lista todas as sessões (pendentes e executadas) para o dashboard."""
    _auth(x_api_key)
    sessions = []
    for sid, session in _pending_sessions.items():
        total_actions = sum(
            len(acc.get("actions_detail", [])) for acc in session.get("accounts", [])
        )
        sessions.append({
            "session_id": sid,
            "platform": session["platform"],
            "created_at": session["created_at"],
            "executed": session.get("executed", False),
            "executed_at": session.get("executed_at"),
            "rejected": session.get("rejected", False),
            "rejected_at": session.get("rejected_at"),
            "total_actions": total_actions,
            "accounts_count": len(session.get("accounts", [])),
            "accounts": [
                {
                    "id": acc.get("customer_id") or acc.get("ad_account_id", ""),
                    "name": acc.get("account_name", ""),
                    "status": acc.get("status", "ok"),
                    "actions_count": len(acc.get("actions_detail", [])),
                }
                for acc in session.get("accounts", [])
            ],
        })
    sessions.sort(key=lambda s: s["created_at"], reverse=True)
    return {"sessions": sessions, "total": len(sessions)}


@app.get("/sessions/{session_id}")
def get_session(session_id: str, x_api_key: Optional[str] = Header(None)):
    """Retorna detalhes completos de uma sessão."""
    _auth(x_api_key)
    session = _pending_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sessão '{session_id}' não encontrada.")
    return {
        "session_id": session_id,
        "platform": session["platform"],
        "created_at": session["created_at"],
        "executed": session.get("executed", False),
        "executed_at": session.get("executed_at"),
        "rejected": session.get("rejected", False),
        "rejected_at": session.get("rejected_at"),
        "accounts": session.get("accounts", []),
    }


@app.post("/sessions/{session_id}/reject")
def reject_session(session_id: str, x_api_key: Optional[str] = Header(None)):
    """Rejeita uma sessão pendente sem executar as ações."""
    _auth(x_api_key)
    session = _pending_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sessão '{session_id}' não encontrada.")
    if session.get("executed"):
        raise HTTPException(status_code=409, detail="Sessão já foi executada e não pode ser rejeitada.")
    if session.get("rejected"):
        raise HTTPException(status_code=409, detail="Sessão já foi rejeitada.")
    session["rejected"] = True
    session["rejected_at"] = datetime.now().isoformat()
    log.info(f"[REJECT] Sessão {session_id} rejeitada.")
    return {"status": "rejected", "session_id": session_id}


@app.post("/analyze/trigger")
def trigger_analysis(x_api_key: Optional[str] = Header(None)):
    """Dispara análise para todas as plataformas configuradas. Usado pelo dashboard."""
    _auth(x_api_key)
    results = {}

    if settings.google_customer_ids:
        from agents import google_ads_agent
        original_dry_run = settings.dry_run
        settings.dry_run = True
        try:
            accounts_results = []
            for cid in settings.google_customer_ids:
                result = google_ads_agent.run(cid, "LAST_7_DAYS")
                accounts_results.append({"customer_id": cid, **result})
            session_id = str(uuid.uuid4())[:8].upper()
            _pending_sessions[session_id] = {
                "platform": "google_ads",
                "accounts": accounts_results,
                "customer_ids": settings.google_customer_ids,
                "date_range": "LAST_7_DAYS",
                "created_at": datetime.now().isoformat(),
                "approved": False,
                "executed": False,
            }
            results["google_ads"] = {"session_id": session_id, "accounts": len(accounts_results)}
        finally:
            settings.dry_run = original_dry_run

    if settings.meta_account_ids:
        from agents import meta_ads_agent
        original_dry_run = settings.dry_run
        settings.dry_run = True
        try:
            accounts_results = []
            for aid in settings.meta_account_ids:
                result = meta_ads_agent.run(aid, "last_7d")
                accounts_results.append({"ad_account_id": aid, **result})
            session_id = str(uuid.uuid4())[:8].upper()
            _pending_sessions[session_id] = {
                "platform": "meta_ads",
                "accounts": accounts_results,
                "account_ids": settings.meta_account_ids,
                "date_preset": "last_7d",
                "created_at": datetime.now().isoformat(),
                "approved": False,
                "executed": False,
            }
            results["meta_ads"] = {"session_id": session_id, "accounts": len(accounts_results)}
        finally:
            settings.dry_run = original_dry_run

    return {"status": "ok", "triggered": results}


# ─── Endpoints legados (compatibilidade) ─────────────────────────────────────

@app.post("/optimize/google-ads")
def optimize_google_ads(
    req: GoogleAdsRequest = GoogleAdsRequest(),
    x_api_key: Optional[str] = Header(None),
):
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
    _auth(x_api_key)
    from agents import meta_ads_agent
    account_ids = [req.ad_account_id] if req.ad_account_id else settings.meta_account_ids
    results = []
    for aid in account_ids:
        result = meta_ads_agent.run(aid, req.date_preset)
        results.append({"ad_account_id": aid, **result})
    return {"status": "ok", "platform": "meta_ads", "accounts": results, "dry_run": settings.dry_run}
