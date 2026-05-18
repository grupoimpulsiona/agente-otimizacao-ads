"""
Agente especialista em Google Ads.
Coleta dados de performance via API, decide com Claude, executa ações com guardrails.
"""

import time
from typing import Any
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

from config.settings import settings
from utils.logger import get_logger, log_action
from utils.guardrails import (
    GuardrailViolation,
    block_budget_increase,
    check_action_limit,
    clamp_bid_change,
    require_min_data,
)
from utils.notifier import notify_anomaly, notify_error, notify_run_result
from agents.decision_engine import run_decision_loop

log = get_logger("google_ads_agent")

PLATFORM = "Google Ads"

# ─── Tools disponíveis para o Claude ────────────────────────────────────────

TOOLS_SCHEMA = [
    {
        "name": "get_campaign_performance",
        "description": "Retorna métricas de performance de todas as campanhas ativas (CTR, CPC, CPA, ROAS, impressões, cliques, conversões, custo).",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "ID da conta Google Ads"},
                "date_range": {"type": "string", "enum": ["LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS"], "description": "Período de análise"},
            },
            "required": ["customer_id", "date_range"],
        },
    },
    {
        "name": "get_keyword_performance",
        "description": "Retorna performance detalhada de keywords por campanha e ad group.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "campaign_id": {"type": "string", "description": "Filtrar por campanha específica (opcional)"},
                "date_range": {"type": "string", "enum": ["LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS"]},
            },
            "required": ["customer_id", "date_range"],
        },
    },
    {
        "name": "get_search_terms_report",
        "description": "Retorna os termos de busca reais que ativaram os anúncios. Útil para identificar termos irrelevantes a negativar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "date_range": {"type": "string", "enum": ["LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS"]},
                "min_impressions": {"type": "integer", "description": "Mínimo de impressões para retornar o termo (padrão: 10)"},
            },
            "required": ["customer_id", "date_range"],
        },
    },
    {
        "name": "pause_keyword",
        "description": "Pausa uma keyword específica que está desperdiçando verba.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "ad_group_id": {"type": "string"},
                "keyword_id": {"type": "string"},
                "keyword_text": {"type": "string", "description": "Texto da keyword (para o log)"},
                "reason": {"type": "string", "description": "Motivo da pausa"},
            },
            "required": ["customer_id", "ad_group_id", "keyword_id", "keyword_text", "reason"],
        },
    },
    {
        "name": "update_keyword_bid",
        "description": "Atualiza o lance (CPC máximo) de uma keyword. Não pode aumentar orçamento.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "ad_group_id": {"type": "string"},
                "keyword_id": {"type": "string"},
                "keyword_text": {"type": "string"},
                "current_bid_micros": {"type": "integer", "description": "Lance atual em micros (1 real = 1.000.000 micros)"},
                "new_bid_micros": {"type": "integer", "description": "Novo lance proposto em micros"},
                "reason": {"type": "string"},
            },
            "required": ["customer_id", "ad_group_id", "keyword_id", "keyword_text", "current_bid_micros", "new_bid_micros", "reason"],
        },
    },
    {
        "name": "add_negative_keyword",
        "description": "Adiciona uma keyword negativa a uma campanha para evitar tráfego irrelevante.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "campaign_id": {"type": "string"},
                "keyword_text": {"type": "string"},
                "match_type": {"type": "string", "enum": ["EXACT", "PHRASE", "BROAD"], "description": "Tipo de correspondência (padrão: PHRASE)"},
                "reason": {"type": "string"},
            },
            "required": ["customer_id", "campaign_id", "keyword_text", "match_type", "reason"],
        },
    },
]


# ─── Cliente Google Ads ──────────────────────────────────────────────────────

def _get_client() -> GoogleAdsClient:
    config = {
        "developer_token": settings.google_ads_developer_token,
        "client_id": settings.google_ads_client_id,
        "client_secret": settings.google_ads_client_secret,
        "refresh_token": settings.google_ads_refresh_token,
        "login_customer_id": settings.google_ads_login_customer_id,
        "use_proto_plus": True,
    }
    return GoogleAdsClient.load_from_dict(config)


_OPTIMIZATION_TOOLS = {"pause_keyword", "update_keyword_bid", "add_negative_keyword"}


def _get_account_name(client: GoogleAdsClient, customer_id: str) -> str:
    """Busca o nome descritivo da conta Google Ads."""
    try:
        rows = _run_query(client, customer_id, "SELECT customer.descriptive_name FROM customer LIMIT 1")
        return rows[0].customer.descriptive_name if rows else ""
    except Exception:
        return ""


def _run_query(client: GoogleAdsClient, customer_id: str, query: str) -> list[dict]:
    """Executa GAQL com retry automático."""
    ga_service = client.get_service("GoogleAdsService")
    for attempt in range(1, 5):
        try:
            response = ga_service.search(customer_id=customer_id, query=query)
            return list(response)
        except GoogleAdsException as e:
            if attempt == 4:
                raise
            wait = 2 ** attempt
            log.warning(f"GAQL erro tentativa {attempt}: {e}. Aguardando {wait}s...")
            time.sleep(wait)
    return []


