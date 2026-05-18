"""
Agente especialista em Google Ads.
Coleta dados de performance via API, decide com Gemini, executa ações com guardrails.

Sinais coletados (pré-fetch antes do Gemini):
  - Campanhas: impressões, cliques, CTR, CPC, CPA, ROAS, IS
  - Keywords: CTR, CPC, CPA, lance atual, bid strategy
  - Search Terms: termos reais com custo e conversões
  - Quality Score: QS por keyword + componentes (ETR, Ad Relevance, LP Experience)
  - Impression Share + Bid Strategy: IS, IS perdida por budget/rank, tipo de bidding
  - Ad Performance: RSA ad strength + métricas por anúncio
  - Device Breakdown: métricas por dispositivo (MOBILE/DESKTOP/TABLET)
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

_OPTIMIZATION_TOOLS = {"pause_keyword", "update_keyword_bid", "add_negative_keyword"}

# ─── Tools disponíveis para o Gemini ─────────────────────────────────────────

TOOLS_SCHEMA = [
    # ── Leitura de dados (fallback — normalmente dados já vêm pré-carregados) ─
    {
        "name": "get_campaign_performance",
        "description": "Retorna métricas de performance de todas as campanhas ativas (CTR, CPC, CPA, ROAS, impressões, cliques, conversões, custo, impression share). Use somente se precisar de dados específicos não cobertos pelo contexto inicial.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "ID da conta Google Ads"},
                "date_range": {"type": "string", "enum": ["LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS"]},
            },
            "required": ["customer_id", "date_range"],
        },
    },
    {
        "name": "get_keyword_performance",
        "description": "Retorna performance detalhada de keywords (CTR, CPC, CPA, lances, match type). Use somente se precisar de dados de keywords não cobertos pelo contexto inicial.",
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
        "description": "Retorna termos de busca reais que ativaram os anúncios. Use somente se precisar de drill-down adicional nos termos.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "date_range": {"type": "string", "enum": ["LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS"]},
                "min_impressions": {"type": "integer", "description": "Mínimo de impressões para retornar o termo"},
            },
            "required": ["customer_id", "date_range"],
        },
    },
    # ── Ações de otimização ──────────────────────────────────────────────────
    {
        "name": "pause_keyword",
        "description": "Pausa uma keyword que está desperdiçando verba (CTR muito baixo, sem conversão e gasto acima do limiar). NUNCA use em campanhas com Smart Bidding automático (TARGET_CPA, TARGET_ROAS, MAXIMIZE_CONVERSIONS) sem verificar primeiro. Inclua campaign_name, ad_group_name e match_type para rastreabilidade.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "campaign_id": {"type": "string", "description": "ID numérico da campanha"},
                "campaign_name": {"type": "string", "description": "Nome da campanha (obrigatório para rastreabilidade no dashboard)"},
                "ad_group_id": {"type": "string"},
                "ad_group_name": {"type": "string", "description": "Nome do grupo de anúncios (obrigatório para rastreabilidade)"},
                "keyword_id": {"type": "string"},
                "keyword_text": {"type": "string", "description": "Texto da keyword"},
                "match_type": {"type": "string", "description": "Tipo de correspondência da keyword: EXACT, PHRASE ou BROAD"},
                "reason": {"type": "string", "description": "Justificativa com dados específicos: CTR, impressões, custo, conversões"},
            },
            "required": ["customer_id", "campaign_id", "campaign_name", "ad_group_id", "ad_group_name", "keyword_id", "keyword_text", "match_type", "reason"],
        },
    },
    {
        "name": "update_keyword_bid",
        "description": "Atualiza o CPC máximo de uma keyword. SOMENTE use em campanhas com lance MANUAL (Manual CPC). NUNCA use em campanhas com Smart Bidding (TARGET_CPA, TARGET_ROAS, MAXIMIZE_CONVERSIONS, MAXIMIZE_CONVERSION_VALUE). Inclua campaign_name, ad_group_name e match_type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "campaign_id": {"type": "string", "description": "ID numérico da campanha"},
                "campaign_name": {"type": "string", "description": "Nome da campanha (obrigatório para rastreabilidade no dashboard)"},
                "ad_group_id": {"type": "string"},
                "ad_group_name": {"type": "string", "description": "Nome do grupo de anúncios (obrigatório para rastreabilidade)"},
                "keyword_id": {"type": "string"},
                "keyword_text": {"type": "string"},
                "match_type": {"type": "string", "description": "Tipo de correspondência da keyword: EXACT, PHRASE ou BROAD"},
                "current_bid_micros": {"type": "integer", "description": "Lance atual em micros (1 real = 1.000.000 micros)"},
                "new_bid_micros": {"type": "integer", "description": "Novo lance proposto em micros"},
                "reason": {"type": "string", "description": "Justificativa com CPA atual, meta de CPA e bid strategy confirmada como manual"},
            },
            "required": ["customer_id", "campaign_id", "campaign_name", "ad_group_id", "ad_group_name", "keyword_id", "keyword_text", "match_type", "current_bid_micros", "new_bid_micros", "reason"],
        },
    },
    {
        "name": "add_negative_keyword",
        "description": "Adiciona uma keyword negativa em uma campanha para bloquear tráfego irrelevante. CRÍTICO: keyword_text DEVE ser o search_term exato do relatório de termos de busca — NUNCA use o texto de uma keyword positiva existente (gera conflito de leilão). Inclua campaign_name para rastreabilidade.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "campaign_id": {"type": "string"},
                "campaign_name": {"type": "string", "description": "Nome da campanha onde a negativa será adicionada (obrigatório para rastreabilidade no dashboard)"},
                "keyword_text": {"type": "string", "description": "DEVE ser o search_term exato do relatório de termos de busca, não um texto de keyword positiva"},
                "match_type": {
                    "type": "string",
                    "enum": ["EXACT", "PHRASE", "BROAD"],
                    "description": "EXACT para bloquear apenas aquela busca específica (preferido); PHRASE para bloquear variações que contenham o termo em sequência; BROAD com extrema cautela",
                },
                "reason": {"type": "string", "description": "Justificativa com: o search_term exato, cliques, custo, e por que é irrelevante para o negócio"},
            },
            "required": ["customer_id", "campaign_id", "campaign_name", "keyword_text", "match_type", "reason"],
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


def _run_query(client: GoogleAdsClient, customer_id: str, query: str) -> list:
    """Executa GAQL com retry automático em backoff exponencial."""
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


# ─── Pré-fetch: funções de coleta de dados ───────────────────────────────────

def _get_account_name(client: GoogleAdsClient, customer_id: str) -> str:
    """Busca o nome descritivo da conta."""
    try:
        rows = _run_query(client, customer_id, "SELECT customer.descriptive_name FROM customer LIMIT 1")
        return rows[0].customer.descriptive_name if rows else ""
    except Exception:
        return ""


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
            "cost_brl": round(row.metrics.cost_micros / 1e6, 2),
            "ctr": round(row.metrics.ctr, 4),
            "avg_cpc_brl": round(row.metrics.average_cpc / 1e6, 2),
            "conversions": round(row.metrics.conversions, 2),
            "cpa_brl": round(row.metrics.cost_per_conversion / 1e6, 2) if row.metrics.conversions > 0 else None,
            "conversion_value": round(row.metrics.conversions_value, 2),
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
            ad_group_criterion.status,
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
            "status": row.ad_group_criterion.status.name,
            "current_bid_micros": row.ad_group_criterion.cpc_bid_micros,
            "current_bid_brl": round(row.ad_group_criterion.cpc_bid_micros / 1e6, 2),
            "impressions": row.metrics.impressions,
            "clicks": row.metrics.clicks,
            "cost_brl": round(row.metrics.cost_micros / 1e6, 2),
            "ctr": round(row.metrics.ctr, 4),
            "conversions": round(row.metrics.conversions, 2),
            "cpa_brl": round(row.metrics.cost_per_conversion / 1e6, 2) if row.metrics.conversions > 0 else None,
        }
        for row in rows
    ]


def _get_search_terms(client: GoogleAdsClient, customer_id: str, date_range: str, min_impressions: int = 10) -> list[dict]:
    query = f"""
        SELECT
            search_term_view.search_term,
            campaign.id, campaign.name,
            ad_group.id, ad_group.name,
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
            "ad_group_id": str(row.ad_group.id),
            "ad_group_name": row.ad_group.name,
            "impressions": row.metrics.impressions,
            "clicks": row.metrics.clicks,
            "cost_brl": round(row.metrics.cost_micros / 1e6, 2),
            "ctr": round(row.metrics.ctr, 4),
            "conversions": round(row.metrics.conversions, 2),
        }
        for row in rows
    ]


