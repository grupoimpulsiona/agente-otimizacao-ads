from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Gemini AI
    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"

    # Google Ads
    google_ads_developer_token: str = ""
    google_ads_client_id: str = ""
    google_ads_client_secret: str = ""
    google_ads_refresh_token: str = ""
    google_ads_login_customer_id: str = ""
    google_ads_customer_ids: str = ""  # CSV: "123,456,789"

    # Meta Ads
    meta_access_token: str = ""
    meta_ad_account_ids: str = ""  # CSV: "act_123,act_456"

    # WhatsApp (Evolution API)
    evolution_api_url: str = ""           # ex: https://evo.seudominio.com.br
    evolution_api_key: str = ""           # apikey da instância
    evolution_instance: str = ""          # nome da instância
    evolution_group_jid: str = "120363423820098780@g.us"  # grupo de notificações

    # Guardrails
    max_bid_change_pct: float = 0.20
    min_data_impressions: int = 200
    min_data_clicks: int = 10
    max_actions_per_run: int = 15
    dry_run: bool = True

    # Metas de performance (personalize por conta)
    target_roas: float = 3.0
    target_cpa: float = 50.0
    max_cpc: float = 10.0
    min_ctr: float = 0.005  # 0.5%

    @property
    def google_customer_ids(self) -> list[str]:
        return [c.strip() for c in self.google_ads_customer_ids.split(",") if c.strip()]

    @property
    def meta_account_ids(self) -> list[str]:
        return [a.strip() for a in self.meta_ad_account_ids.split(",") if a.strip()]


settings = Settings()
