"""
Agente especialista em Meta Ads (Facebook + Instagram).
Coleta dados via Marketing API, decide com Gemini, executa com guardrails.

Sinais coletados (pré-fetch antes do Gemini):
  - Campanhas: impressões, cliques, CTR, CPM, CPC, conversões, CPA, ROAS, gasto
  - Ad Sets: métricas + frequência (sinal de fadiga de audiência)
  - Ads: performance por criativo individual
  - Placements: breakdown por publisher_platform + platform_position
  - Demographics: breakdown por idade e gênero
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

_OPTIMIZATION_TOOLS = {"pause_ad_set", "pause_ad", "update_ad_set_bid"}

# ─── Tools disponíveis para o Gemini ─────────────────────────────────────────

TOOLS_SCHEMA = [
    # ── Leitura de dados (fallback — normalmente dados já vêm pré-carregados) ─
    {
        "name": "get_campaigns_performance",
        "description": "Retorna métricas de campanhas ativas. Use somente para drill-down adicional não coberto pelos dados iniciais.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ad_account_id": {"type": "string", "description": "ID da conta de anúncios (ex: act_123456)"},
                "date_preset": {"type": "string", "enum": ["last_7d", "last_14d", "last_30d"]},
            },
            "required": ["ad_account_id", "date_preset"],
        },
    },
    {
        "name": "get_ad_sets_performance",
        "description": "Retorna métricas por ad set com frequência e audience saturation. Use somente para drill-down.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ad_account_id": {"type": "string"},
                "campaign_id": {"type": "string", "description": "Filtrar por campanha (opcional)"},
                "date_preset": {"type": "string", "enum": ["last_7d", "last_14d", "last_30d"]},
            },
            "required": ["ad_account_id", "date_preset"],
        },
    },
    {
        "name": "get_ads_performance",
        "description": "Retorna performance por anúncio individual. Use somente para drill-down.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ad_account_id": {"type": "string"},
                "ad_set_id": {"type": "string", "description": "Filtrar por ad set (opcional)"},
                "date_preset": {"type": "string", "enum": ["last_7d", "last_14d", "last_30d"]},
            },
            "required": ["ad_account_id", "date_preset"],
        },
    },
    # ── Ações de otimização ──────────────────────────────────────────────────
    {
        "name": "pause_ad_set",
        "description": "Pausa um ad set com performance ruim ou audiência fatigada (frequência alta + CTR baixo + CPA acima da meta).",
        "input_schema": {
            "type": "object",
            "properties": {
                "ad_set_id": {"type": "string"},
                "ad_set_name": {"type": "string", "description": "Nome do ad set (para o log)"},
                "reason": {"type": "string", "description": "Justificativa com dados: frequência, CTR, CPA atual, meta de CPA"},
            },
            "required": ["ad_set_id", "ad_set_name", "reason"],
        },
    },
    {
        "name": "pause_ad",
        "description": "Pausa um anúncio específico com baixo CTR ou saturação por frequência.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ad_id": {"type": "string"},
                "ad_name": {"type": "string"},
                "reason": {"type": "string", "description": "Justificativa com dados: CTR, frequência, gasto sem conversão"},
            },
            "required": ["ad_id", "ad_name", "reason"],
        },
    },
    {
        "name": "update_ad_set_bid",
        "description": "Atualiza o lance de um ad set. Use para reduzir lance quando CPA está acima da meta com dados estatisticamente válidos (> 500 impressões). Não pode aumentar orçamento.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ad_set_id": {"type": "string"},
                "ad_set_name": {"type": "string"},
                "current_bid_amount": {"type": "number", "description": "Lance atual em centavos"},
                "new_bid_amount": {"type": "number", "description": "Novo lance proposto em centavos"},
                "reason": {"type": "string", "description": "Justificativa com CPA atual, meta e impressões disponíveis"},
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


def _parse_conversions(actions_data: list) -> float:
    """Soma conversões relevantes (purchase, lead, complete_registration)."""
    return sum(
        float(a["value"]) for a in (actions_data or [])
        if a["action_type"] in ("purchase", "lead", "complete_registration", "onsite_conversion.lead_grouped")
    )


def _get_account_name(ad_account_id: str) -> str:
    """Busca o nome da conta Meta Ads."""
    try:
        data = _meta_get(ad_account_id, {"fields": "name"})
        return data.get("name", "")
    except Exception:
        return ""


# ─── Pré-fetch: funções de coleta de dados ───────────────────────────────────

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
        conversions = _parse_conversions(row.get("actions", []))
        spend = float(row.get("spend", 0))
        results.append({
            "campaign_id": row.get("campaign_id"),
            "campaign_name": row.get("campaign_name"),
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
            "ctr": round(float(row.get("ctr", 0)), 4),
            "cpm": round(float(row.get("cpm", 0)), 2),
            "cpc": round(float(row.get("cpc", 0)), 2),
            "spend_brl": round(spend, 2),
            "conversions": round(conversions, 2),
            "cpa_brl": round(spend / conversions, 2) if conversions > 0 else None,
            "frequency": round(float(row.get("frequency", 0)), 2),
            "reach": int(row.get("reach", 0)),
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
        conversions = _parse_conversions(row.get("actions", []))
        spend = float(row.get("spend", 0))
        results.append({
            "ad_set_id": row.get("adset_id"),
            "ad_set_name": row.get("adset_name"),
            "campaign_id": row.get("campaign_id"),
            "campaign_name": row.get("campaign_name"),
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
            "ctr": round(float(row.get("ctr", 0)), 4),
            "cpm": round(float(row.get("cpm", 0)), 2),
            "spend_brl": round(spend, 2),
            "conversions": round(conversions, 2),
            "cpa_brl": round(spend / conversions, 2) if conversions > 0 else None,
            "frequency": round(float(row.get("frequency", 0)), 2),
            "reach": int(row.get("reach", 0)),
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
        conversions = _parse_conversions(row.get("actions", []))
        spend = float(row.get("spend", 0))
        results.append({
            "ad_id": row.get("ad_id"),
            "ad_name": row.get("ad_name"),
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
            "ctr": round(float(row.get("ctr", 0)), 4),
            "spend_brl": round(spend, 2),
            "conversions": round(conversions, 2),
            "cpa_brl": round(spend / conversions, 2) if conversions > 0 else None,
            "frequency": round(float(row.get("frequency", 0)), 2),
        })
    return results


def _get_placement_breakdown(ad_account_id: str, date_preset: str) -> list[dict]:
    """
    Breakdown por placement: publisher_platform (facebook, instagram, audience_network)
    + platform_position (feed, story, reels, etc.).
    """
    data = _meta_get(f"{ad_account_id}/insights", {
        "level": "account",
        "date_preset": date_preset,
        "fields": "impressions,clicks,spend,ctr,cpm,actions",
        "breakdowns": "publisher_platform,platform_position",
        "limit": 100,
    })
    results = []
    for row in data.get("data", []):
        conversions = _parse_conversions(row.get("actions", []))
        spend = float(row.get("spend", 0))
        if spend < 0.5:  # ignora placements com gasto irrelevante
            continue
        results.append({
            "publisher_platform": row.get("publisher_platform", "unknown"),
            "platform_position": row.get("platform_position", "unknown"),
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
            "ctr": round(float(row.get("ctr", 0)), 4),
            "cpm": round(float(row.get("cpm", 0)), 2),
            "spend_brl": round(spend, 2),
            "conversions": round(conversions, 2),
            "cpa_brl": round(spend / conversions, 2) if conversions > 0 else None,
        })
    # Ordena por gasto decrescente
    return sorted(results, key=lambda x: x["spend_brl"], reverse=True)


def _get_demographic_breakdown(ad_account_id: str, date_preset: str) -> list[dict]:
    """
    Breakdown por faixa etária e gênero.
    Útil para identificar segmentos demográficos com CPA muito acima da meta.
    """
    data = _meta_get(f"{ad_account_id}/insights", {
        "level": "account",
        "date_preset": date_preset,
        "fields": "impressions,clicks,spend,ctr,cpm,actions",
        "breakdowns": "age,gender",
        "limit": 100,
    })
    results = []
    for row in data.get("data", []):
        conversions = _parse_conversions(row.get("actions", []))
        spend = float(row.get("spend", 0))
        if spend < 1.0:  # ignora segmentos com gasto irrelevante
            continue
        results.append({
            "age": row.get("age", "unknown"),
            "gender": row.get("gender", "unknown"),
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
            "ctr": round(float(row.get("ctr", 0)), 4),
            "cpm": round(float(row.get("cpm", 0)), 2),
            "spend_brl": round(spend, 2),
            "conversions": round(conversions, 2),
            "cpa_brl": round(spend / conversions, 2) if conversions > 0 else None,
        })
    return sorted(results, key=lambda x: x["spend_brl"], reverse=True)


# ─── Ações de otimização (mutations) ─────────────────────────────────────────

def _pause_ad_set(ad_set_id: str) -> dict:
    return _meta_post(ad_set_id, {"status": "PAUSED"})


def _enable_ad_set(ad_set_id: str) -> dict:
    return _meta_post(ad_set_id, {"status": "ACTIVE"})


def _pause_ad(ad_id: str) -> dict:
    return _meta_post(ad_id, {"status": "PAUSED"})


def _enable_ad(ad_id: str) -> dict:
    return _meta_post(ad_id, {"status": "ACTIVE"})


def _update_ad_set_bid(ad_set_id: str, new_bid_amount: int) -> dict:
    return _meta_post(ad_set_id, {"bid_amount": new_bid_amount})


# ─── Executor de tools (com guardrails) ─────────────────────────────────────

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
            result = (
                {"skipped": "dry_run", "adjusted_bid": int(adjusted)}
                if settings.dry_run
                else _update_ad_set_bid(inp["ad_set_id"], int(adjusted))
            )
            log_action(PLATFORM, "update_ad_set_bid", inp["ad_set_id"], inp, str(result), settings.dry_run)
            actions_counter.append(1)
            return result

        raise ValueError(f"Tool desconhecida: {tool_name}")

    return execute


# ─── Pré-fetch com tolerância a falhas ───────────────────────────────────────

def _safe_fetch(name: str, fn, *args, **kwargs):
    """Executa uma função de pré-fetch com tratamento de erro isolado."""
    try:
        result = fn(*args, **kwargs)
        log.info(f"[prefetch] {name}: {len(result)} registros")
        return result
    except Exception as e:
        log.warning(f"[prefetch] {name}: falhou — {e}")
        return []


# ─── Replay: executa em produção exatamente o que foi aprovado no dry-run ────

def replay_stored_actions(
    ad_account_id: str,
    actions_detail: list[dict],
    selected_indices: list[int] | None = None,
) -> dict:
    """
    Executa em produção as ações validadas no dry-run.
    selected_indices: se fornecido, executa apenas os índices listados.
    """
    account_name = _get_account_name(ad_account_id)

    to_execute = [
        (i, a) for i, a in enumerate(actions_detail)
        if selected_indices is None or i in selected_indices
    ]

    executed: list[dict] = []
    errors:   list[dict] = []

    for idx, action in to_execute:
        tool       = action["tool"]
        inp        = action["input"]
        dry_result = action.get("result", {})

        try:
            if tool == "pause_ad_set":
                result = _pause_ad_set(inp["ad_set_id"])
                log_action(PLATFORM, tool, inp["ad_set_id"], inp, str(result), False)

            elif tool == "pause_ad":
                result = _pause_ad(inp["ad_id"])
                log_action(PLATFORM, tool, inp["ad_id"], inp, str(result), False)

            elif tool == "update_ad_set_bid":
                # Usa o lance já ajustado pelo clamp do dry-run
                adjusted_bid = dry_result.get("adjusted_bid") or inp["new_bid_amount"]
                result = _update_ad_set_bid(inp["ad_set_id"], int(adjusted_bid))
                log_action(PLATFORM, tool, inp["ad_set_id"], inp, str(result), False)

            else:
                log.warning(f"[replay] Tool desconhecida: {tool} — ignorada")
                continue

            executed.append({
                "tool": tool, "input": inp, "result": result,
                "description": action.get("description", ""),
            })

        except Exception as e:
            log.error(f"[replay] Erro ao executar {tool} (idx={idx}): {e}")
            errors.append({"tool": tool, "action_index": idx, "error": str(e)})

    status = "ok" if not errors else ("partial_error" if executed else "error")
    return {
        "status":         status,
        "account_name":   account_name,
        "actions_count":  len(executed),
        "actions_detail": executed,
        "summary":        f"Replay: {len(executed)}/{len(to_execute)} ações executadas."
                          + (f" {len(errors)} erro(s)." if errors else ""),
        "dry_run":        False,
        "errors":         errors,
    }


# ─── Revert: desfaz as ações de uma sessão já executada ─────────────────────

def revert_stored_actions(ad_account_id: str, actions_detail: list[dict]) -> dict:
    """
    Reverte ações de uma sessão já executada.
    actions_detail deve vir da sessão EXECUTADA (resultado real).
    """
    account_name = _get_account_name(ad_account_id)

    reverted: list[dict] = []
    errors:   list[dict] = []

    for action in reversed(actions_detail):
        tool = action["tool"]
        inp  = action["input"]

        try:
            if tool == "pause_ad_set":
                rv = _enable_ad_set(inp["ad_set_id"])
                log_action(PLATFORM, f"revert_{tool}", inp["ad_set_id"], inp, str(rv), False)

            elif tool == "pause_ad":
                rv = _enable_ad(inp["ad_id"])
                log_action(PLATFORM, f"revert_{tool}", inp["ad_id"], inp, str(rv), False)

            elif tool == "update_ad_set_bid":
                original_bid = inp["current_bid_amount"]
                rv = _update_ad_set_bid(inp["ad_set_id"], int(original_bid))
                log_action(PLATFORM, f"revert_{tool}", inp["ad_set_id"], inp, str(rv), False)

            else:
                continue

            reverted.append({
                "tool":        f"revert_{tool}",
                "input":       inp,
                "result":      rv,
                "description": f"Revertido: {action.get('description', tool)}",
            })

        except Exception as e:
            log.error(f"[revert] Erro ao reverter {tool}: {e}")
            errors.append({"tool": tool, "error": str(e)})

    return {
        "status":           "ok" if not errors else ("partial_error" if reverted else "error"),
        "account_name":     account_name,
        "reverted_count":   len(reverted),
        "reverted_actions": reverted,
        "errors":           errors,
    }


# ─── Entry point ─────────────────────────────────────────────────────────────

def run(ad_account_id: str, date_preset: str = "last_7d") -> dict:
    log.info(f"[Meta Ads] Iniciando | conta={ad_account_id} | período={date_preset} | dry_run={settings.dry_run}")

    try:
        account_name = _get_account_name(ad_account_id)
        client_config = settings.get_meta_account_config(ad_account_id)

        log.info(f"[Meta Ads] Conta: '{account_name}' | CPA meta: R${client_config['target_cpa']:.2f} | ROAS meta: {client_config['target_roas']:.1f}x")

        # ── Pré-fetch completo de todos os sinais ─────────────────────────────
        log.info(f"[Meta Ads] Iniciando pré-fetch de dados...")
        prefetched_data = {
            "campaigns": _safe_fetch(
                "campaigns", _get_campaigns_performance, ad_account_id, date_preset
            ),
            "ad_sets": _safe_fetch(
                "ad_sets", _get_ad_sets_performance, ad_account_id, date_preset
            ),
            "ads": _safe_fetch(
                "ads", _get_ads_performance, ad_account_id, date_preset
            ),
            "placements": _safe_fetch(
                "placements", _get_placement_breakdown, ad_account_id, date_preset
            ),
            "demographics": _safe_fetch(
                "demographics", _get_demographic_breakdown, ad_account_id, date_preset
            ),
        }
        log.info(f"[Meta Ads] Pré-fetch concluído. Enviando ao Gemini...")

        actions_counter: list = []
        executor = _make_tool_executor(actions_counter)

        actions, summary = run_decision_loop(
            platform="meta_ads",
            performance_data={"ad_account_id": ad_account_id, "date_preset": date_preset},
            tools_schema=TOOLS_SCHEMA,
            tool_executor=executor,
            client_config=client_config,
            prefetched_data=prefetched_data,
        )

        # Filtra apenas ações de otimização (exclui consultas de dados)
        optimization_actions = [a for a in actions if a.get("tool") in _OPTIMIZATION_TOOLS]

        notify_run_result(PLATFORM, summary, optimization_actions, settings.dry_run)
        return {
            "status": "ok",
            "account_name": account_name,
            "actions_count": len(optimization_actions),
            "actions_detail": optimization_actions,
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
