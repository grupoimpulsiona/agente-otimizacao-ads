"""
Agente especialista em Meta Ads (Facebook + Instagram).
Coleta dados via Marketing API, decide com Claude, executa com guardrails.
"""

import time
from typing import Any
import requests

from config.settings import settings
from utils.logger import get_logger, log_action
from utils.guardrails import (
    GuardrailViolation,
    block_budget_increase,
    check_action_limit,
    clamp_bid_change,
)
from utils.notifier import notify_error, notify_run_result
from agents.decision_engine import run_decision_loop

log = get_logger("meta_ads_agent")

PLATFORM = "Meta Ads"
META_API_VERSION = "v21.0"
META_BASE = f"https://graph.facebook.com/{META_API_VERSION}"

# ─── Tools disponíveis para o Claude ─────────────────────────────────────────

TOOLS_SCHEMA = [
    {
        "name": "get_campaigns_performance",
        "description": "Retorna métricas de performance de todas as campanhas ativas: impressões, cliques, CTR, CPM, CPC, conversões, CPA, ROAS, gasto.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ad_account_id": {"type": "string", "description": "ID da conta de anúncios (ex: act_123456)"},
                "date_preset": {"type": "string", "enum": ["last_7d", "last_14d", "last_30d"], "default": "last_7d"},
            },
            "required": ["ad_account_id", "date_preset"],
        },
    },
    {
        "name": "get_ad_sets_performance",
        "description": "Retorna métricas detalhadas por ad set, incluindo frequência e audience saturation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ad_account_id": {"type": "string"},
                "campaign_id": {"type": "string", "description": "Filtrar por campanha (opcional)"},
                "date_preset": {"type": "string", "enum": ["last_7d", "last_14d", "last_30d"], "default": "last_7d"},
            },
            "required": ["ad_account_id", "date_preset"],
        },
    },
    {
        "name": "get_ads_performance",
        "description": "Retorna performance por anúncio individual, incluindo CTR, frequência e gasto.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ad_account_id": {"type": "string"},
                "ad_set_id": {"type": "string", "description": "Filtrar por ad set (opcional)"},
                "date_preset": {"type": "string", "enum": ["last_7d", "last_14d", "last_30d"], "default": "last_7d"},
            },
            "required": ["ad_account_id", "date_preset"],
        },
    },
    {
        "name": "pause_ad_set",
        "description": "Pausa um ad set com performance ruim ou audiência fatigada.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ad_set_id": {"type": "string"},
                "ad_set_name": {"type": "string", "description": "Nome do ad set (para o log)"},
                "reason": {"type": "string"},
            },
            "required": ["ad_set_id", "ad_set_name", "reason"],
        },
    },
    {
        "name": "pause_ad",
        "description": "Pausa um anúncio específico com baixa performance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ad_id": {"type": "string"},
                "ad_name": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["ad_id", "ad_name", "reason"],
        },
    },
    {
        "name": "update_ad_set_bid",
        "description": "Atualiza o lance de um ad set. Não pode aumentar orçamento.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ad_set_id": {"type": "string"},
                "ad_set_name": {"type": "string"},
                "current_bid_amount": {"type": "number", "description": "Lance atual em centavos"},
                "new_bid_amount": {"type": "number", "description": "Novo lance proposto em centavos"},
                "reason": {"type": "string"},
            },
            "required": ["ad_set_id", "ad_set_name", "current_bid_amount", "new_bid_amount", "reason"],
        },
    },
]


# ─── Chamadas à Meta Marketing API ───────────────────────────────────────────