def _get_quality_scores(client: GoogleAdsClient, customer_id: str, date_range: str) -> list[dict]:
    """
    Quality Score por keyword com componentes detalhados.
    QS disponível via ad_group_criterion.quality_info (só para keywords ativas com dados suficientes).
    """
    query = f"""
        SELECT
            campaign.id, campaign.name,
            ad_group.id, ad_group.name,
            ad_group_criterion.criterion_id,
            ad_group_criterion.keyword.text,
            ad_group_criterion.quality_info.quality_score,
            ad_group_criterion.quality_info.search_predicted_ctr,
            ad_group_criterion.quality_info.ad_relevance,
            ad_group_criterion.quality_info.landing_page_experience,
            metrics.impressions, metrics.clicks, metrics.cost_micros
        FROM keyword_view
        WHERE ad_group_criterion.status != 'REMOVED'
          AND campaign.status = 'ENABLED'
          AND segments.date DURING {date_range}
          AND ad_group_criterion.quality_info.quality_score > 0
        ORDER BY ad_group_criterion.quality_info.quality_score ASC, metrics.cost_micros DESC
        LIMIT 100
    """
    rows = _run_query(client, customer_id, query)
    results = []
    for row in rows:
        qs = row.ad_group_criterion.quality_info.quality_score
        if qs and qs > 0:
            results.append({
                "campaign_id": str(row.campaign.id),
                "campaign_name": row.campaign.name,
                "ad_group_id": str(row.ad_group.id),
                "ad_group_name": row.ad_group.name,
                "keyword_id": str(row.ad_group_criterion.criterion_id),
                "keyword_text": row.ad_group_criterion.keyword.text,
                "quality_score": qs,
                "search_predicted_ctr": row.ad_group_criterion.quality_info.search_predicted_ctr.name,
                "ad_relevance": row.ad_group_criterion.quality_info.ad_relevance.name,
                "landing_page_experience": row.ad_group_criterion.quality_info.landing_page_experience.name,
                "impressions": row.metrics.impressions,
                "clicks": row.metrics.clicks,
                "cost_brl": round(row.metrics.cost_micros / 1e6, 2),
            })
    return results