# ─── Implementação das tools ─────────────────────────────────────────────────

def _get_campaign_performance(client: GoogleAdsClient, customer_id: str, date_range: str) -> list[dict]:
    query = f"""
        SELECT
            campaign.id, campaign.name, campaign.status,
            metrics.impressions, metrics.clicks, metrics.cost_micros,
            metrics.ctr, metrics.average_cpc, metrics.conversions,
            metrics.cost_per_conversion, metrics.conversions_value,
            metrics.search_impression_share
        FROM campaign
        WHERE campaign.status = 'ENABLED'
          AND segments.date DURING {date_range}
        ORDER BY metrics.cost_micros DESC
    """
    rows = _run_query(client, customer_id, query)
    return [
        {
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "impressions": row.metrics.impressions,
            "clicks": row.metrics.clicks,
            "cost_brl": row.metrics.cost_micros / 1e6,
            "ctr": round(row.metrics.ctr, 4),
            "avg_cpc_brl": row.metrics.average_cpc / 1e6,
            "conversions": row.metrics.conversions,
            "cpa_brl": row.metrics.cost_per_conversion / 1e6 if row.metrics.conversions > 0 else None,
            "conversion_value": row.metrics.conversions_value,
            "roas": round(row.metrics.conversions_value / (row.metrics.cost_micros / 1e6), 2) if row.metrics.cost_micros > 0 else 0,
            "impression_share": round(row.metrics.search_impression_share, 3),
        }
        for row in rows
    ]


def _get_keyword_performance(client: GoogleAdsClient, customer_id: str, date_range: str, campaign_id: str = None) -> list[dict]:
    campaign_filter = f"AND campaign.id = {campaign_id}" if campaign_id else ""
    query = f"""
        SELECT
            campaign.id, campaign.name,
            ad_group.id, ad_group.name,
            ad_group_criterion.criterion_id,
            ad_group_criterion.keyword.text,
            ad_group_criterion.keyword.match_type,
            ad_group_criterion.cpc_bid_micros,
            metrics.impressions, metrics.clicks, metrics.cost_micros,
            metrics.ctr, metrics.conversions, metrics.cost_per_conversion
        FROM keyword_view
        WHERE ad_group_criterion.status != 'REMOVED'
          AND campaign.status = 'ENABLED'
          AND segments.date DURING {date_range}
          {campaign_filter}
        ORDER BY metrics.cost_micros DESC
        LIMIT 200
    """
    rows = _run_query(client, customer_id, query)
    return [
        {
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "ad_group_id": str(row.ad_group.id),
            "ad_group_name": row.ad_group.name,
            "keyword_id": str(row.ad_group_criterion.criterion_id),
            "keyword_text": row.ad_group_criterion.keyword.text,
            "match_type": row.ad_group_criterion.keyword.match_type.name,
            "current_bid_micros": row.ad_group_criterion.cpc_bid_micros,
            "current_bid_brl": row.ad_group_criterion.cpc_bid_micros / 1e6,
            "impressions": row.metrics.impressions,
            "clicks": row.metrics.clicks,
            "cost_brl": row.metrics.cost_micros / 1e6,
            "ctr": round(row.metrics.ctr, 4),
            "conversions": row.metrics.conversions,
            "cpa_brl": row.metrics.cost_per_conversion / 1e6 if row.metrics.conversions > 0 else None,
        }
        for row in rows
    ]


def _get_search_terms(client: GoogleAdsClient, customer_id: str, date_range: str, min_impressions: int = 10) -> list[dict]:
    query = f"""
        SELECT
            search_term_view.search_term,
            campaign.id, campaign.name,
            metrics.impressions, metrics.clicks, metrics.cost_micros,
            metrics.ctr, metrics.conversions
        FROM search_term_view
        WHERE segments.date DURING {date_range}
          AND metrics.impressions >= {min_impressions}
        ORDER BY metrics.cost_micros DESC
        LIMIT 100
    """
    rows = _run_query(client, customer_id, query)
    return [
        {
            "search_term": row.search_term_view.search_term,
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "impressions": row.metrics.impressions,
            "clicks": row.metrics.clicks,
            "cost_brl": row.metrics.cost_micros / 1e6,
            "ctr": round(row.metrics.ctr, 4),
            "conversions": row.metrics.conversions,
        }
        for row in rows
    ]


def _pause_keyword(client: GoogleAdsClient, customer_id: str, ad_group_id: str, keyword_id: str) -> dict:
    ag_criterion_service = client.get_service("AdGroupCriterionService")
    criterion_op = client.get_type("AdGroupCriterionOperation")
    criterion = criterion_op.update
    criterion.resource_name = ag_criterion_service.ad_group_criterion_path(
        customer_id, ad_group_id, keyword_id
    )
    criterion.status = client.enums.AdGroupCriterionStatusEnum.PAUSED
    field_mask = client.get_type("FieldMask")
    field_mask.paths.append("status")
    criterion_op.update_mask.CopyFrom(field_mask)
    response = ag_criterion_service.mutate_ad_group_criteria(
        customer_id=customer_id, operations=[criterion_op]
    )
    return {"paused": str(response.results[0].resource_name)}


