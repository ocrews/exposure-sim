#!/usr/bin/env bash
# exposure-sim: one-shot, re-runnable setup for a Raspberry Pi (Raspberry Pi OS / Debian).
#
#   sudo bash deploy/setup-pi.sh              # harden + deploy, LAN only
#   sudo bash deploy/setup-pi.sh --tunnel     # also publish via a Cloudflare quick tunnel
#   sudo bash deploy/setup-pi.sh --no-tunnel  # turn the quick tunnel off again
#
# Safe to re-run: every step checks current state first. Re-running is also how you
# update the app (it pulls the latest main and restarts the service).
#
# Before the FIRST run: keep a second SSH session open in case the firewall step
# locks you out. The script refuses to enable the firewall if your SSH session
# would not be allowed by it.
#
# Overrides (environment variables):
#   LAN_CIDR=192.168.1.0/24   network allowed to SSH and reach the app (default: auto-detect)
#   APP_PORT=8000             port the app listens on
#   REPO_URL / REPO_BRANCH    where to deploy from (default: this repo's GitHub, main)
set -euo pipefail

APP=exposure-sim
APP_USER=exposure-sim
APP_DIR=/opt/exposure-sim
SRC_DIR=$APP_DIR/app
VENV_DIR=$APP_DIR/venv
ENV_DIR=/etc/exposure-sim
ENV_FILE=$ENV_DIR/exposure-sim.env
UNIT=/etc/systemd/system/exposure-sim.service
TUNNEL_UNIT=/etc/systemd/system/exposure-sim-tunnel.service
JOURNAL_CONF=/etc/systemd/journald.conf.d/50-exposure-sim.conf
APP_PORT=${APP_PORT:-8000}
REPO_URL=${REPO_URL:-https://github.com/ocrews/exposure-sim.git}
REPO_BRANCH=${REPO_BRANCH:-main}
TUNNEL_MODE=keep        # keep | on | off

# ---- output helpers ---------------------------------------------------------------------
RESULTS=()
step()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
info()  { printf '   %s\n' "$*"; }
pass()  { printf '   \033[32mPASS\033[0m %s\n' "$*"; RESULTS+=("PASS  $*"); }
warn()  { printf '   \033[33mWARN\033[0m %s\n' "$*"; RESULTS+=("WARN  $*"); }
fail()  { printf '   \033[31mFAIL\033[0m %s\n' "$*" >&2; RESULTS+=("FAIL  $*"); summary; exit 1; }
summary() {
  printf '\n\033[1m== Summary\033[0m\n'
  printf '   %s\n' "${RESULTS[@]}"
}
trap 'printf "\n\033[31mStopped at line %s (exit %s). Nothing after this point ran.\033[0m\n" "$LINENO" "$?" >&2' ERR

usage() { sed -n '2,20p' "$0"; exit "${1:-0}"; }
for arg in "$@"; do
  case $arg in
    --tunnel) TUNNEL_MODE=on ;;
    --no-tunnel) TUNNEL_MODE=off ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown option: $arg" >&2; usage 2 ;;
  esac
done

# ---- 0. preflight -------------------------------------------------------------------------
step "0. Preflight"
[[ $EUID -eq 0 ]] || { echo "Run with sudo: sudo bash $0 $*" >&2; exit 1; }
command -v apt-get >/dev/null || fail "apt-get not found; this script targets Raspberry Pi OS / Debian"
. /etc/os-release
pass "OS: ${PRETTY_NAME}"

if [[ -z ${LAN_CIDR:-} ]]; then
  dev=$(ip -4 route show default | awk '{print $5; exit}')
  addr=$(ip -4 -o addr show dev "$dev" | awk '{print $4; exit}')
  LAN_CIDR=$(python3 -c "import ipaddress,sys; print(ipaddress.ip_interface(sys.argv[1]).network)" "$addr")