def _meta_get(endpoint: str, params: dict) -> dict:
    params["access_token"] = settings.meta_access_token
    for attempt in range(1, 5):
        try:
            r = requests.get(f"{META_BASE}/{endpoint}", params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            if attempt == 4 or r.status_code in (400, 401, 403):
                raise
            wait = 2 ** attempt
            log.warning(f"Meta API erro tentativa {attempt}: {e}. Aguardando {wait}s...")
            time.sleep(wait)
    return {}


def _meta_post(endpoint: str, payload: dict) -> dict:
    payload["access_token"] = settings.meta_access_token
    for attempt in range(1, 5):
        try:
            r = requests.post(f"{META_BASE}/{endpoint}", data=payload, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            if attempt == 4 or r.status_code in (400, 401, 403):
                raise
            wait = 2 ** attempt
            log.warning(f"Meta API POST erro tentativa {attempt}: {e}. Aguardando {wait}s...")
            time.sleep(wait)
    return {}


INSIGHTS_FIELDS = "campaign_id,campaign_name,impressions,clicks,ctr,cpm,cpc,spend,actions,action_values,frequency,reach"


def _parse_conversions(actions_data: list) -> tuple[float, float]:
    conversions = sum(float(a["value"]) for a in (actions_data or []) if a["action_type"] in ("purchase", "lead", "complete_registration"))
    conv_value = 0.0
    return conversions, conv_value


def _get_campaigns_performance(ad_account_id: str, date_preset: str) -> list[dict]:
    data = _meta_get(f"{ad_account_id}/insights", {
        "level": "campaign",
        "date_preset": date_preset,
        "fields": INSIGHTS_FIELDS,
        "filtering": '[{"field":"campaign.effective_status","operator":"IN","value":["ACTIVE"]}]',
        "limit": 100,
    })
    results = []
    for row in data.get("data", []):
        conversions, _ = _parse_conversions(row.get("actions", []))
        spend = float(row.get("spend", 0))
        results.append({
            "campaign_id": row.get("campaign_id"),
            "campaign_name": row.get("campaign_name"),
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
            "ctr": float(row.get("ctr", 0)),
            "cpm": float(row.get("cpm", 0)),
            "cpc": float(row.get("cpc", 0)),
            "spend_brl": spend,
            "conversions": conversions,
            "cpa_brl": spend / conversions if conversions > 0 else None,
            "frequency": float(row.get("frequency", 0)),
        })
    return results


def _get_ad_sets_performance(ad_account_id: str, date_preset: str, campaign_id: str = None) -> list[dict]:
    params = {
        "level": "adset",
        "date_preset": date_preset,
        "fields": f"{INSIGHTS_FIELDS},adset_id,adset_name",
        "filtering": '[{"field":"adset.effective_status","operator":"IN","value":["ACTIVE"]}]',
        "limit": 100,
    }
    if campaign_id:
        params["filtering"] = f'[{{"field":"campaign.id","operator":"EQUAL","value":"{campaign_id}"}}]'

    data = _meta_get(f"{ad_account_id}/insights", params)
    results = []
    for row in data.get("data", []):
        conversions, _ = _parse_conversions(row.get("actions", []))
        spend = float(row.get("spend", 0))
        results.append({
            "ad_set_id": row.get("adset_id"),
            "ad_set_name": row.get("adset_name"),
            "campaign_id": row.get("campaign_id"),
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
            "ctr": float(row.get("ctr", 0)),
            "cpm": float(row.get("cpm", 0)),
            "spend_brl": spend,
            "conversions": conversions,
            "cpa_brl": spend / conversions if conversions > 0 else None,
            "frequency": float(row.get("frequency", 0)),
        })
    return results


def _get_ads_performance(ad_account_id: str, date_preset: str, ad_set_id: str = None) -> list[dict]:
    params = {
        "level": "ad",
        "date_preset": date_preset,
        "fields": f"{INSIGHTS_FIELDS},ad_id,ad_name",
        "limit": 100,
    }
    if ad_set_id:
        params["filtering"] = f'[{{"field":"adset.id","operator":"EQUAL","value":"{ad_set_id}"}}]'

    data = _meta_get(f"{ad_account_id}/insights", params)
    results = []
    for row in data.get("data", []):
        conversions, _ = _parse_conversions(row.get("actions", []))
        spend = float(row.get("spend", 0))
        results.append({
            "ad_id": row.get("ad_id"),
            "ad_name": row.get("ad_name"),
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
            "ctr": float(row.get("ctr", 0)),
            "spend_brl": spend,
            "conversions": conversions,
            "frequency": float(row.get("frequency", 0)),
        })
    return results


def _pause_ad_set(ad_set_id: str) -> dict:
    return _meta_post(ad_set_id, {"status": "PAUSED"})


def _pause_ad(ad_id: str) -> dict:
    return _meta_post(ad_id, {"status": "PAUSED"})


def _update_ad_set_bid(ad_set_id: str, new_bid_amount: int) -> dict:
    return _meta_post(ad_set_id, {"bid_amount": new_bid_amount})


# ─── Executor de tools com guardrails ────────────────────────────────────────

def _make_tool_executor(actions_counter: list):
    def execute(tool_name: str, inp: dict) -> Any:
        check_action_limit(len(actions_counter), settings.max_actions_per_run)
        block_budget_increase(tool_name)

        if tool_name == "get_campaigns_performance":
            return _get_campaigns_performance(inp["ad_account_id"], inp.get("date_preset", "last_7d"))

        if tool_name == "get_ad_sets_performance":
            return _get_ad_sets_performance(inp["ad_account_id"], inp.get("date_preset", "last_7d"), inp.get("campaign_id"))

        if tool_name == "get_ads_performance":
            return _get_ads_performance(inp["ad_account_id"], inp.get("date_preset", "last_7d"), inp.get("ad_set_id"))

        if tool_name == "pause_ad_set":
            result = {"skipped": "dry_run"} if settings.dry_run else _pause_ad_set(inp["ad_set_id"])
            log_action(PLATFORM, "pause_ad_set", inp["ad_set_id"], inp, str(result), settings.dry_run)
            actions_counter.append(1)
            return result

        if tool_name == "pause_ad":
            result = {"skipped": "dry_run"} if settings.dry_run else _pause_ad(inp["ad_id"])
            log_action(PLATFORM, "pause_ad", inp["ad_id"], inp, str(result), settings.dry_run)
            actions_counter.append(1)
            return result

        if tool_name == "update_ad_set_bid":
            adjusted = clamp_bid_change(
                inp["current_bid_amount"], inp["new_bid_amount"],
                settings.max_bid_change_pct, inp["ad_set_name"]
            )
            result = {"skipped": "dry_run", "adjusted_bid": int(adjusted)} if settings.dry_run else _update_ad_set_bid(inp["ad_set_id"], int(adjusted))
            log_action(PLATFORM, "update_ad_set_bid", inp["ad_set_id"], inp, str(result), settings.dry_run)
            actions_counter.append(1)
            return result

        raise ValueError(f"Tool desconhecida: {tool_name}")

    return execute


# ─── Entry point ─────────────────────────────────────────────────────────────

def run(ad_account_id: str, date_preset: str = "last_7d") -> dict:
    log.info(f"[Meta Ads] Iniciando agente | conta={ad_account_id} | período={date_preset} | dry_run={settings.dry_run}")

    try:
        actions_counter: list = []
        executor = _make_tool_executor(actions_counter)

        actions, summary = run_decision_loop(
            platform="meta_ads",
            performance_data={"ad_account_id": ad_account_id, "date_preset": date_preset},
            tools_schema=TOOLS_SCHEMA,
            tool_executor=executor,
        )

        notify_run_result(PLATFORM, summary, actions, settings.dry_run)
        return {
            "status": "ok",
            "actions_count": len(actions),
            "actions_detail": actions,
            "summary": summary,
            "dry_run": settings.dry_run,
        }

    except GuardrailViolation as e:
        msg = f"Guardrail ativado: {e}"
        log.error(msg)
        notify_error(PLATFORM, msg)
        return {"status": "guardrail_blocked", "error": str(e)}

    except Exception as e:
        log.exception(f"Erro inesperado no agente Meta Ads: {e}")
        notify_error(PLATFORM, str(e))
        return {"status": "error", "error": str(e)}
