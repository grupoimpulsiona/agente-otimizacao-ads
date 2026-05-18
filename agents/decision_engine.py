"""
Motor de decisão baseado em Gemini com function calling.
Recebe dados pré-carregados de performance e decide quais ações executar.

Arquitetura:
  - Dados são pré-carregados pelo agente antes de chamar este módulo
  - O Gemini recebe contexto completo na mensagem inicial (não precisa "buscar dados")
  - Function calls são usadas APENAS para executar ações de otimização
"""

import json
from typing import Any, Callable
import google.generativeai as genai
from google.generativeai import types
import google.ai.generativelanguage as glm
from config.settings import settings
from utils.logger import get_logger

log = get_logger("decision_engine")

genai.configure(api_key=settings.gemini_api_key)


# ─── System Prompts Especializados ───────────────────────────────────────────

SYSTEM_GOOGLE_ADS = """Você é um Gestor de Tráfego Sênior com 10+ anos de experiência em Google Ads (Search, Display, YouTube), especializado em diagnóstico cirúrgico e otimização de contas de performance.

## METODOLOGIA DE ANÁLISE

Siga esta ordem obrigatoriamente ao receber os dados:

### 1. PANORAMA DA CONTA
- Qual o gasto total no período? Está dentro do budget mensal?
- Qual a tendência geral de CPA e ROAS?
- Alguma campanha concentra mais de 70% do gasto?

### 2. DIAGNÓSTICO POR CAMPANHA
Para cada campanha, verifique:
- **Impression Share (IS)**: IS < 60% é sinal de problema
  - IS perdida por RANK > 30% → problema de Quality Score ou lance baixo
  - IS perdida por BUDGET > 30% → campanha limitada por orçamento (informe no resumo, mas NÃO aumente o orçamento)
- **Bid Strategy**: Identifique se é Smart Bidding (TARGET_CPA, TARGET_ROAS, MAXIMIZE_CONVERSIONS, MAXIMIZE_CONVERSION_VALUE)
  - Smart Bidding → NUNCA ajuste lances de keywords. O algoritmo gerencia automaticamente.
  - Manual CPC → lances de keyword são ajustáveis

### 3. ANÁLISE DE KEYWORDS
Critérios de intervenção:
- **PAUSAR** quando: CTR < 0,3% E impressões > 300 E conversões = 0 E custo > R$10
- **PAUSAR** quando: CPA > 3× meta E conversões < 2 (dados insuficientes para otimizar)
- **REDUZIR LANCE 15%** quando: CPA entre 1,5× e 3× meta E conversões ≥ 2 E campanha Manual CPC
- **AUMENTAR LANCE 10%** quando: ROAS > meta × 1,5 E IS < 50% E campanha Manual CPC E bid atual não está no teto

### 4. QUALITY SCORE
- QS ≤ 4 em keyword com gasto > R$20: reportar no resumo com componente mais fraco (ETR / Ad Relevance / LP Experience)
- QS ≤ 3 em qualquer keyword ativa: sinalizar urgência no resumo
- QS influencia IS e CPC — sempre conecte QS baixo com IS perdida por rank

### 5. SEARCH TERMS (termos de busca)
- Termo com conversões = 0 E cliques > 5 E custo > R$15 E claramente irrelevante → negativar (PHRASE)
- Termo muito genérico (ex: "grátis", "como fazer", "o que é") → negativar (BROAD)
- Regra de ouro: duvide, mas não negativar termos que possam ser de intenção de compra

### 6. RSA / ANÚNCIOS
- Ad Strength "Poor": urgência máxima — reportar no resumo
- Ad Strength "Average": recomendar melhoria de headlines
- Ad group com apenas 1 anúncio ativo: sinalizar no resumo

### 7. DEVICE BREAKDOWN
- Mobile com CTR muito abaixo de Desktop (< 50%): verificar se landing page está otimizada para mobile
- Mobile com CPA 2× acima de Desktop: considerar ajuste de lance por device no resumo

## REGRAS ABSOLUTAS
1. NUNCA aumente orçamento de campanhas (ferramenta bloqueada por política)
2. NUNCA ajuste lances de keywords em campanhas com Smart Bidding automático
3. Mínimo de dados para agir: dados pré-definidos nos guardrails da mensagem
4. Cada ação DEVE ter uma justificativa com número específico dos dados
5. Dúvida → não aja. Prefira recomendar no resumo a executar ação sem dado sólido

## FORMATO DO RESUMO FINAL
Encerre SEMPRE com este resumo estruturado em português:

RESUMO DA OTIMIZAÇÃO — [Nome da conta]

SITUAÇÃO GERAL:
[2-3 frases objetivas sobre o estado atual da conta — o que está funcionando e o que não está]

AÇÕES EXECUTADAS:
[Lista cada ação com: tipo | entidade | dado que justificou | resultado esperado]
Exemplo: PAUSA | Keyword "tênis barato" | CTR 0,1%, 450 impressões, R$18 sem conversão | Eliminar desperdício estimado de R$X/semana

ATENÇÃO MANUAL NECESSÁRIA:
[Itens que precisam de intervenção humana, incluindo:]
- Campanhas com Smart Bidding que precisam de ajuste de meta de CPA/ROAS
- Landing pages com LP Experience baixo
- Ad groups com Ad Strength Poor
- Campanhas limitadas por orçamento

PRÓXIMOS 7 DIAS — O QUE MONITORAR:
[Métricas e entidades específicas para acompanhar]"""


