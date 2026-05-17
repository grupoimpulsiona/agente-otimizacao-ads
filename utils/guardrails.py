from utils.logger import get_logger

log = get_logger("guardrails")


class GuardrailViolation(Exception):
    pass


def clamp_bid_change(current: float, proposed: float, max_pct: float, label: str) -> float:
    """
    Limita a variação de lance ao percentual máximo configurado.
    Nunca aumenta orçamento — aumento de budget é bloqueado em nível de ação.
    """
    if current <= 0:
        raise GuardrailViolation(f"Lance atual inválido para {label}: {current}")

    change_pct = (proposed - current) / current

    if change_pct > max_pct:
        adjusted = current * (1 + max_pct)
        log.warning(
            f"[GUARDRAIL] {label}: proposta +{change_pct:.1%} → limitada a +{max_pct:.1%} "
            f"({current:.2f} → {adjusted:.2f})"
        )
        return round(adjusted, 2)

    if change_pct < -max_pct:
        adjusted = current * (1 - max_pct)
        log.warning(
            f"[GUARDRAIL] {label}: proposta {change_pct:.1%} → limitada a -{max_pct:.1%} "
            f"({current:.2f} → {adjusted:.2f})"
        )
        return round(adjusted, 2)

    return round(proposed, 2)


def block_budget_increase(action: str) -> None:
    """Bloqueia qualquer ação de aumento de orçamento. Política absoluta."""
    if "budget" in action.lower() and "increase" in action.lower():
        raise GuardrailViolation(
            "Aumento de orçamento autônomo está BLOQUEADO por política. "
            "Aprovação humana necessária."
        )


def require_min_data(impressions: int, clicks: int, min_impressions: int, min_clicks: int, label: str) -> None:
    """Exige volume mínimo de dados antes de tomar decisão."""
    if impressions < min_impressions:
        raise GuardrailViolation(
            f"[{label}] Dados insuficientes: {impressions} impressões (mínimo: {min_impressions})"
        )
    if clicks < min_clicks:
        raise GuardrailViolation(
            f"[{label}] Dados insuficientes: {clicks} cliques (mínimo: {min_clicks})"
        )


def check_action_limit(actions_taken: int, max_actions: int) -> None:
    if actions_taken >= max_actions:
        raise GuardrailViolation(
            f"Limite de {max_actions} ações por execução atingido. Abortando para segurança."
        )