fi
LAN_IP=$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<NF;i++) if($i=="src") {print $(i+1); exit}}')
pass "LAN network ${LAN_CIDR}, this Pi is ${LAN_IP}"

# Refuse to continue if SSH still accepts passwords: the firewall is not a substitute for that.
# Output is captured first: 'cmd | grep -q' can fail under pipefail when grep exits early.
if grep -qx 'passwordauthentication yes' <<<"$(sshd -T 2>/dev/null)"; then
  fail "sshd still allows password logins. Set 'PasswordAuthentication no' in /etc/ssh/sshd_config.d/ and re-run."
fi
pass "sshd: password logins disabled"

# Lockout guard: every current SSH session must come from LAN_CIDR, or enabling ufw would cut it off.
python3 - "$LAN_CIDR" <<'PY' || fail "An SSH session is connected from outside ${LAN_CIDR}; enabling the firewall would drop it. Set LAN_CIDR or connect from the LAN."
import ipaddress, subprocess, sys
net = ipaddress.ip_network(sys.argv[1])
out = subprocess.run(["ss", "-Htn", "state", "established", "( sport = :22 )"],
                     capture_output=True, text=True, check=True).stdout
for line in out.splitlines():
    peer = line.split()[-1].rsplit(":", 1)[0].strip("[]")
    ip = ipaddress.ip_address(peer)
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    if ip.version != 4 or ip not in net:
        print(f"   SSH session from {peer} is outside {net}", file=sys.stderr)
        sys.exit(1)
PY
pass "all current SSH sessions come from ${LAN_CIDR}"

# ---- 1. packages and automatic security updates ------------------------------------------
step "1. Packages and automatic security updates"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get -y -q -o Dpkg::Options::=--force-confold full-upgrade
apt-get -y -q install git python3-venv curl ufw unattended-upgrades apt-listchanges
pass "system upgraded and packages installed"

cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
# Default origins = Debian security updates only. Kernel/firmware updates from
# archive.raspberrypi.com stay manual so a kernel update can't reboot the Pi unattended.
systemctl enable --now apt-daily.timer apt-daily-upgrade.timer >/dev/null
pass "unattended security updates enabled (kernel/firmware stay manual)"
[[ -f /var/run/reboot-required ]] && warn "a reboot is needed for installed updates: run 'sudo reboot' after this script"

# ---- 2. firewall ------------------------------------------------------------------------
step "2. Firewall (IPv4 + IPv6)"
grep -q '^IPV6=yes' /etc/default/ufw || sed -i 's/^IPV6=.*/IPV6=yes/' /etc/default/ufw
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
# Allow rules go in BEFORE 'ufw enable'. ufw skips rules that already exist, so re-runs don't duplicate.
ufw allow from "$LAN_CIDR" to any port 22 proto tcp comment 'SSH from LAN' >/dev/null
ufw allow from "$LAN_CIDR" to any port "$APP_PORT" proto tcp comment 'exposure-sim from LAN' >/dev/null
ufw logging low >/dev/null
ufw --force enable >/dev/null
grep -q '^Status: active' <<<"$(ufw status)" || fail "ufw is not active"
pass "ufw active: inbound denied except SSH and port ${APP_PORT} from ${LAN_CIDR}; no IPv6 inbound"

# ---- 3. journald: keep logs across reboots, capped -------------------------------------
step "3. Log size limit"
mkdir -p "$(dirname "$JOURNAL_CONF")"
cat > "$JOURNAL_CONF" <<'EOF'
[Journal]
Storage=persistent
SystemMaxUse=50M
EOF
systemctl restart systemd-journald
pass "journald persistent, capped at 50 MB"

# ---- 4. service account ------------------------------------------------------------------
step "4. Service account"
if id "$APP_USER" >/dev/null 2>&1; then
  pass "user ${APP_USER} already exists"
