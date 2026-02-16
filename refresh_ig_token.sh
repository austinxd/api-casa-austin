#!/bin/bash
# Auto-renovación del token de Instagram cada 50 días
# Instalar en cron:
#   crontab -e
#   0 3 */50 * * /srv/casaaustin/api-casa-austin/refresh_ig_token.sh >> /var/log/refresh_ig_token.log 2>&1

PROJECT_DIR="/srv/casaaustin/api-casa-austin"
VENV="$PROJECT_DIR/venv-py311"
MANAGE="$PROJECT_DIR/src/manage.py"

echo "=========================================="
echo "$(date): Renovando token de Instagram..."
echo "=========================================="

# Activar venv y ejecutar comando
source "$VENV/bin/activate"
cd "$PROJECT_DIR/src"
python "$MANAGE" refresh_ig_token

if [ $? -eq 0 ]; then
    echo "$(date): Token renovado. Reiniciando servicio..."
    supervisorctl restart api-erp
    echo "$(date): Servicio reiniciado."
else
    echo "$(date): ERROR al renovar token."
    exit 1
fi
