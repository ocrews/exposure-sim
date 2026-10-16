#!/usr/bin/env bash
# exposure-sim: remove everything setup-pi.sh installed for the app.
#
#   sudo bash deploy/teardown-pi.sh                   # remove app, service, tunnel, secret, user
#   sudo bash deploy/teardown-pi.sh --firewall-too    # also reset ufw and turn off auto-updates
#   sudo bash deploy/teardown-pi.sh --purge-cloudflared   # also uninstall cloudflared and its apt repo
#
# By default the hardening (firewall, automatic security updates, log cap) stays in place,
# since it's good for the Pi whether or not the app is installed. System upgrades are never
# rolled back.
set -euo pipefail

APP=exposure-sim
APP_USER=exposure-sim
APP_DIR=/opt/exposure-sim
ENV_DIR=/etc/exposure-sim
APP_PORT=${APP_PORT:-8000}
FIREWALL_TOO=""
PURGE_CF=""

for arg in "$@"; do
  case $arg in
    --firewall-too) FIREWALL_TOO=1 ;;
    --purge-cloudflared) PURGE_CF=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done
[[ $EUID -eq 0 ]] || { echo "Run with sudo: sudo bash $0 $*" >&2; exit 1; }

done_() { printf '   \033[32mdone\033[0m %s\n' "$*"; }

for unit in exposure-sim-tunnel exposure-sim; do
  systemctl disable -q --now "$unit" 2>/dev/null || true
  rm -f "/etc/systemd/system/${unit}.service"
done
systemctl daemon-reload
done_ "services stopped and removed"

rm -rf "$APP_DIR" "$ENV_DIR"
done_ "code, virtualenv and secret removed"

if id "$APP_USER" >/dev/null 2>&1; then
  userdel "$APP_USER"
  getent group "$APP_USER" >/dev/null && groupdel "$APP_USER"
fi
done_ "service account removed"

# Remove only the app's port rule; leave SSH and the defaults alone.
while grep -q "${APP_PORT}/tcp.*exposure-sim from LAN" <<<"$(ufw status numbered)"; do
  n=$(ufw status numbered | grep "${APP_PORT}/tcp.*exposure-sim from LAN" | head -1 | sed -E 's/^\[ *([0-9]+)\].*/\1/')
  ufw --force delete "$n" >/dev/null
done
done_ "firewall rule for port ${APP_PORT} removed"

if [[ -n $FIREWALL_TOO ]]; then
  ufw --force reset >/dev/null
  ufw disable >/dev/null || true
  rm -f /etc/apt/apt.conf.d/20auto-upgrades /etc/systemd/journald.conf.d/50-exposure-sim.conf
  systemctl restart systemd-journald
  done_ "firewall reset and disabled, auto-updates and log cap removed"
fi

if [[ -n $PURGE_CF ]]; then
  apt-get -y -q purge cloudflared >/dev/null 2>&1 || true
  rm -f /etc/apt/sources.list.d/cloudflared.list /usr/share/keyrings/cloudflare-main.gpg
  apt-get update -q >/dev/null
  done_ "cloudflared and its apt repository removed"
fi

printf '\nCheck: systemctl status %s should say "could not be found", and ls %s should fail.\n' "$APP" "$APP_DIR"
