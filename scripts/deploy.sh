#!/usr/bin/env bash
# Production deployment script template.
# Customize for your EC2 / AWS / Cloud target.
set -euo pipefail

EC2_HOST="${EC2_HOST:-your.server.ip}"
EC2_USER="${EC2_USER:-ubuntu}"
KEY_FILE="${KEY_FILE:-~/.ssh/your-key.pem}"
APP_NAME="${APP_NAME:-my-app}"

echo "▶ Build artifacts..."
tar -czf "$APP_NAME.tar.gz" \
  --exclude='node_modules' \
  --exclude='.next' \
  --exclude='__pycache__' \
  --exclude='.git' \
  --exclude='*.tar.gz' \
  .

echo "▶ Upload to $EC2_HOST..."
scp -i "$KEY_FILE" "$APP_NAME.tar.gz" "$EC2_USER@$EC2_HOST:~/"

echo "▶ Deploy on remote..."
ssh -i "$KEY_FILE" "$EC2_USER@$EC2_HOST" bash <<EOF
  set -e
  cd ~/
  rm -rf "$APP_NAME" || true
  mkdir "$APP_NAME"
  tar -xzf "$APP_NAME.tar.gz" -C "$APP_NAME/"
  cd "$APP_NAME"
  docker-compose down || true
  docker-compose -f docker-compose.yml up -d --build
EOF

echo "▶ Cleanup local tar..."
rm "$APP_NAME.tar.gz"

echo "✅ Deployed to http://$EC2_HOST/"
