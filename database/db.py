"""
SQLite — persistência de sessões e ações de otimização.

O arquivo do banco fica em /app/data/ads_agent.db (volume Docker).
Substitui o dict em memória que era perdido a cada restart.
"""

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "/app/data/ads_agent.db")


def _conn() -> sqlite3.Connection:
    """Abre conexão com WAL mode (leituras concorrentes sem travar escritas)."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Cria as tabelas e índices na primeira execução."""
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id   TEXT PRIMARY KEY,
                platform     TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                executed     INTEGER NOT NULL DEFAULT 0,
                executed_at  TEXT,
                rejected     INTEGER NOT NULL DEFAULT 0,
                rejected_at  TEXT,
                customer_ids TEXT,
                account_ids  TEXT,
                date_range   TEXT,
                date_preset  TEXT
            );

            CREATE TABLE IF NOT EXISTS session_accounts (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id     TEXT NOT NULL REFERENCES sessions(session_id),
                account_id     TEXT,
                account_name   TEXT,
                status         TEXT NOT NULL DEFAULT 'ok',
                actions_count  INTEGER NOT NULL DEFAULT 0,
                actions_detail TEXT NOT NULL DEFAULT '[]',
                summary        TEXT NOT NULL DEFAULT '',
                dry_run        INTEGER NOT NULL DEFAULT 1,
                error          TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_platform
                ON sessions(platform, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_accounts_session
                ON session_accounts(session_id);
        """)


# ─── Escrita ──────────────────────────────────────────────────────────────────

def create_session(
    session_id: str,
    platform: str,
    accounts: list[dict],
    customer_ids: list = None,
    account_ids: list = None,
    date_range: str = None,
    date_preset: str = None,
) -> str:
    """Persiste nova sessão + contas analisadas. Retorna created_at."""
    created_at = datetime.now().isoformat()
    with _conn() as conn:
        conn.execute(
            """INSERT INTO sessions
               (session_id, platform, created_at, customer_ids, account_ids, date_range, date_preset)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, platform, created_at,
             json.dumps(customer_ids or []),
             json.dumps(account_ids or []),
             date_range, date_preset),
        )
        for acc in accounts:
            _insert_account(conn, session_id, acc, dry_run=True)
    return created_at


def _insert_account(conn, session_id: str, acc: dict, dry_run: bool):
    account_id = acc.get("customer_id") or acc.get("ad_account_id", "")
    actions    = acc.get("actions_detail", [])
    conn.execute(
        """INSERT INTO session_accounts
           (session_id, account_id, account_name, status,
            actions_count, actions_detail, summary, dry_run, error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id,
         account_id,
         acc.get("account_name", ""),
         acc.get("status", "ok"),
         len(actions),
         json.dumps(actions),
         acc.get("summary", ""),
         1 if dry_run else 0,
         acc.get("error")),
    )


def mark_executed(session_id: str, results: list[dict]) -> str:
    """Marca sessão como executada e atualiza contas com resultados reais."""
    executed_at = datetime.now().isoformat()
    with _conn() as conn:
        conn.execute(
            "UPDATE sessions SET executed=1, executed_at=? WHERE session_id=?",
            (executed_at, session_id),
        )
        for acc in results:
            account_id = acc.get("customer_id") or acc.get("ad_account_id", "")
            actions    = acc.get("actions_detail", [])
            conn.execute(
                """UPDATE session_accounts
                   SET actions_count=?, actions_detail=?, summary=?, dry_run=0, error=?
                   WHERE session_id=? AND account_id=?""",
                (len(actions), json.dumps(actions),
                 acc.get("summary", ""),
                 acc.get("error"),
                 session_id, account_id),
            )
    return executed_at


def mark_rejected(session_id: str) -> str:
    """Marca sessão como rejeitada."""
    rejected_at = datetime.now().isoformat()
    with _conn() as conn:
        conn.execute(
            "UPDATE sessions SET rejected=1, rejected_at=? WHERE session_id=?",
            (rejected_at, session_id),
        )
    return rejected_at


# ─── Leitura ──────────────────────────────────────────────────────────────────

def get_session(session_id: str) -> Optional[dict]:
    """Retorna sessão completa com contas (para o detalhe no dashboard)."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if not row:
            return None

        account_rows = conn.execute(
            "SELECT * FROM session_accounts WHERE session_id=? ORDER BY id",
            (session_id,),
        ).fetchall()

        s = dict(row)
        s["customer_ids"] = json.loads(s.get("customer_ids") or "[]")
        s["account_ids"]  = json.loads(s.get("account_ids") or "[]")
        s["accounts"]     = [_account_to_api_dict(a) for a in account_rows]
        s["executed"]     = bool(s["executed"])
        s["rejected"]     = bool(s["rejected"])
        return s


def list_sessions(limit: int = 500) -> list[dict]:
    """Lista todas as sessões com resumo (para o dashboard e history)."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT session_id, platform, created_at,
                      executed, executed_at, rejected, rejected_at
               FROM sessions
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

        result = []
        for row in rows:
            d = dict(row)
            d["executed"] = bool(d["executed"])
            d["rejected"] = bool(d["rejected"])

            accs = conn.execute(
                """SELECT account_id, account_name, status, actions_count
                   FROM session_accounts WHERE session_id=?""",
                (d["session_id"],),
            ).fetchall()

            d["accounts"] = [
                {
                    "id": a["account_id"],
                    "name": a["account_name"],
                    "status": a["status"],
                    "actions_count": a["actions_count"],
                }
                for a in accs
            ]
            d["accounts_count"] = len(accs)
            d["total_actions"]  = sum(a["actions_count"] for a in accs)
            result.append(d)
        return result


def list_executed_with_details(limit: int = 500) -> list[dict]:
    """Retorna todas as sessões executadas com actions_detail completo (para a página de relatórios)."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT session_id, platform, created_at, executed_at
               FROM sessions
               WHERE executed=1
               ORDER BY executed_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

        result = []
        for row in rows:
            d = dict(row)
            accs = conn.execute(
                """SELECT account_id, account_name, status,
                          actions_count, actions_detail, summary
                   FROM session_accounts WHERE session_id=?""",
                (d["session_id"],),
            ).fetchall()

            d["accounts"] = []
            for a in accs:
                acc = dict(a)
                try:
                    acc["actions_detail"] = json.loads(acc.get("actions_detail") or "[]")
                except Exception:
                    acc["actions_detail"] = []
                d["accounts"].append(acc)

            d["total_actions"] = sum(a["actions_count"] for a in accs)
            result.append(d)
        return result


def _account_to_api_dict(row) -> dict:
    """Converte linha do SQLite para o formato AccountResult da API."""
    d = dict(row)
    try:
        d["actions_detail"] = json.loads(d.get("actions_detail") or "[]")
    except Exception:
        d["actions_detail"] = []

    account_id = d.pop("account_id", "") or ""
    if account_id.startswith("act_"):
        d["ad_account_id"] = account_id
    else:
        d["customer_id"] = account_id

    d.pop("id", None)
    d.pop("session_id", None)
    d["dry_run"] = bool(d.get("dry_run", 1))
    return d
