#!/bin/bash
# Setup inicial em servidor Ubuntu 22.04 limpo
# Execute como root: bash server_setup.sh

set -e

REPO="https://github.com/grupoimpulsiona/agente-otimizacao-ads.git"
APP_DIR="/opt/agente-otimizacao-ads"

echo ""
echo "================================================"
echo "  Setup — Agente de Otimização de Ads"
echo "================================================"
echo ""

# ── 1. Atualizar sistema ────────────────────────────
echo "▶ Atualizando sistema..."
apt-get update -q && apt-get upgrade -y -q

# ── 2. Instalar Docker ──────────────────────────────
echo "▶ Instalando Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo "✓ Docker instalado"
else
    echo "✓ Docker já instalado"
fi

# ── 3. Instalar Docker Compose ──────────────────────
echo "▶ Instalando Docker Compose..."
if ! command -v docker compose &> /dev/null; then
    apt-get install -y docker-compose-plugin
    echo "✓ Docker Compose instalado"
else
    echo "✓ Docker Compose já instalado"
fi

# ── 4. Clonar repositório ───────────────────────────
echo "▶ Clonando repositório..."
if [ -d "$APP_DIR" ]; then
    echo "  Diretório já existe, fazendo pull..."
    cd "$APP_DIR" && git pull
else
    git clone "$REPO" "$APP_DIR"
fi
echo "✓ Repositório em $APP_DIR"

# ── 5. Configurar .env ──────────────────────────────
cd "$APP_DIR"
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "⚠  PRÓXIMO PASSO OBRIGATÓRIO:"
    echo "   Edite o arquivo .env com suas credenciais:"
    echo "   nano $APP_DIR/.env"
    echo ""
else
    echo "✓ .env já existe"
fi

# ── 6. Criar pasta de logs ──────────────────────────
mkdir -p logs
echo "✓ Pasta de logs criada"

# ── 7. Configurar firewall ──────────────────────────
echo "▶ Configurando firewall..."
if command -v ufw &> /dev/null; then
    ufw allow 22/tcp    # SSH
    ufw allow 8000/tcp  # API
    ufw allow 5678/tcp  # N8N
    ufw --force enable
    echo "✓ Firewall configurado (22, 8000, 5678)"
fi

echo ""
echo "================================================"
echo "  ✓ Setup concluído!"
echo ""
echo "  Próximos passos:"
echo "  1. Edite o .env:   nano $APP_DIR/.env"
echo "  2. Valide:         cd $APP_DIR && python scripts/validate_credentials.py"
echo "  3. Suba:           cd $APP_DIR && docker compose up -d"
echo "  4. Acesse o N8N:   http://$(curl -s ifconfig.me):5678"
echo "================================================"
echo ""
