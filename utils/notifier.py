import time
import requests
from utils.logger import get_logger

log = get_logger("notifier")


def _zapi_send(instance_id: str, token: str, client_token: str, phone: str, message: str) -> bool:
    url = f"https://api.z-api.io/instances/{instance_id}/token/{token}/send-text"
    headers = {"Client-Token": client_token, "Content-Type": "application/json"}
    payload = {"phone": phone, "message": message}

    for attempt in range(1, 4):
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=15)
            r.raise_for_status()
            return True
        except Exception as e:
            wait = 2 ** attempt
            log.warning(f"Z-API tentativa {attempt} falhou: {e}. Aguardando {wait}s...")
            time.sleep(wait)

    log.error("Z-API: todas as tentativas falharam.")
    return False


def send_whatsapp(message: str) -> bool:
    from config.settings import settings

    if not all([settings.zapi_instance_id, settings.zapi_token, settings.zapi_phone_number]):
        log.warning("WhatsApp não configurado. Pulando notificação.")
        return False

    return _zapi_send(
        settings.zapi_instance_id,
        settings.zapi_token,
        settings.zapi_client_token,
        settings.zapi_phone_number,
        message,
    )


def notify_run_result(platform: str, summary: str, actions: list[dict], dry_run: bool) -> None:
    flag = "🧪 *DRY-RUN*" if dry_run else "✅ *EXECUTADO*"
    lines = [
        f"🤖 *Agente {platform}* — {flag}",
        "",
        summary,
        "",
    ]

    if actions:
        lines.append(f"*Ações realizadas ({len(actions)}):*")
        for a in actions[:10]:  # limita preview a 10
            lines.append(f"  • {a.get('description', str(a))}")
        if len(actions) > 10:
            lines.append(f"  ... e mais {len(actions) - 10} ações no log.")
    else:
        lines.append("_Nenhuma ação necessária nesta execução._")

    send_whatsapp("\n".join(lines))


def notify_error(platform: str, error: str) -> None:
    message = (
        f"🚨 *ERRO — Agente {platform}*\n\n"
        f"{error}\n\n"
        f"_Verifique os logs em /logs/agent.log_"
    )
    send_whatsapp(message)


def notify_anomaly(platform: str, anomalies: list[str]) -> None:
    if not anomalies:
        return
    lines = [f"⚠️ *Anomalia detectada — {platform}*", ""]
    lines.extend(f"  • {a}" for a in anomalies)
    send_whatsapp("\n".join(lines))
