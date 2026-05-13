#!/usr/bin/env bash
set -euo pipefail

# ── Pré-requisito ────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && { echo "Execute como root." >&2; exit 1; }

INSTALL_DIR="/opt/litellm"
CONFIG_DIR="/etc/litellm"
PORT=4000

# ── API key ──────────────────────────────────────────────────────────────────
read -rsp "Anthropic API key: " ANTHROPIC_KEY; echo
[[ -z "$ANTHROPIC_KEY" ]] && { echo "API key não pode ser vazia." >&2; exit 1; }

# ── Dependências do sistema ──────────────────────────────────────────────────
echo "→ Atualizando pacotes..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv curl

# ── Instalar LiteLLM num venv isolado ────────────────────────────────────────
echo "→ Instalando LiteLLM em $INSTALL_DIR (pode demorar alguns minutos)..."
python3 -m venv "$INSTALL_DIR"
"$INSTALL_DIR/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/bin/pip" install --quiet 'litellm[proxy]'

# ── Configuração ─────────────────────────────────────────────────────────────
mkdir -p "$CONFIG_DIR"

# Chave separada do config (só root lê)
cat > "$CONFIG_DIR/env" <<EOF
ANTHROPIC_API_KEY=$ANTHROPIC_KEY
EOF
chmod 600 "$CONFIG_DIR/env"

# Modelos expostos
cat > "$CONFIG_DIR/config.yaml" <<'EOF'
model_list:
  - model_name: claude-sonnet-4-6
    litellm_params:
      model: anthropic/claude-sonnet-4-6
      api_key: os.environ/ANTHROPIC_API_KEY

  - model_name: claude-haiku-4-5
    litellm_params:
      model: anthropic/claude-haiku-4-5-20251001
      api_key: os.environ/ANTHROPIC_API_KEY

  - model_name: claude-opus-4-6
    litellm_params:
      model: anthropic/claude-opus-4-6
      api_key: os.environ/ANTHROPIC_API_KEY

general_settings:
  drop_params: true   # ignora parâmetros não suportados pela Anthropic
EOF

# ── Serviço systemd ──────────────────────────────────────────────────────────
cat > /etc/systemd/system/litellm.service <<EOF
[Unit]
Description=LiteLLM Proxy
After=network.target

[Service]
Type=simple
EnvironmentFile=$CONFIG_DIR/env
ExecStart=$INSTALL_DIR/bin/litellm --config $CONFIG_DIR/config.yaml --port $PORT --host 0.0.0.0
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now litellm

# ── Verificação ──────────────────────────────────────────────────────────────
echo "→ Aguardando o serviço iniciar..."
for i in $(seq 1 12); do
    if curl -sf "http://127.0.0.1:$PORT/models" > /dev/null 2>&1; then
        echo "✓ LiteLLM respondendo na porta $PORT"
        break
    fi
    sleep 3
    [[ $i -eq 12 ]] && {
        echo "⚠ Serviço não respondeu em 36s. Verifique:"
        echo "   journalctl -u litellm -n 50"
        exit 1
    }
done

# ── Instruções ───────────────────────────────────────────────────────────────
IP=$(hostname -I | awk '{print $1}')
echo ""
echo "══════════════════════════════════════════════"
echo " Configure o Risos em Configurações → IA:"
echo "   API Base URL : http://${IP}:${PORT}"
echo "   API Key      : qualquer string não-vazia"
echo ""
echo " Modelos disponíveis:"
echo "   claude-sonnet-4-6   (recomendado)"
echo "   claude-haiku-4-5    (mais rápido e barato)"
echo "   claude-opus-4-6     (mais capaz)"
echo "══════════════════════════════════════════════"
echo ""
echo " Para adicionar provedores: edite $CONFIG_DIR/config.yaml"
echo " Para reiniciar:            systemctl restart litellm"
echo " Para ver logs:             journalctl -u litellm -f"
