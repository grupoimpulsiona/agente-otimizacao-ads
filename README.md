# Agente de Otimização de Ads — Impulsiona

Agente de IA que otimiza campanhas do **Google Ads** e **Meta Ads** automaticamente, usando Claude com tool use para analisar dados de performance e executar ações reais (pausar keywords, ajustar lances, adicionar negativos) com guardrails de segurança.

O N8N dispara o agente diariamente e as notificações de resultado chegam via WhatsApp (Evolution API).

---

## Arquitetura

```
N8N (Schedule Trigger)
   ↓ HTTP Request
FastAPI (api/main.py)
   ↓
Decision Engine (Claude + tool use)
   ↓
Google Ads API / Meta Marketing API
   ↓
Evolution API (notificação WhatsApp)
```

---

## Pré-requisitos

- Docker e Docker Compose
- Conta Google Ads com acesso de desenvolvedor
- Conta Meta Business com token de acesso à Marketing API
- Instância Evolution API ativa
- Chave de API da Anthropic (Claude)

---

## Setup

### 1. Clone e configure as variáveis

```bash
git clone https://github.com/grupoimpulsiona/lp-impulsiona-eventos.git
cd lp-impulsiona-eventos
cp .env.example .env
```

Edite o `.env` com suas credenciais reais. **Nunca commite o `.env`.**

### 2. Suba os serviços

```bash
docker compose up -d
```

Isso sobe:
- `ads-agent-api` — FastAPI na porta `8000`
- `n8n` — interface N8N na porta `5678`

### 3. Verifique a saúde da API

```bash
curl http://localhost:8000/health
# {"status":"ok","dry_run":true}
```

### 4. Importe os workflows no N8N

1. Acesse `http://localhost:5678`
2. Menu → **Workflows** → **Import from file**
3. Importe `n8n/google_ads_workflow.json` e `n8n/meta_ads_workflow.json`
4. Configure a credential **HTTP Header Auth** com o valor de `API_SECRET` do seu `.env`

---

## Modo de Operação

O agente opera em dois modos, controlados pela variável `DRY_RUN` no `.env`:

| Modo | DRY_RUN | Comportamento |
|------|---------|---------------|
| Simulação | `true` | Analisa e decide, mas **não executa** nenhuma ação real |
| Produção | `false` | Executa as ações via API |

**Comece sempre em `DRY_RUN=true`** para validar o comportamento antes de ir para produção.

---

## Guardrails de Segurança

Todas as ações passam por validação antes de serem executadas:

| Guardrail | Padrão | Variável |
|-----------|--------|----------|
| Variação máxima de lance | ±20% | `MAX_BID_CHANGE_PCT` |
| Mínimo de impressões para decidir | 200 | `MIN_DATA_IMPRESSIONS` |
| Mínimo de cliques para decidir | 10 | `MIN_DATA_CLICKS` |
| Máximo de ações por execução | 15 | `MAX_ACTIONS_PER_RUN` |
| Aumento de orçamento | **Bloqueado** | — |

---

## Endpoints da API

### `GET /health`
Verifica se a API está rodando.

### `POST /optimize/google-ads`
Roda o agente para uma conta Google Ads.

```json
{
  "customer_id": "1234567890",
  "date_range": "LAST_7_DAYS",
  "dry_run": true
}
```

### `POST /optimize/meta-ads`
Roda o agente para uma conta Meta Ads.

```json
{
  "ad_account_id": "act_123456789",
  "date_preset": "last_7d",
  "dry_run": true
}
```

### `POST /optimize/all`
Roda todos os agentes em sequência (usado pelo N8N no trigger diário).

Todos os endpoints exigem o header `X-API-Key: <API_SECRET>`.

---

## Logs

Todas as ações executadas são registradas em `logs/actions_YYYY-MM-DD.jsonl`:

```json
{"timestamp":"2026-05-17T07:00:12Z","platform":"Google Ads","action":"pause_keyword","entity_id":"123456","input":{...},"result":"...","dry_run":false}
```

---

## Ações disponíveis

### Google Ads
| Ação | Condição |
|------|----------|
| Pausar keyword | CTR < 0.5% e sem conversão em 7 dias |
| Reduzir lance | CPA > 2x meta com volume alto |
| Aumentar lance | ROAS > 4x e impression share < 50% |
| Adicionar negativa | Termo de busca irrelevante detectado |

### Meta Ads
| Ação | Condição |
|------|----------|
| Pausar ad set | ROAS < 1.5 por 3+ dias ou frequência > 3.5 |
| Pausar ad | CTR < 0.8% com gasto > R$50 sem conversão |
| Ajustar lance | CPM > 2x média ou ROAS > 4x |

---

## Credenciais necessárias

### Google Ads API
1. Acesse [Google Ads API Center](https://developers.google.com/google-ads/api/docs/get-started/introduction)
2. Crie um projeto no Google Cloud e ative a Google Ads API
3. Gere OAuth2 credentials e um refresh token
4. Solicite o Developer Token na conta MCC

### Meta Marketing API
1. Acesse [Meta for Developers](https://developers.facebook.com/docs/marketing-apis/get-started)
2. Crie um app com permissão `ads_management`
3. Gere um token de acesso de longa duração

### Evolution API
Configure a URL, API key e nome da instância no `.env`. O `EVOLUTION_GROUP_JID` é o ID do grupo WhatsApp que receberá as notificações.
