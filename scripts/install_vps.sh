#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo ./scripts/install_vps.sh" >&2
  exit 1
fi

ENGINE_SRC=$(cd "$(dirname "$0")/.." && pwd)

AIDE_BASE=${AIDE_BASE:-/opt/aide}
AIDE_ENGINE=${AIDE_ENGINE:-$AIDE_BASE/engine}
AIDE_WORKSPACE=${AIDE_WORKSPACE:-$AIDE_BASE/workspace}
AIDE_USER=${AIDE_USER:-${SUDO_USER:-}}

if [[ -z "${AIDE_USER}" ]]; then
  AIDE_USER=root
  echo "Warning: AIDE_USER not set; using root." >&2
fi

USER_HOME=$(getent passwd "$AIDE_USER" | cut -d: -f6 || true)
if [[ -z "$USER_HOME" ]]; then
  USER_HOME="/home/$AIDE_USER"
fi
if [[ "$AIDE_USER" == "root" ]]; then
  USER_HOME="/root"
fi

echo "Installing system deps..."
apt update
apt install -y git python3 python3-pip python3-venv python3-full

mkdir -p "$AIDE_BASE"

if [[ ! -d "$AIDE_ENGINE/.git" ]]; then
  echo "Setting up engine at $AIDE_ENGINE"
  remote=$(git -C "$ENGINE_SRC" remote get-url origin 2>/dev/null || true)
  if [[ -n "$remote" ]]; then
    git clone "$remote" "$AIDE_ENGINE"
  else
    cp -a "$ENGINE_SRC" "$AIDE_ENGINE"
  fi
else
  echo "Engine already present at $AIDE_ENGINE"
fi

echo "Initializing workspace at $AIDE_WORKSPACE"
"$AIDE_ENGINE/scripts/init.sh" "$AIDE_WORKSPACE"

echo "Creating venv at $AIDE_BASE/venv"
python3 -m venv "$AIDE_BASE/venv"
"$AIDE_BASE/venv/bin/pip" install -r "$AIDE_ENGINE/requirements.txt"

echo "Fixing ownership for $AIDE_USER"
chown -R "$AIDE_USER:$AIDE_USER" "$AIDE_BASE"

echo "Installing systemd services"
cat > /etc/systemd/system/aide-bot.service <<EOF
[Unit]
Description=Aide Telegram Bot
After=network.target

[Service]
Type=simple
User=$AIDE_USER
Group=$AIDE_USER
WorkingDirectory=$AIDE_ENGINE
EnvironmentFile=$AIDE_WORKSPACE/.env
Environment="PATH=$AIDE_BASE/venv/bin:/usr/local/bin:/usr/bin:/bin:$USER_HOME/.local/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=$AIDE_BASE/venv/bin/python $AIDE_ENGINE/main.py --workspace $AIDE_WORKSPACE
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/aide-slack.service <<EOF
[Unit]
Description=Aide Slack Bot
After=network.target

[Service]
Type=simple
User=$AIDE_USER
Group=$AIDE_USER
WorkingDirectory=$AIDE_ENGINE
EnvironmentFile=$AIDE_WORKSPACE/.env
Environment="PATH=$AIDE_BASE/venv/bin:/usr/local/bin:/usr/bin:/bin:$USER_HOME/.local/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=$AIDE_BASE/venv/bin/python $AIDE_ENGINE/slack_bot.py --workspace $AIDE_WORKSPACE
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/aide-scheduler.service <<EOF
[Unit]
Description=Aide Scheduler
After=network.target

[Service]
Type=simple
User=$AIDE_USER
Group=$AIDE_USER
WorkingDirectory=$AIDE_ENGINE
EnvironmentFile=$AIDE_WORKSPACE/.env
Environment="PATH=$AIDE_BASE/venv/bin:/usr/local/bin:/usr/bin:/bin:$USER_HOME/.local/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=$AIDE_BASE/venv/bin/python $AIDE_ENGINE/scheduler.py --workspace $AIDE_WORKSPACE
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable aide-bot.service aide-slack.service aide-scheduler.service

token=$(grep -E "^TELEGRAM_TOKEN=" "$AIDE_WORKSPACE/.env" | cut -d= -f2- || true)
allowed=$(grep -E "^ALLOWED_USERS=" "$AIDE_WORKSPACE/.env" | cut -d= -f2- || true)
telegram_enabled=$(grep -E "^AIDE_TELEGRAM_ENABLED=" "$AIDE_WORKSPACE/.env" | cut -d= -f2- || true)
slack_token=$(grep -E "^SLACK_BOT_TOKEN=" "$AIDE_WORKSPACE/.env" | cut -d= -f2- || true)
slack_app_token=$(grep -E "^SLACK_APP_TOKEN=" "$AIDE_WORKSPACE/.env" | cut -d= -f2- || true)
slack_enabled=$(grep -E "^AIDE_SLACK_ENABLED=" "$AIDE_WORKSPACE/.env" | cut -d= -f2- || true)

started_any=0

if [[ "${telegram_enabled,,}" != "0" && "${telegram_enabled,,}" != "false" && "${telegram_enabled,,}" != "no" ]]; then
  if [[ -n "$token" && "$token" != "YOUR_TELEGRAM_BOT_TOKEN" && -n "$allowed" ]]; then
    systemctl start aide-bot.service
    started_any=1
  else
    echo "Telegram bot not started (missing TELEGRAM_TOKEN/ALLOWED_USERS)."
  fi
fi

if [[ "${slack_enabled,,}" != "0" && "${slack_enabled,,}" != "false" && "${slack_enabled,,}" != "no" ]]; then
  if [[ -n "$slack_token" && "$slack_token" != "YOUR_SLACK_BOT_TOKEN" && -n "$slack_app_token" && "$slack_app_token" != "YOUR_SLACK_APP_TOKEN" ]]; then
    systemctl start aide-slack.service
    started_any=1
  else
    echo "Slack bot not started (missing SLACK_BOT_TOKEN/SLACK_APP_TOKEN)."
  fi
fi

if [[ "$started_any" -eq 1 ]]; then
  systemctl start aide-scheduler.service
  echo "Services started."
else
  echo "Services enabled but not started."
  echo "Please edit $AIDE_WORKSPACE/.env (TELEGRAM_TOKEN/ALLOWED_USERS or SLACK_BOT_TOKEN/SLACK_APP_TOKEN), then run:"
  echo "  sudo systemctl start aide-bot.service aide-slack.service aide-scheduler.service"
fi

echo "Done."
