#!/usr/bin/env bash
# Установка lab-chat на Debian/Ubuntu/Astra.
# Использование: sudo bash deploy/install.sh /path/to/lab-chat
set -euo pipefail

SRC="${1:-$(pwd)}"
DST=/opt/lab-chat
USER_NAME=labchat

apt-get update
apt-get install -y python3 python3-venv python3-pip rsync

id -u "$USER_NAME" >/dev/null 2>&1 || useradd --system --home "$DST" --shell /usr/sbin/nologin "$USER_NAME"

mkdir -p "$DST"
rsync -a --delete \
  --exclude .git --exclude .venv --exclude data \
  "$SRC"/ "$DST"/

[ -f "$DST/.env" ] || cp "$DST/.env.example" "$DST/.env"
mkdir -p "$DST/data"

python3 -m venv "$DST/.venv"
"$DST/.venv/bin/pip" install --upgrade pip
"$DST/.venv/bin/pip" install -r "$DST/requirements.txt"

chown -R "$USER_NAME:$USER_NAME" "$DST"

install -m 644 "$DST/deploy/lab-chat.service" /etc/systemd/system/lab-chat.service
systemctl daemon-reload
systemctl enable --now lab-chat

echo "Готово. Проверка: curl -s http://127.0.0.1:8000/api/state"
echo "Не забудь: nano $DST/.env и python $DST/tools/create_user.py <login>"
