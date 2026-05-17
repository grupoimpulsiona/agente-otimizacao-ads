"""
Motor de decisão baseado em Claude com tool use.
Recebe dados de performance e decide quais ações executar.
"""

import json
from typing import Any, Callable
import anthropic
from config.settings import settings
from utils.logger import get_logger

log = get_logger("decision_engine")

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

SYSTEM_GOOGLE_ADS = """Você é um especialista sênior em Google Ads com 10+ anos de experiência.
Analise os dados de performance fornecidos e tome decisões de otimização cirúrgicas.

REGRAS ABSOLUTAS:
- NUNCA aumente orçamento de campanhas (bloqueado por política)
- Só tome decisão sobre entidades com dados suficientes (mínimo fornecido nos dados)
- Priorize: reduzir desperdício > melhorar ROAS > escalar o que funciona
- Explique cada decisão em português, de forma que um gestor de marketing entenda

CRITÉRIOS DE AÇÃO:
- Keyword com CTR < 0.5% e sem conversão nos últimos 7 dias → pausar
- Keyword com CPA > 2x meta e volume alto → reduzir lance em 10-15%
- Keyword com ROAS > 4x e impressão share < 50% → aumentar lance (respeitando limite)
- Termo de busca irrelevante → adicionar como negativa
- Ad group com frequência de anomalia → escalar alerta

Ao final, forneça um resumo executivo das ações tomadas."""

SYSTEM_META_ADS = """Você é um especialista sênior em Meta Ads (Facebook e Instagram) com 10+ anos de experiência.
Analise os dados de performance e tome decisões de otimização precisas.

REGRAS ABSOLUTAS:
- NUNCA aumente orçamento de campanhas ou ad sets (bloqueado por política)
- Só atue em entidades com dados estatisticamente relevantes
- Frequência > 3.5 = audiência fatigada → pausar ad set ou rodar criativo novo
- Priorize: cortar gastos ruins > otimizar criativos > escalar ganhadores

CRITÉRIOS DE AÇÃO:
- Ad set com CPM > 2x média da conta → investigar audiência e pausar se necessário
- Ad com CTR < 0.8% e gasto > R$50 sem conversão → pausar ad
- Ad set com ROAS < 1.5 por 3+ dias consecutivos → pausar
- Ad set com ROAS > 4x → aumentar lance CBO (respeitando limite de guardrail)
- Criativo com frequência alta + CTR caindo → sinalizar para troca de criativo

Ao final, forneça um resumo executivo das ações tomadas."""


def run_decision_loop(
    platform: str,
    performance_data: dict,
    tools_schema: list[dict],
    tool_executor: Callable[[str, dict], Any],
) -> tuple[list[dict], str]:
    """
    Loop agêntico principal.
    Retorna (lista_de_acoes_executadas, resumo_texto).
    """
    system = SYSTEM_GOOGLE_ADS if platform == "google_ads" else SYSTEM_META_ADS

    user_message = (
        f"Analise os dados de performance a seguir e execute as otimizações necessárias.\n\n"
        f"Configurações de guardrail:\n"
        f"- Limite de variação de lance: ±{settings.max_bid_change_pct*100:.0f}%\n"
        f"- Mínimo de impressões para decisão: {settings.min_data_impressions}\n"
        f"- Aumento de orçamento: BLOQUEADO\n"
        f"- Modo: {'DRY-RUN (nenhuma ação real)' if settings.dry_run else 'PRODUÇÃO (ações reais)'}\n\n"
        f"Dados de performance:\n{json.dumps(performance_data, ensure_ascii=False, indent=2)}"
    )

    messages = [{"role": "user", "content": user_message}]
    actions_taken: list[dict] = []
    max_iterations = 20

    for iteration in range(max_iterations):
        log.info(f"[{platform}] Iteração {iteration + 1}/{max_iterations}")

        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=4096,
            system=system,
            tools=tools_schema,
            messages=messages,
        )

        log.info(f"[{platform}] stop_reason={response.stop_reason}")

        if response.stop_reason == "end_turn":
            summary = _extract_text(response.content)
            log.info(f"[{platform}] Agente finalizou. Ações: {len(actions_taken)}")
            return actions_taken, summary

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            log.info(f"[{platform}] Tool call: {block.name} | input={block.input}")

            try:
                result = tool_executor(block.name, block.input)
                actions_taken.append({
                    "tool": block.name,
                    "input": block.input,
                    "result": result,
                    "description": _describe_action(block.name, block.input, result),
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
            except Exception as e:
                log.error(f"[{platform}] Erro na tool {block.name}: {e}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"ERRO: {e}",
                    "is_error": True,
                })

        clean_content = [
            block for block in response.content
            if not (hasattr(block, "text") and not block.text)
        ]
        if clean_content:
            messages.append({"role": "assistant", "content": clean_content})

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    log.warning(f"[{platform}] Limite de iterações atingido.")
    return actions_taken, "Limite de iterações atingido. Verifique os logs."


def _extract_text(content: list) -> str:
    return " ".join(b.text for b in content if hasattr(b, "text") and b.text)


def _describe_action(tool_name: str, inp: dict, result: Any) -> str:
    descriptions = {
        "pause_keyword": f"Pausou keyword '{inp.get('keyword_text', inp.get('keyword_id', ''))}'",
        "update_keyword_bid": f"Ajustou lance de '{inp.get('keyword_text', '')}' para R${inp.get('new_bid_micros', 0)/1e6:.2f}",
        "add_negative_keyword": f"Adicionou negativa '{inp.get('keyword_text', '')}'",
        "pause_ad": f"Pausou anúncio ID {inp.get('ad_id', '')}",
        "pause_ad_set": f"Pausou ad set '{inp.get('ad_set_name', inp.get('ad_set_id', ''))}'",
        "update_ad_set_bid": f"Ajustou lance do ad set '{inp.get('ad_set_name', '')}'",
        "get_performance_data": "Consultou dados de performance",
        "get_search_terms": "Consultou termos de busca",
        "get_anomalies": "Verificou anomalias",
    }
    return descriptions.get(tool_name, f"{tool_name}: {inp}")
