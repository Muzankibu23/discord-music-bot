#!/usr/bin/env bash
# Usage (sur le VPS, en root) : bash install.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Lance en root (sudo bash install.sh)"; exit 1; }
UNIT=/etc/systemd/system/rm-mcp.service
[ -e "$UNIT" ] && { echo "$UNIT existe déjà, abandon (rien n'a été modifié)."; exit 1; }
D=/opt/rm-mcp
read -rp "URL Odoo (https://odoo.example.com) : " ODOO_URL
read -rp "Base de données Odoo : " ODOO_DB
read -rp "Login de l'utilisateur Odoo dédié : " ODOO_LOGIN
read -rsp "Clé API de cet utilisateur : " ODOO_API_KEY; echo
read -rp "Domaine public du MCP (ex: mcp.example.com, vide si aucun) : " HOSTN
TOKEN=$(openssl rand -hex 32)

id rmmcp &>/dev/null || useradd -r -s /usr/sbin/nologin rmmcp
mkdir -p "$D"
cp "$(dirname "$0")"/{server.py,requirements.txt} "$D"/
python3 -m venv "$D/venv"
"$D/venv/bin/pip" install -q -r "$D/requirements.txt"
cat > "$D/.env" <<ENV
ODOO_URL=$ODOO_URL
ODOO_DB=$ODOO_DB
ODOO_LOGIN=$ODOO_LOGIN
ODOO_API_KEY=$ODOO_API_KEY
MCP_AUTH_TOKEN=$TOKEN
MCP_HOST=127.0.0.1
MCP_PORT=8765
MCP_ALLOWED_HOSTS=$HOSTN
ENV
chown -R rmmcp: "$D"; chmod 600 "$D/.env"
cp "$(dirname "$0")/rm-mcp.service" "$UNIT"
systemctl daemon-reload && systemctl enable --now rm-mcp
sleep 2; systemctl is-active rm-mcp
echo
echo "MCP écoute sur 127.0.0.1:8765/mcp  (reverse proxy HTTPS à ajouter)"
echo "Token Bearer (note-le, affiché une seule fois) : $TOKEN"