else
  useradd --system --user-group --no-create-home --home-dir "$APP_DIR" \
          --shell /usr/sbin/nologin --comment "exposure-sim service" "$APP_USER"
  pass "created system user ${APP_USER} (no login, no password)"
fi
install -d -o root -g "$APP_USER" -m 0750 "$APP_DIR"

# ---- 5. application code -----------------------------------------------------------------
step "5. Application code"
# Code is owned by root and only readable by the service account, so a compromised app
# can't modify itself.
if [[ -d $SRC_DIR/.git ]]; then
  git -C "$SRC_DIR" fetch -q origin "$REPO_BRANCH"
  git -C "$SRC_DIR" reset -q --hard "origin/$REPO_BRANCH"
  info "updated existing checkout"
else
  git clone -q --branch "$REPO_BRANCH" "$REPO_URL" "$SRC_DIR"
  info "cloned ${REPO_URL}"
fi
pass "code at ${SRC_DIR} is $(git -C "$SRC_DIR" log -1 --format='%h %s')"

[[ -x $VENV_DIR/bin/python ]] || python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -q --upgrade pip
"$VENV_DIR/bin/pip" install -q -r "$SRC_DIR/requirements-prod.txt"
"$VENV_DIR/bin/python" -m compileall -q "$SRC_DIR/exposure_sim" >/dev/null
chown -R root:"$APP_USER" "$APP_DIR"
chmod -R u=rwX,g=rX,o= "$APP_DIR"
pass "virtualenv ready with $("$VENV_DIR/bin/gunicorn" --version 2>&1 | head -1)"

# ---- 6. secret key -----------------------------------------------------------------------
step "6. Secret key"
install -d -o root -g root -m 0700 "$ENV_DIR"
if [[ -s $ENV_FILE ]] && grep -q '^EXPOSURE_SIM_SECRET=.\+' "$ENV_FILE"; then
  pass "existing secret kept (sessions stay valid)"
else
  umask 077
  # Generated here, written straight to the file, never printed.
  printf 'EXPOSURE_SIM_SECRET=%s\n' "$(python3 -c 'import secrets; print(secrets.token_hex(32))')" > "$ENV_FILE"
  pass "new secret generated"
fi
chown root:root "$ENV_FILE"
chmod 0600 "$ENV_FILE"
[[ $(stat -c '%U:%G %a' "$ENV_FILE") == "root:root 600" ]] || fail "secret file permissions are wrong"
pass "secret file is root:root 0600 (systemd reads it as root before dropping privileges)"

# ---- 7. systemd service ------------------------------------------------------------------
step "7. App service (gunicorn + systemd)"
cat > "$UNIT" <<EOF
[Unit]
Description=exposure-sim (gunicorn)
After=network-online.target
Wants=network-online.target

[Service]
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${SRC_DIR}
EnvironmentFile=${ENV_FILE}
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=${VENV_DIR}/bin/gunicorn --workers 2 --bind 0.0.0.0:${APP_PORT} --access-logfile - "exposure_sim:create_app()"
Restart=on-failure
RestartSec=3

# Sandboxing: read-only filesystem, no new privileges, no devices, no kernel access.
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
CapabilityBoundingSet=
SystemCallArchitectures=native
SystemCallFilter=@system-service
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q "$APP"
systemctl restart "$APP"

ok=""
for _ in $(seq 1 20); do
  if curl -fsS -o /dev/null "http://127.0.0.1:${APP_PORT}/"; then ok=1; break; fi
  sleep 1
done
[[ -n $ok ]] || { journalctl -u "$APP" -n 30 --no-pager >&2; fail "app did not answer on port ${APP_PORT}"; }
grep -q 'Prairie Freight' <<<"$(curl -fsS "http://127.0.0.1:${APP_PORT}/")" || fail "app answered but the page looks wrong"
pass "app running as ${APP_USER}, answering on port ${APP_PORT}"

