import json
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Gemini AI ───────────────────────────────────────────────────────────────
    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"

    # ── Google Ads ──────────────────────────────────────────────────────────────
    google_ads_developer_token: str = ""
    google_ads_client_id: str = ""
    google_ads_client_secret: str = ""
    google_ads_refresh_token: str = ""
    google_ads_login_customer_id: str = ""
    google_ads_customer_ids: str = ""  # CSV: "123,456"

    # Configurações por conta — JSON string
    # Exemplo:
    # {"9659371450": {"name": "LP Impulsiona Eventos", "segment": "eventos",
    #                 "target_cpa": 80.0, "target_roas": 0.0, "monthly_budget": 5000}}
    google_ads_account_configs: str = "{}"

    # ── Meta Ads ────────────────────────────────────────────────────────────────
    meta_access_token: str = ""
    meta_ad_account_ids: str = ""  # CSV: "act_123,act_456"

    # Configurações por conta — JSON string
    # Exemplo:
    # {"act_123456": {"name": "LP Impulsiona Eventos", "segment": "eventos",
    #                 "target_cpa": 60.0, "target_roas": 0.0, "monthly_budget": 3000}}
    meta_account_configs: str = "{}"

    # ── WhatsApp (Evolution API) ────────────────────────────────────────────────
    evolution_api_url: str = ""
    evolution_api_key: str = ""
    evolution_instance: str = ""
    evolution_group_jid: str = "120363423820098780@g.us"

    # ── Segurança da API ────────────────────────────────────────────────────────
    api_secret: str = "trocar-em-producao"

    # ── Guardrails ──────────────────────────────────────────────────────────────
    max_bid_change_pct: float = 0.20
    min_data_impressions: int = 100
    min_data_clicks: int = 5
    max_actions_per_run: int = 20
    dry_run: bool = True

    # ── Metas globais (fallback quando não há config por conta) ─────────────────
    target_roas: float = 3.0
    target_cpa: float = 50.0
    max_cpc: float = 10.0
    min_ctr: float = 0.005

    # ── Propriedades ────────────────────────────────────────────────────────────

    @property
    def google_customer_ids(self) -> list[str]:
        return [c.strip() for c in self.google_ads_customer_ids.split(",") if c.strip()]

    @property
    def meta_account_ids(self) -> list[str]:
        return [a.strip() for a in self.meta_ad_account_ids.split(",") if a.strip()]

    @property
    def google_account_config_map(self) -> dict:
        try:
            return json.loads(self.google_ads_account_configs)
        except Exception:
            return {}

    @property
    def meta_account_config_map(self) -> dict:
        try:
            return json.loads(self.meta_account_configs)
        except Exception:
            return {}

    def get_google_account_config(self, customer_id: str) -> dict:
        """Retorna config específica da conta, com fallback para valores globais."""
        cfg = self.google_account_config_map.get(str(customer_id), {})
        return {
            "name": cfg.get("name", f"Conta {customer_id}"),
            "segment": cfg.get("segment", "não informado"),
            "target_cpa": float(cfg.get("target_cpa", self.target_cpa)),
            "target_roas": float(cfg.get("target_roas", self.target_roas)),
            "monthly_budget": float(cfg.get("monthly_budget", 0)),
        }

    def get_meta_account_config(self, ad_account_id: str) -> dict:
        """Retorna config específica da conta Meta, com fallback para valores globais."""
        cfg = self.meta_account_config_map.get(str(ad_account_id), {})
        return {
            "name": cfg.get("name", f"Conta {ad_account_id}"),
            "segment": cfg.get("segment", "não informado"),
            "target_cpa": float(cfg.get("target_cpa", self.target_cpa)),
            "target_roas": float(cfg.get("target_roas", self.target_roas)),
            "monthly_budget": float(cfg.get("monthly_budget", 0)),
        }


settings = Settings()