SYSTEM_META_ADS = """Você é um Gestor de Tráfego Sênior com 10+ anos de experiência em Meta Ads (Facebook + Instagram), especializado em diagnóstico de fadiga de audiência, otimização de criativos e controle de CPA/ROAS.

## METODOLOGIA DE ANÁLISE

Siga esta ordem obrigatoriamente ao receber os dados:

### 1. PANORAMA DA CONTA
- Gasto total no período vs. budget mensal
- Tendência geral de CPM: subiu ou caiu em relação ao esperado?
- Alguma campanha/ad set concentra mais de 70% do gasto?

### 2. DIAGNÓSTICO DE FADIGA DE AUDIÊNCIA
Sinais de fadiga (frequência + CTR + CPM):
- **Fadiga confirmada**: frequência > 4,0 E CTR caiu E CPM subiu
- **Fadiga em início**: frequência > 3,0 E CTR caindo
- Audiência fatigada → pausar ad set OU recomendar novo criativo (não há ferramenta de edição)

### 3. ANÁLISE DE AD SETS
Critérios de intervenção:
- **PAUSAR** quando: frequência > 4,0 E CTR < 0,8% E gasto > R$30 (fadiga clara)
- **PAUSAR** quando: CPA > 3× meta E gasto > R$50 E conversões < 0,5
- **PAUSAR** quando: CTR < 0,5% E impressões > 1.000 E gasto > R$30 sem conversão
- **REDUZIR LANCE** quando: CPA entre 1,5× e 3× meta E impressões > 500 (dados válidos)
- Regra: não pausar ad sets com < 500 impressões — dados insuficientes

### 4. ANÁLISE DE ADS (criativos individuais)
- **PAUSAR** quando: CTR < 0,5% E impressões > 500 E gasto > R$20 sem conversão
- **PAUSAR** quando: frequência > 5 E CTR < 0,8% (criativo saturado no nível do anúncio)
- Múltiplos anúncios ruins no mesmo ad set → pausar os piores, deixar no máximo 2

### 5. PLACEMENT BREAKDOWN (quando disponível)
- Audience Network > 40% do gasto E CPA 2× acima da média → recomendar exclusão no resumo
- Stories/Reels com CPM muito alto (> 3× do feed) E CTR baixo → recomendar criativo vertical específico

### 6. DEMOGRÁFICO (quando disponível)
- Faixa etária ou gênero com CPA 2× acima da meta E gasto significativo → recomendar ajuste de segmentação no resumo
- Concentração alta em um segmento demográfico com frequência alta → sinal de audiência estreita

## REGRAS ABSOLUTAS
1. NUNCA aumente orçamento de campanhas ou ad sets (ferramenta bloqueada)
2. Mínimo de dados para agir: dados pré-definidos nos guardrails da mensagem
3. Cada ação DEVE ter justificativa com número específico dos dados
4. Dúvida → não aja. Prefira recomendar no resumo

## FORMATO DO RESUMO FINAL
Encerre SEMPRE com este resumo estruturado em português:

RESUMO DA OTIMIZAÇÃO — [Nome da conta]

SITUAÇÃO GERAL:
[2-3 frases objetivas sobre o estado atual — o que está funcionando, tendências de CPM/CTR]

AÇÕES EXECUTADAS:
[Lista cada ação com: tipo | entidade | dado que justificou | resultado esperado]
Exemplo: PAUSA | Ad Set "Lookalike 1%" | Frequência 4,8, CTR caiu para 0,3%, CPA R$320 (meta R$100) | Reduzir desperdício

ATENÇÃO MANUAL NECESSÁRIA:
[Itens que precisam de intervenção humana, incluindo:]
- Criativos que precisam ser renovados (com dados de frequência e CTR)
- Exclusões de placement recomendadas
- Ajustes de segmentação demográfica

PRÓXIMOS 7 DIAS — O QUE MONITORAR:
[Métricas e entidades específicas para acompanhar]"""


# ─── Conversão de tools ───────────────────────────────────────────────────────

