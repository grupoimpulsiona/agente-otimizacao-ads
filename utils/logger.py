import json
import logging
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

_fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=_fmt,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "agent.log", encoding="utf-8"),
    ],
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


_action_log_path = LOG_DIR / "actions.jsonl"


def log_action(
    platform: str,
    action: str,
    entity_id: str,
    payload: dict,
    result: str,
    dry_run: bool,
) -> None:
    """Registro imutável (append-only) de toda ação executada pelo agente."""
    entry = {
        "ts": datetime.utcnow().isoformat(),
        "platform": platform,
        "action": action,
        "entity_id": entity_id,
        "dry_run": dry_run,
        "payload": payload,
        "result": result,
    }
    with _action_log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    logger = get_logger("action_log")
    flag = "[DRY-RUN]" if dry_run else "[EXECUTED]"
    logger.info(f"{flag} {platform}/{action} entity={entity_id} → {result}")