# ---- 8. optional quick tunnel ------------------------------------------------------------
step "8. Public access (Cloudflare quick tunnel)"
case $TUNNEL_MODE in
  on)
    if ! command -v cloudflared >/dev/null; then
      install -d -m 0755 /usr/share/keyrings
      curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
      echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
        > /etc/apt/sources.list.d/cloudflared.list
      apt-get update -q
      apt-get -y -q install cloudflared
    fi
    pass "$(cloudflared --version 2>&1 | head -1)"
    cat > "$TUNNEL_UNIT" <<EOF
[Unit]
Description=exposure-sim Cloudflare quick tunnel (temporary trycloudflare.com URL)
After=network-online.target ${APP}.service
Wants=network-online.target
Requires=${APP}.service

[Service]
DynamicUser=yes
ExecStart=/usr/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:${APP_PORT}
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable -q exposure-sim-tunnel
    systemctl restart exposure-sim-tunnel
    url=""
    for _ in $(seq 1 30); do
      url=$(journalctl -u exposure-sim-tunnel --since '-2min' --no-pager -o cat \
            | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1 || true)
      [[ -n $url ]] && break
      sleep 1
    done
    [[ -n $url ]] || fail "tunnel started but no URL appeared; see: journalctl -u exposure-sim-tunnel"
    pass "public URL: ${url} (changes every time the tunnel restarts)"
    ;;
  off)
    if systemctl list-unit-files exposure-sim-tunnel.service >/dev/null 2>&1 && [[ -f $TUNNEL_UNIT ]]; then
      systemctl disable -q --now exposure-sim-tunnel || true
      rm -f "$TUNNEL_UNIT"
      systemctl daemon-reload
      pass "quick tunnel stopped and removed; app is LAN-only"
    else
      pass "no quick tunnel configured; app is LAN-only"
    fi
    ;;
  keep)
    if systemctl is-active -q exposure-sim-tunnel 2>/dev/null; then
      url=$(journalctl -u exposure-sim-tunnel --no-pager -o cat | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1 || true)
      pass "quick tunnel still running${url:+: ${url}}"
    else
      pass "LAN only (re-run with --tunnel to publish)"
    fi
    ;;
esac

# ---- 9. final checks ---------------------------------------------------------------------
step "9. Final checks"
# check "pass message" "fail message" command...   (runs the command; passes if it succeeds)
check() { local ok_msg=$1 bad_msg=$2; shift 2; if "$@"; then pass "$ok_msg"; else fail "$bad_msg"; fi; }
default_deny()  { grep -q 'Default: deny (incoming)' <<<"$(ufw status verbose)"; }
one_ssh_rule()  { [[ $(grep -c "22/tcp.*ALLOW IN.*${LAN_CIDR}" <<<"$(ufw status)") -eq 1 ]]; }
no_v6_allow()   { ! grep -q '(v6).*ALLOW' <<<"$(ufw status)"; }
no_login()      { [[ $(getent passwd "$APP_USER" | cut -d: -f7) == /usr/sbin/nologin ]]; }
runs_as_app()   { [[ $(systemctl show -p User --value "$APP") == "$APP_USER" ]]; }

check "firewall default: deny incoming"     "firewall default is not deny"     default_deny
check "exactly one SSH allow rule"          "SSH rule missing or duplicated"   one_ssh_rule
check "no inbound IPv6 allowed"             "an IPv6 allow rule exists"        no_v6_allow
check "${APP_USER} cannot log in"           "${APP_USER} has a login shell"    no_login
check "app starts on boot"                  "app not enabled at boot"          systemctl is-enabled -q "$APP"
check "app runs as ${APP_USER}, not root"   "app user is wrong"                runs_as_app

summary
printf '\nOpen the game from any device on your network: \033[1mhttp://%s:%s\033[0m\n' "$LAN_IP" "$APP_PORT"
printf 'Logs: journalctl -u %s -f    Update: re-run this script    Remove: sudo bash deploy/teardown-pi.sh\n' "$APP"