def _convert_tools_to_gemini(tools_schema: list[dict]) -> list:
    """Converte tools do formato OpenAPI para o formato Gemini."""
    function_declarations = []
    for tool in tools_schema:
        function_declarations.append(
            types.FunctionDeclaration(
                name=tool["name"],
                description=tool["description"],
                parameters=tool.get("input_schema", {}),
            )
        )
    return [types.Tool(function_declarations=function_declarations)]


# ─── Loop principal ───────────────────────────────────────────────────────────

def run_decision_loop(
    platform: str,
    performance_data: dict,
    tools_schema: list[dict],
    tool_executor: Callable[[str, dict], Any],
    client_config: dict | None = None,
    prefetched_data: dict | None = None,
) -> tuple[list[dict], str]:
    """
    Loop agêntico principal com Gemini.

    Args:
        platform: "google_ads" ou "meta_ads"
        performance_data: dados básicos de contexto (ignorado quando prefetched_data fornecido)
        tools_schema: ferramentas disponíveis para o agente
        tool_executor: função que executa as ferramentas
        client_config: configuração por cliente (name, segment, target_cpa, target_roas, monthly_budget)
        prefetched_data: dados pré-carregados (campanhas, keywords, QS, IS, etc.)

    Returns:
        (lista_de_acoes_executadas, resumo_texto)
    """
    system = SYSTEM_GOOGLE_ADS if platform == "google_ads" else SYSTEM_META_ADS

    # ── Seção de configuração do cliente ─────────────────────────────────────
    client_section = ""
    if client_config:
        client_section = (
            f"\n\n═══ CONFIGURAÇÃO DO CLIENTE ═══\n"
            f"Nome: {client_config.get('name', 'Não informado')}\n"
            f"Segmento: {client_config.get('segment', 'Não informado')}\n"
            f"Meta de CPA: R${float(client_config.get('target_cpa', settings.target_cpa)):.2f}\n"
            f"Meta de ROAS: {float(client_config.get('target_roas', settings.target_roas)):.1f}x\n"
            f"Budget Mensal: R${float(client_config.get('monthly_budget', 0)):.0f}\n"
        )

    # ── Seção de guardrails ativos ────────────────────────────────────────────
    guardrails_section = (
        f"\n\n═══ GUARDRAILS ATIVOS ═══\n"
        f"Variação máxima de lance: ±{settings.max_bid_change_pct * 100:.0f}%\n"
        f"Mínimo de impressões para decisão: {settings.min_data_impressions}\n"
        f"Mínimo de cliques para decisão: {settings.min_data_clicks}\n"
        f"Aumento de orçamento: BLOQUEADO\n"
        f"Máximo de ações por execução: {settings.max_actions_per_run}\n"
        f"Modo: {'⚠️ DRY-RUN — simulação, nenhuma ação real será executada' if settings.dry_run else '🚀 PRODUÇÃO — ações reais serão executadas'}\n"
    )

    # ── Seção de dados pré-carregados ─────────────────────────────────────────
    if prefetched_data:
        data_section = "\n\n═══ DADOS PRÉ-CARREGADOS — ANALISE ESTES DADOS ANTES DE QUALQUER AÇÃO ═══\n"
        data_section += "INSTRUÇÃO: Todos os dados abaixo já foram coletados. Use as ferramentas APENAS para pausar, ajustar lances ou adicionar negativos — não para buscar mais dados.\n"

        dataset_labels = {
            "campaigns": "CAMPANHAS — Performance Geral",
            "keywords": "KEYWORDS — Performance Detalhada",
            "search_terms": "TERMOS DE BUSCA — Reais dos Usuários",
            "quality_scores": "QUALITY SCORE — por Keyword",
            "impression_share": "IMPRESSION SHARE + BID STRATEGY — por Campanha",
            "ad_performance": "ANÚNCIOS (RSA) — Ad Strength e Métricas",
            "device_breakdown": "BREAKDOWN POR DISPOSITIVO",
            "ad_sets": "AD SETS — Performance Detalhada",
            "ads": "ANÚNCIOS — Performance Individual",
            "placements": "BREAKDOWN POR PLACEMENT",
            "demographics": "BREAKDOWN DEMOGRÁFICO (Idade/Gênero)",
        }

        for key, value in prefetched_data.items():
            if value:
                label = dataset_labels.get(key, key.upper().replace("_", " "))
                data_section += f"\n### {label}\n"
                data_section += json.dumps(value, ensure_ascii=False, indent=2)
                data_section += "\n"
            else:
                label = dataset_labels.get(key, key)
                data_section += f"\n### {label}: (sem dados no período)\n"
    else:
        data_section = (
            f"\n\n═══ CONTEXTO INICIAL ═══\n"
            f"{json.dumps(performance_data, ensure_ascii=False, indent=2)}\n"
            f"\nBusque os dados de performance usando as ferramentas disponíveis antes de tomar decisões.\n"
        )

    user_message = (
        "Analise os dados de performance e execute as otimizações necessárias conforme sua metodologia."
        f"{client_section}"
        f"{guardrails_section}"
        f"{data_section}"
    )

    # ── Inicialização do Gemini ───────────────────────────────────────────────
    gemini_tools = _convert_tools_to_gemini(tools_schema)
    model = genai.GenerativeModel(
        model_name=settings.gemini_model,
        system_instruction=system,
        tools=gemini_tools,
    )

    chat = model.start_chat()
    actions_taken: list[dict] = []
    max_iterations = 20

    log.info(f"[{platform}] Enviando {len(prefetched_data or {})} datasets pré-carregados ao Gemini")
    response = chat.send_message(user_message)

    for iteration in range(max_iterations):
        log.info(f"[{platform}] Iteração {iteration + 1}/{max_iterations}")

        candidate = response.candidates[0]
        finish_reason = candidate.finish_reason.name
        log.info(f"[{platform}] finish_reason={finish_reason}")

        # Coleta todas as function calls desta resposta
        function_calls = [
            part.function_call
            for part in candidate.content.parts
            if hasattr(part, "function_call") and part.function_call and part.function_call.name
        ]

        if not function_calls:
            summary = _extract_text(candidate.content.parts)
            log.info(f"[{platform}] Agente finalizou. Ações executadas: {len(actions_taken)}")
            return actions_taken, summary

        # Executa cada tool e coleta as respostas
        tool_response_parts = []
        for fc in function_calls:
            tool_name = fc.name
            tool_input = dict(fc.args)

            log.info(f"[{platform}] Tool call: {tool_name} | input={json.dumps(tool_input, ensure_ascii=False)}")

            try:
                result = tool_executor(tool_name, tool_input)
                actions_taken.append({
                    "tool": tool_name,
                    "input": tool_input,
                    "result": result,
                    "description": _describe_action(tool_name, tool_input, result),
                })
                tool_response_parts.append(
                    glm.Part(
                        function_response=glm.FunctionResponse(
                            name=tool_name,
                            response={"result": json.dumps(result, ensure_ascii=False, default=str)},
                        )
                    )
                )
            except Exception as e:
                log.error(f"[{platform}] Erro na tool {tool_name}: {e}")
                tool_response_parts.append(
                    glm.Part(
                        function_response=glm.FunctionResponse(
                            name=tool_name,
                            response={"error": str(e)},
                        )
                    )
                )

        response = chat.send_message(tool_response_parts)

    log.warning(f"[{platform}] Limite de iterações atingido ({max_iterations}).")
    return actions_taken, "Limite de iterações atingido. Verifique os logs para detalhes."


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _extract_text(parts) -> str:
    """Extrai texto de uma lista de parts do Gemini."""
    return " ".join(
        part.text for part in parts
        if hasattr(part, "text") and part.text
    ).strip()


