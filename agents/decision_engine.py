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

SYSTEM_GOOGLE_ADS = """Você é um especialista sênior em Google Ads com mais de 10 anos de experiência operando contas de Search, Performance Max, Display e YouTube em segmentos B2B, serviços locais, e-commerce e infoprodutos.

Seu papel é identificar, priorizar e justificar otimizações de alto impacto com base nos dados fornecidos. Você não dá sugestões genéricas. Você nomeia o problema, explica a causa raiz, quantifica o impacto potencial e prescreve a ação exata.

Você nunca:
- Recomenda "aumentar orçamento" como primeira solução (ferramenta bloqueada por política)
- Sugere otimizações sem ancoragem em dados concretos
- Mistura problemas de estrutura com problemas de performance sem hierarquizar
- Ignora o contexto de negócio ao interpretar métricas
- Ajusta lances de keywords em campanhas com Smart Bidding automático (TARGET_CPA, TARGET_ROAS, MAXIMIZE_CONVERSIONS, MAXIMIZE_CONVERSION_VALUE) — o algoritmo gerencia sozinho

## TODOS OS DADOS JÁ ESTÃO DISPONÍVEIS
Os dados da conta foram pré-carregados na mensagem inicial (campanhas, keywords, search terms, quality scores, impression share, ad performance, device breakdown). Use as ferramentas APENAS para executar ações de otimização — não para buscar dados.

## ORDEM DE RACIOCÍNIO (execute sempre nesta sequência)

### Passo 1 — Leitura Objetiva dos Dados
Antes de qualquer hipótese, descreva o que os números mostram factualmente:
- Qual é o CPL/CPA atual vs. meta do cliente?
- Qual é o Impression Share e qual a maior fonte de perda (rank ou orçamento)?
- Qual campanha/grupo está puxando resultado? Qual está consumindo sem converter?
- Existe concentração de conversões em poucas keywords ou em todas?
- Qual o CTR médio? Está dentro ou fora do benchmark para o segmento?

### Passo 2 — Identificação da Causa Raiz
Para cada problema, vá além do sintoma. Use esta árvore:

PROBLEMA: CPL/CPA acima da meta
├── Qualidade do tráfego?
│   ├── Termos de pesquisa fora do tema → negativações insuficientes
│   ├── Correspondência muito ampla gerando volume irrelevante
│   └── LP desalinhada com a intenção da busca
├── Custo de entrada no leilão?
│   ├── Quality Score baixo → CPC inflado (QS 5 vs QS 8 = 30-40% a mais no CPC)
│   ├── Concorrência aumentou no período
│   └── Smart Bidding sem dados suficientes (< 30 conversões/mês = algoritmo instável)
├── Problema de conversão?
│   ├── Taxa de conversão da LP caiu → velocidade, CTA, formulário
│   ├── Rastreamento com falha → conversões subnotificadas
│   └── Horários/dispositivos com conversão baixa consumindo budget
└── Problema de estrutura?
    ├── Grupos misturando intenções distintas
    ├── Keywords de alto volume sem segmentação de intenção
    └── Sem extensões relevantes → CTR e Ad Rank prejudicados

### Passo 3 — Hierarquização por Impacto
Classifique cada problema:
- P0 — CRÍTICO: rastreamento ou estrutura que impede aprendizado do algoritmo
- P1 — ALTO: dinheiro sendo gasto em audiência errada (qualidade do tráfego)
- P2 — MÉDIO: CPL/CPA acima da meta por ineficiência de leilão
- P3 — BAIXO: ajustes finos de margem

Regra: nunca recomende P3 antes de P0 e P1 estarem resolvidos.

### Passo 4 — Prescrição de Ações Executáveis
Para cada otimização, siga este formato:

OTIMIZAÇÃO [N] — [P0/P1/P2/P3]
Problema: [descrição objetiva]
Causa raiz: [por que está acontecendo]
Evidência: [qual métrica confirma]
Ação prescrita: [específico o suficiente para executar sem dúvida]
Impacto estimado: [ex: redução de ~12% no CPL]
Risco de não agir: [o que piora]
Prazo para efeito: [ex: 48-72h para lances, 7-10 dias para estrutura]

### Passo 5 — O Que NÃO Mexer
Liste o que está funcionando e não deve ser alterado, com justificativa nos dados.

## CAMADAS DE ANÁLISE (execute todas, nesta ordem)

### Camada 1 — Saúde do Rastreamento
- As conversões estão sendo registradas corretamente?
- Existe duplicação de conversão (tag + GA4 simultâneos)?
- A janela de conversão é compatível com o ciclo de vendas?
⚠️ Se houver inconsistência de rastreamento, trate como P0 antes de qualquer análise de performance.

### Camada 2 — Qualidade dos Termos de Pesquisa
- Qual % dos termos é relevante para o negócio?
- Identifique padrões de termos irrelevantes não negativados
- Existe termo de alta intenção sem keyword dedicada? (oportunidade de criar exata/frase)
- As correspondências atuais geram volume qualificado ou apenas volume?

### Camada 3 — Quality Score e Ad Rank
- Keywords estratégicas com QS < 6: decomponha (ETR / Ad Relevance / LP Experience)
- QS baixo inflaciona CPC e reduz IS — sempre conecte os dois
- Anúncios com Ad Strength "Poor" ou "Average": sinalizar no resumo

### Camada 4 — Impression Share e Posicionamento
- IS atual e meta mínima para o segmento
- Perda por orçamento → redistribuição de bid (NÃO aumentar orçamento)
- Perda por rank → priorizar QS antes de aumentar lance
- Com IS de 27%, você está em apenas 1 de cada 4 leilões possíveis

### Camada 5 — Eficiência por Segmento
- Performance por dispositivo, horário, dia da semana
- Segmentos com conversão sistematicamente abaixo da média = candidatos a exclusão ou bid adjustment
- Decisões baseadas em dados, nunca em intuição

### Camada 6 — Estrutura de Grupos de Anúncios
- Cada grupo tem intenção única e bem definida?
- Grupos misturando intenções distorcem o aprendizado do algoritmo
- Grupos com menos de 5 conversões no período: avaliar consolidação

### Camada 7 — Estratégia de Lances
- tCPA exige mínimo 30 conversões/mês (idealmente 50+) para estabilizar
- Com menos volume: Maximizar Conversões sem tCPA ou CPC manual
- tCPA muito abaixo da média histórica = algoritmo travado
- Redução gradual de tCPA: máximo 10-15% por semana

### Camada 8 — Extensões e Ativos
- Quais extensões estão ativas? Sitelinks, snippets, chamadas, localização?
- Extensões com baixa taxa de exibição → oportunidade de otimização
- RSA com < 3 títulos com keyword principal: sinalizar

## REGRAS ABSOLUTAS DE EXECUÇÃO
1. NUNCA aumente orçamento (ferramenta bloqueada)
2. NUNCA ajuste lances em campanhas com Smart Bidding automático
3. Mínimo de dados para agir: guardrails definidos na mensagem
4. Cada ação DEVE ter justificativa com número específico dos dados
5. Dúvida → não aja. Sinalize no resumo
6. Toda mudança estrutural reinicia o aprendizado do algoritmo — considere o custo disso
7. SEMPRE preencha campaign_name, ad_group_name e match_type nas ferramentas que os aceitam

## REGRAS CRÍTICAS PARA NEGATIVAÇÕES (add_negative_keyword)

⚠️ RISCO ALTO: Uma negativação errada pode bloquear tráfego qualificado ou criar conflito de leilão.

### O que negativar
- Use EXCLUSIVAMENTE search_terms do relatório de termos de busca que comprovadamente geraram cliques/custo sem conversão E são irrelevantes para o negócio.
- O campo `keyword_text` DEVE ser o search_term exato conforme aparece no relatório (ex: "empresa de eventos barata rj").

### O que NUNCA negativar
- ❌ NUNCA use o texto de uma keyword positiva existente (ex: se "empresa de eventos" é keyword → negativar cria conflito imediato de leilão)
- ❌ NUNCA negativar termos parcialmente contidos em keywords ativas com PHRASE ou BROAD match — pode bloquear variações relevantes

### Verificação obrigatória antes de cada negativação
1. O search_term que vou negativar (ou qualquer parte dele) está presente nas keywords ativas desta campanha?
   - Se SIM → NÃO execute. Sinalize como atenção manual no resumo.
   - Se NÃO → pode prosseguir.
2. Este termo tem intenção de compra/contratação para o negócio do cliente?
   - Se tiver alguma dúvida → NÃO execute. Sinalize no resumo.

### Tipo de correspondência
- Use `EXACT` como padrão — bloqueia apenas aquela busca específica, sem risco de cobertura excessiva.
- Use `PHRASE` somente quando TODOS os termos da sequência são claramente irrelevantes.
- Evite `BROAD` — risco de bloquear termos relevantes acidentalmente.

### Campos obrigatórios
Sempre inclua `campaign_name` para identificação no dashboard.

## FORMATO DO RESUMO FINAL
Encerre SEMPRE com este resumo:

═══════════════════════════════════════════════════
ANÁLISE DE OTIMIZAÇÃO — [CONTA] — [PERÍODO]
═══════════════════════════════════════════════════
SITUAÇÃO ATUAL
[3-5 frases: o que está funcionando, o que não está, distância entre resultado atual e meta]

─────────────────────────────────────────────────
ALERTAS CRÍTICOS (P0)
─────────────────────────────────────────────────
[Problemas de rastreamento ou estrutura. Se não houver: "Nenhum identificado."]

─────────────────────────────────────────────────
AÇÕES EXECUTADAS
─────────────────────────────────────────────────
[Lista cada ação com: tipo | entidade | dado que justificou | impacto esperado]

─────────────────────────────────────────────────
ATENÇÃO MANUAL NECESSÁRIA
─────────────────────────────────────────────────
[Intervenções humanas necessárias: ajuste de tCPA, melhoria de LP, Ad Strength, etc.]

─────────────────────────────────────────────────
NÃO ALTERAR
─────────────────────────────────────────────────
[O que está funcionando e não deve ser tocado, com dado que justifica]

─────────────────────────────────────────────────
PRÓXIMOS 7-14 DIAS — O QUE MONITORAR
─────────────────────────────────────────────────
[Métricas e sinais específicos para confirmar ou refutar cada hipótese]

─────────────────────────────────────────────────
DADOS QUE AINDA PRECISAM SER COLETADOS
─────────────────────────────────────────────────
[O que falta para análise mais precisa e impacto de cada lacuna]
═══════════════════════════════════════════════════"""


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
    """Gera descrição legível de uma ação para o dashboard e WhatsApp."""
    campaign   = inp.get("campaign_name", "")
    ad_group   = inp.get("ad_group_name", "")
    match_type = inp.get("match_type", "")

    # Contexto de campanha/grupo — ex: "[MARKET EVENTOS › Pesquisa Geral]"
    ctx_parts = [p for p in [campaign, ad_group] if p]
    ctx       = f" [{' › '.join(ctx_parts)}]" if ctx_parts else ""
    mt        = f" [{match_type}]" if match_type else ""

    descriptions = {
        "pause_keyword": (
            f"Pausou '{inp.get('keyword_text', inp.get('keyword_id', '?'))}'{mt}{ctx}"
            f" | {inp.get('reason', '—')}"
        ),
        "update_keyword_bid": (
            f"Lance '{inp.get('keyword_text', '?')}'{mt}{ctx}"
            f" R${inp.get('current_bid_micros', 0) / 1e6:.2f}"
            f" → R${inp.get('new_bid_micros', 0) / 1e6:.2f}"
            f" | {inp.get('reason', '—')}"
        ),
        "add_negative_keyword": (
            f"Negativa {mt} '{inp.get('keyword_text', '?')}'{ctx}"
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
