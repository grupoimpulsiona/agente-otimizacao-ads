.PHONY: help start stop restart logs validate test-dry build

help:
	@echo ""
	@echo "  Agente de Otimização de Ads"
	@echo ""
	@echo "  Comandos disponíveis:"
	@echo "    make start        Sobe a API e o N8N"
	@echo "    make stop         Para todos os serviços"
	@echo "    make restart      Reinicia todos os serviços"
	@echo "    make logs         Exibe logs em tempo real"
	@echo "    make validate     Valida todas as credenciais do .env"
	@echo "    make test-dry     Dispara o agente Google Ads em modo simulação"
	@echo "    make build        Reconstrói a imagem Docker da API"
	@echo ""

start:
	@echo "▶ Subindo serviços..."
	docker compose up -d
	@echo "✓ API: http://localhost:8000"
	@echo "✓ N8N: http://localhost:5678"

stop:
	@echo "■ Parando serviços..."
	docker compose down

restart:
	docker compose down && docker compose up -d

logs:
	docker compose logs -f

build:
	docker compose build --no-cache python-api

validate:
	@echo "Validando credenciais..."
	python scripts/validate_credentials.py

test-dry:
	@echo "Disparando agente Google Ads em DRY_RUN..."
	curl -s -X POST http://localhost:8000/optimize/google-ads \
		-H "Content-Type: application/json" \
		-H "X-API-Key: $$(grep API_SECRET .env | cut -d= -f2)" \
		-d '{"customer_id": "'$$(grep GOOGLE_ADS_CUSTOMER_IDS .env | cut -d= -f2 | cut -d, -f1)'", "dry_run": true}' \
		| python -m json.tool