def _describe_action(tool_name: str, inp: dict, result: Any) -> str:
    """Gera descrição legível de uma ação para o WhatsApp."""
    descriptions = {
        "pause_keyword": (
            f"Pausou keyword '{inp.get('keyword_text', inp.get('keyword_id', '?'))}'"
            f" | Motivo: {inp.get('reason', '—')}"
        ),
        "update_keyword_bid": (
            f"Ajustou lance de '{inp.get('keyword_text', '?')}'"
            f" de R${inp.get('current_bid_micros', 0) / 1e6:.2f}"
            f" → R${inp.get('new_bid_micros', 0) / 1e6:.2f}"
            f" | {inp.get('reason', '—')}"
        ),
        "add_negative_keyword": (
            f"Adicionou negativa '{inp.get('keyword_text', '?')}'"
            f" [{inp.get('match_type', 'PHRASE')}]"
            f" | {inp.get('reason', '—')}"
        ),
        "pause_ad": (
            f"Pausou anúncio '{inp.get('ad_name', inp.get('ad_id', '?'))}'"
            f" | {inp.get('reason', '—')}"
        ),
        "pause_ad_set": (
            f"Pausou ad set '{inp.get('ad_set_name', inp.get('ad_set_id', '?'))}'"
            f" | {inp.get('reason', '—')}"
        ),
        "update_ad_set_bid": (
            f"Ajustou lance do ad set '{inp.get('ad_set_name', '?')}'"
            f" de R${inp.get('current_bid_amount', 0) / 100:.2f}"
            f" → R${inp.get('new_bid_amount', 0) / 100:.2f}"
            f" | {inp.get('reason', '—')}"
        ),
    }
    return descriptions.get(tool_name, f"{tool_name}: {json.dumps(inp, ensure_ascii=False)}")
