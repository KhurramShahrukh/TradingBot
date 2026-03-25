# DigitalOcean Ubuntu 24.04 deployment

## 1. Droplet (DigitalOcean console)

- Image: **Ubuntu 24.04 LTS**
- Add your **SSH public key**
- Create a **cloud firewall** (or use `ufw` via `setup-server.sh`) allowing **SSH (22)** only

### Choosing a size

| Plan (typical) | RAM | Notes |
|----------------|-----|--------|
| **~$6/mo** | **1 GB** | **Recommended** for this bot: pandas + ccxt + many pairs in `config.json` fits comfortably. |
| ~$4/mo | 512 MB | Works if you add **swap** (`sudo bash deploy/add-swap.sh`) and watch for OOM in `journalctl -k`. |

Extra disk/bandwidth on the larger tier is only relevant for logs and backups; both are fine for SQLite and this workload.

## 2. First SSH session

```bash
sudo bash deploy/setup-server.sh
```

## 3. Application files

As user `tradingbot` (or your chosen user), put the project under `/opt/tradingbot` (or set `APP_DIR` when running `setup-server.sh`):

```bash
sudo -u tradingbot -H bash
cd /opt/tradingbot
# git clone <your-repo> .   OR   rsync from your machine into this directory
```

## 4. Install Python deps

```bash
bash deploy/install-app.sh
```

## 5. Config and secrets

- Ensure `config.json` is present and reviewed (`paper_trading`, risk settings).
- `cp .env.example .env`, edit values, then `chmod 600 .env`

## 6. Smoke test

```bash
source .venv/bin/activate
python test_run.py
```

## 7. systemd

```bash
exit   # back to a user with sudo
sudo bash /opt/tradingbot/deploy/install-systemd.sh
```

Override defaults if needed:

```bash
sudo APP_USER=tradingbot SERVICE_NAME=tradingbot bash /opt/tradingbot/deploy/install-systemd.sh
```

**Monitor:** `journalctl -u tradingbot -f`  
**App log file:** `logs/bot.log`

## 8. Operations

- **Binance API IP restriction:** allow the droplet’s public IP.
- **Backups:** `bash deploy/backup-state.sh` (sets `BACKUP_DEST` to change output dir).