def _update_keyword_bid(client: GoogleAdsClient, customer_id: str, ad_group_id: str, keyword_id: str, new_bid_micros: int) -> dict:
    ag_criterion_service = client.get_service("AdGroupCriterionService")
    criterion_op = client.get_type("AdGroupCriterionOperation")
    criterion = criterion_op.update
    criterion.resource_name = ag_criterion_service.ad_group_criterion_path(
        customer_id, ad_group_id, keyword_id
    )
    criterion.cpc_bid_micros = new_bid_micros
    field_mask = client.get_type("FieldMask")
    field_mask.paths.append("cpc_bid_micros")
    criterion_op.update_mask.CopyFrom(field_mask)
    response = ag_criterion_service.mutate_ad_group_criteria(
        customer_id=customer_id, operations=[criterion_op]
    )
    return {"updated": str(response.results[0].resource_name), "new_bid_micros": new_bid_micros}


def _add_negative_keyword(client: GoogleAdsClient, customer_id: str, campaign_id: str, keyword_text: str, match_type: str) -> dict:
    campaign_criterion_service = client.get_service("CampaignCriterionService")
    campaign_service = client.get_service("CampaignService")
    criterion_op = client.get_type("CampaignCriterionOperation")
    criterion = criterion_op.create
    criterion.campaign = campaign_service.campaign_path(customer_id, campaign_id)
    criterion.negative = True
    criterion.keyword.text = keyword_text
    criterion.keyword.match_type = getattr(client.enums.KeywordMatchTypeEnum, match_type)
    response = campaign_criterion_service.mutate_campaign_criteria(
        customer_id=customer_id, operations=[criterion_op]
    )
    return {"added_negative": keyword_text, "resource": str(response.results[0].resource_name)}


# ─── Executor de tools (com guardrails) ─────────────────────────────────────

def _make_tool_executor(client: GoogleAdsClient, actions_counter: list):
    def execute(tool_name: str, inp: dict) -> Any:
        check_action_limit(len(actions_counter), settings.max_actions_per_run)
        block_budget_increase(tool_name)
        customer_id = inp.get("customer_id", "")

        if tool_name == "get_campaign_performance":
            return _get_campaign_performance(client, customer_id, inp["date_range"])

        if tool_name == "get_keyword_performance":
            return _get_keyword_performance(client, customer_id, inp["date_range"], inp.get("campaign_id"))

        if tool_name == "get_search_terms_report":
            return _get_search_terms(client, customer_id, inp["date_range"], inp.get("min_impressions", 10))

        if tool_name == "pause_keyword":
            result = {"skipped": "dry_run"} if settings.dry_run else _pause_keyword(
                client, customer_id, inp["ad_group_id"], inp["keyword_id"]
            )
            log_action(PLATFORM, "pause_keyword", inp["keyword_id"], inp, str(result), settings.dry_run)
            actions_counter.append(1)
            return result

        if tool_name == "update_keyword_bid":
            adjusted_bid = clamp_bid_change(
                inp["current_bid_micros"], inp["new_bid_micros"],
                settings.max_bid_change_pct, inp["keyword_text"]
            )
            result = {"skipped": "dry_run", "adjusted_bid_micros": int(adjusted_bid)} if settings.dry_run else _update_keyword_bid(
                client, customer_id, inp["ad_group_id"], inp["keyword_id"], int(adjusted_bid)
            )
            log_action(PLATFORM, "update_keyword_bid", inp["keyword_id"], inp, str(result), settings.dry_run)
            actions_counter.append(1)
            return result

        if tool_name == "add_negative_keyword":
            result = {"skipped": "dry_run"} if settings.dry_run else _add_negative_keyword(
                client, customer_id, inp["campaign_id"], inp["keyword_text"], inp.get("match_type", "PHRASE")
            )
            log_action(PLATFORM, "add_negative_keyword", inp["keyword_text"], inp, str(result), settings.dry_run)
            actions_counter.append(1)
            return result

        raise ValueError(f"Tool desconhecida: {tool_name}")

    return execute


# ─── Entry point ─────────────────────────────────────────────────────────────

def run(customer_id: str, date_range: str = "LAST_7_DAYS") -> dict:
    log.info(f"[Google Ads] Iniciando agente | conta={customer_id} | período={date_range} | dry_run={settings.dry_run}")

    try:
        ads_client = _get_client()
        account_name = _get_account_name(ads_client, customer_id)
        actions_counter: list = []
        executor = _make_tool_executor(ads_client, actions_counter)

        actions, summary = run_decision_loop(
            platform="google_ads",
            performance_data={"customer_id": customer_id, "date_range": date_range},
            tools_schema=TOOLS_SCHEMA,
            tool_executor=executor,
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
        log.exception(f"Erro inesperado no agente Google Ads: {e}")
        notify_error(PLATFORM, str(e))
        return {"status": "error", "error": str(e)}
