"""
Valida todas as credenciais do .env antes de ir para produção.
Execute com: python scripts/validate_credentials.py

Testa:
  ✓ Anthropic API (Claude)
  ✓ Google Ads API
  ✓ Meta Marketing API
  ✓ Evolution API (WhatsApp)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESET  = "\033[0m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BOLD   = "\033[1m"

ok    = lambda msg: print(f"  {GREEN}✓{RESET} {msg}")
fail  = lambda msg: print(f"  {RED}✗{RESET} {msg}")
warn  = lambda msg: print(f"  {YELLOW}!{RESET} {msg}")
title = lambda msg: print(f"\n{BOLD}{msg}{RESET}")

errors = []


def check_anthropic():
    title("1. Anthropic (Claude)")
    try:
        import anthropic
        from config.settings import settings

        if not settings.anthropic_api_key or settings.anthropic_api_key.startswith("sk-ant-..."):
            fail("ANTHROPIC_API_KEY não configurada")
            errors.append("ANTHROPIC_API_KEY")
            return

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=10,
            messages=[{"role": "user", "content": "ping"}],
        )
        ok(f"API funcionando | modelo={settings.claude_model}")
    except Exception as e:
        fail(f"Erro: {e}")
        errors.append("Anthropic API")


def check_google_ads():
    title("2. Google Ads API")
    try:
        from config.settings import settings

        fields = {
            "GOOGLE_ADS_DEVELOPER_TOKEN": settings.google_ads_developer_token,
            "GOOGLE_ADS_CLIENT_ID": settings.google_ads_client_id,
            "GOOGLE_ADS_CLIENT_SECRET": settings.google_ads_client_secret,
            "GOOGLE_ADS_REFRESH_TOKEN": settings.google_ads_refresh_token,
            "GOOGLE_ADS_LOGIN_CUSTOMER_ID": settings.google_ads_login_customer_id,
            "GOOGLE_ADS_CUSTOMER_IDS": settings.google_ads_customer_ids,
        }
        missing = [k for k, v in fields.items() if not v or v.startswith("seu_")]
        if missing:
            for m in missing:
                fail(f"{m} não configurada")
                errors.append(m)
            return

        from google.ads.googleads.client import GoogleAdsClient
        config = {
            "developer_token": settings.google_ads_developer_token,
            "client_id": settings.google_ads_client_id,
            "client_secret": settings.google_ads_client_secret,
            "refresh_token": settings.google_ads_refresh_token,
            "login_customer_id": settings.google_ads_login_customer_id,
            "use_proto_plus": True,
        }
        client = GoogleAdsClient.load_from_dict(config)
        customer_ids = settings.google_customer_ids

        for cid in customer_ids:
            ga_service = client.get_service("GoogleAdsService")
            query = "SELECT customer.id, customer.descriptive_name FROM customer LIMIT 1"
            response = ga_service.search(customer_id=cid, query=query)
            for row in response:
                ok(f"Conta {cid} → '{row.customer.descriptive_name}'")
    except Exception as e:
        fail(f"Erro: {e}")
        errors.append("Google Ads API")


def check_meta():
    title("3. Meta Marketing API")
    try:
        import requests
        from config.settings import settings

        if not settings.meta_access_token or settings.meta_access_token.startswith("EAA"):
            if len(settings.meta_access_token) < 20:
                fail("META_ACCESS_TOKEN parece inválido")
                errors.append("META_ACCESS_TOKEN")
                return

        r = requests.get(
            "https://graph.facebook.com/v21.0/me",
            params={"access_token": settings.meta_access_token, "fields": "id,name"},
            timeout=10,
        )
        data = r.json()
        if "error" in data:
            fail(f"Token inválido: {data['error']['message']}")
            errors.append("META_ACCESS_TOKEN")
            return
        ok(f"Token válido | usuário={data.get('name', data.get('id'))}")

        for account_id in settings.meta_account_ids:
            r2 = requests.get(
                f"https://graph.facebook.com/v21.0/{account_id}",
                params={"access_token": settings.meta_access_token, "fields": "id,name,account_status"},
                timeout=10,
            )
            data2 = r2.json()
            if "error" in data2:
                fail(f"Conta {account_id}: {data2['error']['message']}")
                errors.append(f"Meta conta {account_id}")
            else:
                status = {1: "Ativa", 2: "Desativada", 3: "Não confirmada"}.get(data2.get("account_status"), "Desconhecido")
                ok(f"Conta {account_id} → '{data2.get('name')}' | status={status}")
    except Exception as e:
        fail(f"Erro: {e}")
        errors.append("Meta API")


def check_evolution():
    title("4. Evolution API (WhatsApp)")
    try:
        import requests
        from config.settings import settings

        if not settings.evolution_api_url:
            fail("EVOLUTION_API_URL não configurada")
            errors.append("EVOLUTION_API_URL")
            return

        r = requests.get(
            f"{settings.evolution_api_url.rstrip('/')}/instance/fetchInstances",
            headers={"apikey": settings.evolution_api_key},
            timeout=10,
        )
        r.raise_for_status()
        instances = r.json()
        names = [i.get("instance", {}).get("instanceName", "") for i in (instances if isinstance(instances, list) else [])]

        if settings.evolution_instance in names:
            ok(f"Instância '{settings.evolution_instance}' encontrada e ativa")
        else:
            warn(f"Instância '{settings.evolution_instance}' não encontrada. Instâncias: {names}")
            errors.append("EVOLUTION_INSTANCE")
    except Exception as e:
        fail(f"Erro ao conectar: {e}")
        errors.append("Evolution API")


def check_env_file():
    title("0. Arquivo .env")
    if os.path.exists(".env"):
        ok(".env encontrado")
    else:
        fail(".env não encontrado — copie .env.example para .env e preencha")
        errors.append(".env")
        sys.exit(1)


if __name__ == "__main__":
    print(f"\n{BOLD}{'='*50}")
    print("  Validação de Credenciais — Agente de Ads")
    print(f"{'='*50}{RESET}")

    check_env_file()
    check_anthropic()
    check_google_ads()
    check_meta()
    check_evolution()

    print(f"\n{BOLD}{'='*50}{RESET}")
    if not errors:
        print(f"{GREEN}{BOLD}  ✓ Tudo OK! Pronto para produção.{RESET}")
        print(f"  Lembre de testar com DRY_RUN=true primeiro.\n")
        sys.exit(0)
    else:
        print(f"{RED}{BOLD}  ✗ {len(errors)} problema(s) encontrado(s):{RESET}")
        for e in errors:
            print(f"    - {e}")
        print()
        sys.exit(1)