def _get_impression_share_and_strategy(client: GoogleAdsClient, customer_id: str, date_range: str) -> list[dict]:
    """
    Impression Share + tipo de bid strategy por campanha.
    Essencial para detectar Smart Bidding e IS perdida por rank vs. budget.
    """
    query = f"""
        SELECT
            campaign.id, campaign.name,
            campaign.bidding_strategy_type,
            metrics.impressions, metrics.clicks, metrics.cost_micros,
            metrics.search_impression_share,
            metrics.search_budget_lost_impression_share,
            metrics.search_rank_lost_impression_share,
            metrics.search_top_impression_share,
            metrics.search_absolute_top_impression_share
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
            "bid_strategy_type": row.campaign.bidding_strategy_type.name,
            "is_smart_bidding": row.campaign.bidding_strategy_type.name in (
                "TARGET_CPA", "TARGET_ROAS", "MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE"
            ),
            "impressions": row.metrics.impressions,
            "clicks": row.metrics.clicks,
            "cost_brl": round(row.metrics.cost_micros / 1e6, 2),
            "impression_share": round(row.metrics.search_impression_share, 3),
            "is_lost_budget": round(row.metrics.search_budget_lost_impression_share, 3),
            "is_lost_rank": round(row.metrics.search_rank_lost_impression_share, 3),
            "top_impression_share": round(row.metrics.search_top_impression_share, 3),
            "abs_top_impression_share": round(row.metrics.search_absolute_top_impression_share, 3),
        }
        for row in rows
    ]


def _get_ad_performance(client: GoogleAdsClient, customer_id: str, date_range: str) -> list[dict]:
    """
    Performance de anúncios RSA com Ad Strength.
    Identifica anúncios com Ad Strength Poor/Average e baixo CTR.
    """
    query = f"""
        SELECT
            campaign.id, campaign.name,
            ad_group.id, ad_group.name,
            ad_group_ad.ad.id,
            ad_group_ad.ad_strength,
            ad_group_ad.status,
            metrics.impressions, metrics.clicks, metrics.ctr,
            metrics.cost_micros, metrics.conversions
        FROM ad_group_ad
        WHERE ad_group_ad.status = 'ENABLED'
          AND campaign.status = 'ENABLED'
          AND segments.date DURING {date_range}
        ORDER BY metrics.impressions DESC
        LIMIT 100
    """
    rows = _run_query(client, customer_id, query)
    return [
        {
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "ad_group_id": str(row.ad_group.id),
            "ad_group_name": row.ad_group.name,
            "ad_id": str(row.ad_group_ad.ad.id),
            "ad_strength": row.ad_group_ad.ad_strength.name,
            "impressions": row.metrics.impressions,
            "clicks": row.metrics.clicks,
            "ctr": round(row.metrics.ctr, 4),
            "cost_brl": round(row.metrics.cost_micros / 1e6, 2),
            "conversions": round(row.metrics.conversions, 2),
        }
        for row in rows
    ]


def _get_device_breakdown(client: GoogleAdsClient, customer_id: str, date_range: str) -> list[dict]:
    """
    Performance por dispositivo (MOBILE / DESKTOP / TABLET) por campanha.
    Útil para identificar disparidade de performance mobile vs. desktop.
    """
    query = f"""
        SELECT
            campaign.id, campaign.name,
            segments.device,
            metrics.impressions, metrics.clicks, metrics.cost_micros,
            metrics.ctr, metrics.conversions, metrics.cost_per_conversion
        FROM campaign
        WHERE campaign.status = 'ENABLED'
          AND segments.date DURING {date_range}
          AND segments.device IN ('DESKTOP', 'MOBILE', 'TABLET')
        ORDER BY campaign.id, metrics.cost_micros DESC
    """
    rows = _run_query(client, customer_id, query)
    return [
        {
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "device": row.segments.device.name,
            "impressions": row.metrics.impressions,
            "clicks": row.metrics.clicks,
            "cost_brl": round(row.metrics.cost_micros / 1e6, 2),
            "ctr": round(row.metrics.ctr, 4),
            "conversions": round(row.metrics.conversions, 2),
            "cpa_brl": round(row.metrics.cost_per_conversion / 1e6, 2) if row.metrics.conversions > 0 else None,
        }
        for row in rows
    ]


# ─── Ações de otimização (mutations) ─────────────────────────────────────────

def _enable_keyword(client: GoogleAdsClient, customer_id: str, ad_group_id: str, keyword_id: str) -> dict:
    """Reativa uma keyword pausada (operação de revert)."""
    ag_criterion_service = client.get_service("AdGroupCriterionService")
    criterion_op = client.get_type("AdGroupCriterionOperation")
    criterion = criterion_op.update
    criterion.resource_name = ag_criterion_service.ad_group_criterion_path(
        customer_id, ad_group_id, keyword_id
    )
    criterion.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
    field_mask = client.get_type("FieldMask")
    field_mask.paths.append("status")
    criterion_op.update_mask.CopyFrom(field_mask)
    response = ag_criterion_service.mutate_ad_group_criteria(
        customer_id=customer_id, operations=[criterion_op]
    )
    return {"enabled": str(response.results[0].resource_name)}


def _remove_negative_keyword(client: GoogleAdsClient, customer_id: str, resource_name: str) -> dict:
    """Remove uma keyword negativa pelo resource_name (operação de revert)."""
    campaign_criterion_service = client.get_service("CampaignCriterionService")
    criterion_op = client.get_type("CampaignCriterionOperation")
    criterion_op.remove = resource_name
    campaign_criterion_service.mutate_campaign_criteria(
        customer_id=customer_id, operations=[criterion_op]
    )
    return {"removed": resource_name}


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
    customer_id: str,
    actions_detail: list[dict],
    selected_indices: list[int] | None = None,
) -> dict:
    """
    Executa em produção as ações validadas no dry-run.
    selected_indices: se fornecido, executa apenas os índices listados.
    Retorna o mesmo formato de run() para compatibilidade com db.mark_executed.
    """
    client = _get_client()
    account_name = _get_account_name(client, customer_id)

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
            if tool == "pause_keyword":
                result = _pause_keyword(client, customer_id, inp["ad_group_id"], inp["keyword_id"])
                log_action(PLATFORM, tool, inp["keyword_id"], inp, str(result), False)

            elif tool == "update_keyword_bid":
                # Usa o lance já ajustado pelo clamp do dry-run (não recalcula)
                adjusted_bid = dry_result.get("adjusted_bid_micros") or inp["new_bid_micros"]
                result = _update_keyword_bid(
                    client, customer_id, inp["ad_group_id"], inp["keyword_id"], int(adjusted_bid)
                )
                log_action(PLATFORM, tool, inp["keyword_id"], inp, str(result), False)

            elif tool == "add_negative_keyword":
                result = _add_negative_keyword(
                    client, customer_id, inp["campaign_id"],
                    inp["keyword_text"], inp.get("match_type", "PHRASE"),
                )
                log_action(PLATFORM, tool, inp["keyword_text"], inp, str(result), False)

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

def revert_stored_actions(customer_id: str, actions_detail: list[dict]) -> dict:
    """
    Reverte ações de uma sessão já executada.
    actions_detail deve vir da sessão EXECUTADA (resultado real, com resource names).
    """
    client = _get_client()
    account_name = _get_account_name(client, customer_id)

    reverted: list[dict] = []
    errors:   list[dict] = []

    for action in reversed(actions_detail):   # ordem reversa por segurança
        tool   = action["tool"]
        inp    = action["input"]
        result = action.get("result", {})

        try:
            if tool == "pause_keyword":
                rv = _enable_keyword(client, customer_id, inp["ad_group_id"], inp["keyword_id"])
                log_action(PLATFORM, f"revert_{tool}", inp["keyword_id"], inp, str(rv), False)

            elif tool == "update_keyword_bid":
                original_bid = inp["current_bid_micros"]
                rv = _update_keyword_bid(
                    client, customer_id, inp["ad_group_id"], inp["keyword_id"], int(original_bid)
                )
                log_action(PLATFORM, f"revert_{tool}", inp["keyword_id"], inp, str(rv), False)

            elif tool == "add_negative_keyword":
                resource_name = result.get("resource")
                if not resource_name:
                    errors.append({"tool": tool, "error": "resource_name ausente no resultado — revert impossível"})
                    continue
                rv = _remove_negative_keyword(client, customer_id, resource_name)
                log_action(PLATFORM, f"revert_{tool}", inp["keyword_text"], inp, str(rv), False)

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

def run(customer_id: str, date_range: str = "LAST_7_DAYS") -> dict:
    log.info(f"[Google Ads] Iniciando | conta={customer_id} | período={date_range} | dry_run={settings.dry_run}")

    try:
        ads_client = _get_client()
        account_name = _get_account_name(ads_client, customer_id)
        client_config = settings.get_google_account_config(customer_id)

        log.info(f"[Google Ads] Conta: '{account_name}' | CPA meta: R${client_config['target_cpa']:.2f} | ROAS meta: {client_config['target_roas']:.1f}x")

        # ── Pré-fetch completo de todos os sinais ─────────────────────────────
        log.info(f"[Google Ads] Iniciando pré-fetch de dados...")
        prefetched_data = {
            "campaigns": _safe_fetch(
                "campaigns", _get_campaign_performance, ads_client, customer_id, date_range
            ),
            "keywords": _safe_fetch(
                "keywords", _get_keyword_performance, ads_client, customer_id, date_range
            ),
            "search_terms": _safe_fetch(
                "search_terms", _get_search_terms, ads_client, customer_id, date_range
            ),
            "quality_scores": _safe_fetch(
                "quality_scores", _get_quality_scores, ads_client, customer_id, date_range
            ),
            "impression_share": _safe_fetch(
                "impression_share", _get_impression_share_and_strategy, ads_client, customer_id, date_range
            ),
            "ad_performance": _safe_fetch(
                "ad_performance", _get_ad_performance, ads_client, customer_id, date_range
            ),
            "device_breakdown": _safe_fetch(
                "device_breakdown", _get_device_breakdown, ads_client, customer_id, date_range
            ),
        }
        log.info(f"[Google Ads] Pré-fetch concluído. Enviando ao Gemini...")

        actions_counter: list = []
        executor = _make_tool_executor(ads_client, actions_counter)

        actions, summary = run_decision_loop(
            platform="google_ads",
            performance_data={"customer_id": customer_id, "date_range": date_range},
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
        log.exception(f"Erro inesperado no agente Google Ads: {e}")
        notify_error(PLATFORM, str(e))
        return {"status": "error", "error": str(e)}
