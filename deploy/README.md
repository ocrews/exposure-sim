# Deploying exposure-sim on a Raspberry Pi

`setup-pi.sh` hardens a fresh Raspberry Pi OS install and runs the game as a sandboxed
systemd service. `teardown-pi.sh` removes it again. Both are safe to re-run.

**Assumes:** Raspberry Pi OS Lite (64-bit), SSH with key-only login (set in Raspberry Pi
Imager), and the Pi on your home network.

## What the setup does

| Step | Result |
|---|---|
| 0. Preflight | Stops if SSH still allows passwords, or if your SSH session would be cut off by the firewall |
| 1. Updates | Full upgrade; automatic **security** updates daily. Kernel/firmware updates stay manual |
| 2. Firewall | ufw: deny all inbound (IPv4 and IPv6) except SSH and port 8000 from your LAN |
| 3. Logs | journald kept across reboots, capped at 50 MB to limit SD card wear |
| 4. Service account | `exposure-sim`: no login shell, no password |
| 5. Code | Cloned to `/opt/exposure-sim/app`, owned by root, read-only to the service account |
| 6. Secret | Random session key in `/etc/exposure-sim/exposure-sim.env`, `root:root 0600`, never printed |
| 7. Service | gunicorn under systemd with a read-only filesystem and no privileges; starts on boot |
| 8. Tunnel (optional) | `--tunnel` publishes it on a temporary `trycloudflare.com` URL |
| 9. Checks | Verifies the firewall, the account, and the service, then prints a PASS/FAIL summary |

## Run it

**Before the first run, open a second SSH session to the Pi and leave it idle.** If the
firewall step ever locks you out, that session stays connected and you can run
`sudo ufw disable` from it.

Pi · user `ocrews` · ⚠️ needs sudo:

```bash
git clone https://github.com/ocrews/exposure-sim && cd exposure-sim
sudo bash deploy/setup-pi.sh
```

- **Pass:** the summary is all `PASS` (a `WARN` about rebooting is fine), and it ends with
  `Open the game ... http://192.168.1.x:8000`. Open that URL from your phone or PC on the
  same Wi-Fi.
- **Fail:** the script stops at the first failing step and says why. Nothing after that
  step runs. Fix the cause and re-run; finished steps are skipped or repeated harmlessly.
- If it printed the reboot warning: `sudo reboot`, wait a minute, SSH back in.

Then, from a **new** SSH session (proves the firewall still lets you in):

```bash
sudo ufw status verbose
systemctl status exposure-sim --no-pager
```

- **Pass:** `Status: active`, `Default: deny (incoming)`, and the service `active (running)`.

## Make it public (optional, temporary)

```bash
sudo bash deploy/setup-pi.sh --tunnel      # prints https://<random>.trycloudflare.com
sudo bash deploy/setup-pi.sh --no-tunnel   # turns it off again
```

Quick tunnels are Cloudflare's test feature: no uptime guarantee, a new URL every time the
tunnel restarts, and anyone with the URL can open the game. Fine for showing someone; for a
permanent address, use a named tunnel on your own domain.

## Update the app

Re-run the same command. It pulls the latest `main`, reinstalls dependencies, and restarts
the service. The secret is kept, so players don't lose progress.

```bash
cd ~/exposure-sim && git pull && sudo bash deploy/setup-pi.sh
```

## Day to day

```bash
journalctl -u exposure-sim -f            # live logs
sudo systemctl restart exposure-sim      # restart the app
sudo unattended-upgrade --dry-run -d     # see what auto-updates would install
```

## Teardown / rollback

Pi · user `ocrews` · ⚠️ needs sudo:

```bash
sudo bash deploy/teardown-pi.sh                     # remove app, service, tunnel, secret, account
sudo bash deploy/teardown-pi.sh --firewall-too      # also reset ufw and turn off auto-updates
sudo bash deploy/teardown-pi.sh --purge-cloudflared # also uninstall cloudflared
```

- **Pass:** `systemctl status exposure-sim` says the unit could not be found, and
  `ls /opt/exposure-sim` fails.
- By default the firewall, automatic security updates, and log cap stay in place, since
  they're good for the Pi either way. System upgrades are never rolled back.
- For a completely clean slate, re-flash the SD card.

## How it was tested

- `shellcheck` clean; both systemd units pass `systemd-analyze verify`.
- Full cycle in an isolated sandbox: setup, a second setup, then teardown. Real git, Python
  venv, pip, gunicorn, user and permission handling; stand-ins only for apt, ufw, systemd,
  sshd and network detection. Verified:
  - the secret is unchanged by a re-run, `root:root 0600`, and never appears in any output
  - firewall rules are not duplicated on re-run, and the SSH rule is added before `ufw enable`
  - the service account can't modify the code or read the secret
  - teardown removes the app and its port rule but keeps SSH access
  - the script stops before touching the firewall if SSH allows passwords or your session
    comes from outside the LAN
- **Not tested here:** the Cloudflare tunnel step (needs internet access the sandbox
  doesn't have) and real systemd sandboxing on the Pi. Check those on the first run.
