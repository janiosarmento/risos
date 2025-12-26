#!/bin/bash
set -e

# =============================================================================
# Risos - Installation Script
# =============================================================================
# This script installs the Risos backend as a systemd service.
# Run as root or with sudo.
# =============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo_info() { echo -e "${GREEN}[INFO]${NC} $1" >&2; }
echo_warn() { echo -e "${YELLOW}[WARN]${NC} $1" >&2; }
echo_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo_error "Please run as root or with sudo"
    exit 1
fi

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
HTDOCS_DIR="$SCRIPT_DIR/htdocs"

echo_info "Installing Risos from: $SCRIPT_DIR"

# =============================================================================
# Configuration
# =============================================================================

# Function to find next available port starting from a base port
find_available_port() {
    local port=$1
    while ss -tlnH "sport = :$port" 2>/dev/null | grep -q ":$port" || \
          grep -q "127.0.0.1:$port" /etc/systemd/system/*.service 2>/dev/null; do
        echo_warn "Port $port is in use, trying next..."
        ((port++))
    done
    echo $port
}

# Find suggested port
SUGGESTED_PORT=$(find_available_port 8100)

# Prompt for configuration
read -p "Service name [risos]: " SERVICE_NAME
SERVICE_NAME=${SERVICE_NAME:-risos}

read -p "Port to run on [$SUGGESTED_PORT]: " PORT
PORT=${PORT:-$SUGGESTED_PORT}

# Validate chosen port is available
if ss -tlnH "sport = :$PORT" 2>/dev/null | grep -q ":$PORT"; then
    echo_error "Port $PORT is already in use!"
    exit 1
fi

read -p "User to run as [www-data]: " RUN_USER
RUN_USER=${RUN_USER:-www-data}

read -p "Group to run as [www-data]: " RUN_GROUP
RUN_GROUP=${RUN_GROUP:-www-data}

# =============================================================================
# Python Virtual Environment
# =============================================================================

echo_info "Setting up Python virtual environment..."

cd "$BACKEND_DIR"

# Check Python3 is available
if ! command -v python3 &> /dev/null; then
    echo_error "python3 not found. Please install Python 3.8+ first."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo_info "Found Python $PYTHON_VERSION"

# Create venv if it doesn't exist
if [ ! -d "venv" ]; then
    echo_info "Creating virtual environment..."
    if ! python3 -m venv venv; then
        echo_error "Failed to create virtual environment"
        echo_error "Try: apt install python3-venv"
        exit 1
    fi
    echo_info "Virtual environment created"
else
    echo_info "Virtual environment already exists"
fi

# Verify venv was created properly
if [ ! -f "venv/bin/activate" ]; then
    echo_error "Virtual environment is broken (no activate script)"
    echo_error "Try: rm -rf venv && re-run this script"
    exit 1
fi

# Activate and install dependencies
echo_info "Installing Python dependencies..."
source venv/bin/activate

if ! pip install --upgrade pip 2>&1 | tee /tmp/pip_upgrade.log; then
    echo_error "Failed to upgrade pip. Check /tmp/pip_upgrade.log"
    deactivate
    exit 1
fi

if ! pip install -r requirements.txt 2>&1 | tee /tmp/pip_install.log; then
    echo_error "Failed to install dependencies. Check /tmp/pip_install.log"
    deactivate
    exit 1
fi

deactivate

# Verify gunicorn was installed
if [ ! -f "venv/bin/gunicorn" ]; then
    echo_error "gunicorn not found after installation!"
    echo_error "Check /tmp/pip_install.log for errors"
    exit 1
fi

echo_info "Dependencies installed successfully"

# =============================================================================
# Configuration Files
# =============================================================================

# Create .env if it doesn't exist
if [ ! -f "$BACKEND_DIR/.env" ]; then
    if [ -f "$BACKEND_DIR/.env.example" ]; then
        cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
        echo_warn ".env created from .env.example - please edit it with your settings!"
        echo_warn "At minimum, set APP_PASSWORD, JWT_SECRET, and CEREBRAS_API_KEY"
    else
        echo_error ".env.example not found!"
        exit 1
    fi
else
    echo_info ".env already exists"
fi

# Create prompts.yaml if it doesn't exist
if [ ! -f "$BACKEND_DIR/prompts.yaml" ]; then
    if [ -f "$BACKEND_DIR/prompts.yaml.example" ]; then
        cp "$BACKEND_DIR/prompts.yaml.example" "$BACKEND_DIR/prompts.yaml"
        echo_info "prompts.yaml created from prompts.yaml.example"
    else
        echo_error "prompts.yaml.example not found!"
        exit 1
    fi
else
    echo_info "prompts.yaml already exists (preserving customizations)"
fi

# Create data directory
mkdir -p "$BACKEND_DIR/data"
chown -R "$RUN_USER:$RUN_GROUP" "$BACKEND_DIR/data"

echo_info "Data directory ready"

# =============================================================================
# Database Migrations
# =============================================================================

echo_info "Running database migrations..."

source venv/bin/activate

if ! alembic upgrade head 2>&1 | tee /tmp/alembic_migrate.log; then
    echo_error "Failed to run migrations. Check /tmp/alembic_migrate.log"
    deactivate
    exit 1
fi

deactivate

echo_info "Database migrations complete"

# =============================================================================
# Systemd Service
# =============================================================================

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo_info "Creating systemd service: $SERVICE_FILE"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Risos Backend
After=network.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_GROUP
WorkingDirectory=$BACKEND_DIR
Environment="PATH=$BACKEND_DIR/venv/bin"
ExecStart=$BACKEND_DIR/venv/bin/gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 127.0.0.1:$PORT --workers 1
Restart=always
RestartSec=5

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$BACKEND_DIR/data

[Install]
WantedBy=multi-user.target
EOF

# Set permissions
chown -R "$RUN_USER:$RUN_GROUP" "$BACKEND_DIR"
chmod 600 "$BACKEND_DIR/.env"

# Reload systemd and enable service
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo_info "Systemd service created and enabled"

# =============================================================================
# Nginx Configuration
# =============================================================================

# Check if WordOps is installed
if command -v wo &> /dev/null; then
    echo_info "WordOps detected - configuring nginx automatically"

    NGINX_CONF_DIR="$SCRIPT_DIR/conf/nginx"
    NGINX_CUSTOM_CONF="$NGINX_CONF_DIR/custom.conf"

    mkdir -p "$NGINX_CONF_DIR"

    echo_info "Creating nginx configuration: $NGINX_CUSTOM_CONF"

    cat > "$NGINX_CUSTOM_CONF" << 'NGINXEOF'
# Risos - Nginx Configuration
# Generated by install.sh

# Frontend - SPA routing
location / {
    try_files $uri $uri/ /index.html;
    expires 1h;
}

# Static assets caching
location /static/ {
    expires 30d;
    add_header Cache-Control "public, immutable";
}

NGINXEOF

    # Add API proxy with the correct port
    cat >> "$NGINX_CUSTOM_CONF" << NGINXEOF
# Backend API proxy
location /api/ {
    proxy_pass http://127.0.0.1:$PORT;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_connect_timeout 30s;
    proxy_read_timeout 60s;
}
NGINXEOF

    chown "$RUN_USER:$RUN_GROUP" "$NGINX_CUSTOM_CONF"

    echo_info "Nginx configuration created"
    echo_info "Reloading nginx..."

    if nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null; then
        echo_info "Nginx reloaded successfully"
    else
        echo_warn "Could not reload nginx. Run: nginx -t && systemctl reload nginx"
    fi

    WORDOPS_DETECTED=true
else
    echo_info "WordOps not detected - manual nginx configuration required"
    WORDOPS_DETECTED=false
fi

# =============================================================================
# Start Service
# =============================================================================

read -p "Start the service now? [Y/n]: " START_NOW
START_NOW=${START_NOW:-Y}

if [[ "$START_NOW" =~ ^[Yy]$ ]]; then
    systemctl start "$SERVICE_NAME"
    sleep 2
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo_info "Service started successfully!"
    else
        echo_error "Service failed to start. Check: journalctl -u $SERVICE_NAME"
        exit 1
    fi
fi

# =============================================================================
# Summary
# =============================================================================

echo ""
echo "============================================================================="
echo -e "${GREEN}Installation Complete!${NC}"
echo "============================================================================="
echo ""
echo "Backend running at: http://127.0.0.1:$PORT"
echo "Service name: $SERVICE_NAME"
echo ""
echo "Useful commands:"
echo "  systemctl status $SERVICE_NAME    # Check status"
echo "  systemctl restart $SERVICE_NAME   # Restart service"
echo "  journalctl -u $SERVICE_NAME -f    # View logs"
echo ""

if [ "$WORDOPS_DETECTED" = true ]; then
    echo "Next steps:"
    echo "  1. Edit $BACKEND_DIR/.env with your settings"
    echo "     - Set APP_PASSWORD, JWT_SECRET, and CEREBRAS_API_KEY"
    echo "  2. Restart the service: systemctl restart $SERVICE_NAME"
    echo ""
    echo "Nginx has been configured automatically at:"
    echo "  $NGINX_CUSTOM_CONF"
    echo ""
else
    echo "Next steps:"
    echo "  1. Edit $BACKEND_DIR/.env with your settings"
    echo "     - Set APP_PASSWORD, JWT_SECRET, and CEREBRAS_API_KEY"
    echo "  2. Configure nginx (see example below)"
    echo "  3. Restart the service: systemctl restart $SERVICE_NAME"
    echo ""
    echo "Example nginx configuration:"
    echo ""
    echo "  server {"
    echo "      listen 80;"
    echo "      server_name your-domain.com;"
    echo ""
    echo "      root $HTDOCS_DIR;"
    echo "      index index.html;"
    echo ""
    echo "      # Frontend - SPA routing"
    echo "      location / {"
    echo "          try_files \$uri \$uri/ /index.html;"
    echo "          expires 1h;"
    echo "      }"
    echo ""
    echo "      # Static assets caching"
    echo "      location /static/ {"
    echo "          expires 30d;"
    echo "          add_header Cache-Control \"public, immutable\";"
    echo "      }"
    echo ""
    echo "      # Backend API proxy"
    echo "      location /api/ {"
    echo "          proxy_pass http://127.0.0.1:$PORT;"
    echo "          proxy_http_version 1.1;"
    echo "          proxy_set_header Host \$host;"
    echo "          proxy_set_header X-Real-IP \$remote_addr;"
    echo "          proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;"
    echo "          proxy_set_header X-Forwarded-Proto \$scheme;"
    echo "      }"
    echo "  }"
    echo ""
fi
