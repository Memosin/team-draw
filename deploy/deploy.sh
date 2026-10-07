#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/home/deployuser/apps/team-draw
SERVICE_FILE=/etc/systemd/system/team-draw.service
NGINX_SITE=/etc/nginx/sites-available/team-draw
NGINX_TEMPLATE="$APP_DIR/deploy/team-draw.nginx"
ENV_FILE="$APP_DIR/.env"

echo "Pulling latest code..."
git -C "$APP_DIR" pull --ff-only origin main

echo "Installing Python dependencies..."
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [ ! -f "$ENV_FILE" ]; then
	echo "Missing $ENV_FILE. Copy .env.example to .env and set APP_DOMAIN first."
	exit 1
fi

APP_DOMAIN=$(sed -n 's/^APP_DOMAIN=//p' "$ENV_FILE" | tail -n 1 | tr -d '\r')
if [[ ! "$APP_DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]; then
	echo "APP_DOMAIN in $ENV_FILE must be a hostname containing only letters, numbers, dots, and hyphens."
	exit 1
fi

echo "Copying systemd service..."
sudo cp "$APP_DIR/deploy/team-draw.service" "$SERVICE_FILE"
sudo chown root:root "$SERVICE_FILE"
sudo chmod 644 "$SERVICE_FILE"
sudo systemctl daemon-reload
sudo systemctl enable team-draw.service
sudo systemctl restart team-draw.service

if [ ! -e "$NGINX_SITE" ]; then
	echo "Installing nginx site configuration for $APP_DOMAIN..."
	sed "s/__APP_DOMAIN__/$APP_DOMAIN/g" "$NGINX_TEMPLATE" | sudo tee "$NGINX_SITE" >/dev/null
else
	echo "Updating nginx hostname to $APP_DOMAIN while preserving existing TLS settings..."
	sudo sed -E -i "s|^[[:space:]]*server_name[[:space:]]+[^;]+;|    server_name $APP_DOMAIN;|" "$NGINX_SITE"
fi

sudo ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/team-draw
sudo nginx -t
sudo systemctl reload nginx

echo "Done. Enable HTTPS after DNS points to this droplet: sudo certbot --nginx -d $APP_DOMAIN"