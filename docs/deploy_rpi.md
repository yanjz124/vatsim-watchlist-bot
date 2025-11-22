# Raspberry Pi deploy notes

This document explains how to wire the repository to automatically install new Python dependencies and restart the systemd service after a `git pull` on the Raspberry Pi.

1) Place the repo on the Pi (example path `/home/pi/vatsim-watchlist-bot`).

2) Install system dependencies if required by additional extensions (none required by default):

```bash
sudo apt-get update
```

3) Create a virtualenv (recommended):

```bash
cd /home/pi/vatsim-watchlist-bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
deactivate
```

4) Install the systemd unit (adjust paths and user):

```bash
sudo cp systemd/vatsim-watchlist-bot.service.example /etc/systemd/system/vatsim-watchlist-bot.service
sudo systemctl daemon-reload
sudo systemctl enable vatsim-watchlist-bot.service
sudo systemctl start vatsim-watchlist-bot.service
```

If using a virtualenv, edit the `ExecStart` in the unit file to point to `/home/pi/vatsim-watchlist-bot/.venv/bin/python /home/pi/vatsim-watchlist-bot/bot.py` and set `WorkingDirectory` appropriately.

5) Setup post-merge hook for automatic deploy after `git pull`:

On the Pi, in the repo's `.git/hooks` folder, create a file named `post-merge` and paste the contents of `scripts/post-merge-hook.sh` into it, or symlink to that file. Make it executable:

```bash
cd /home/pi/vatsim-watchlist-bot
ln -s ../../scripts/post-merge-hook.sh .git/hooks/post-merge
chmod +x .git/hooks/post-merge
```

Now, whenever you `git pull` on the Pi (or the auto-update pulls new commits), the post-merge hook will call `scripts/deploy.sh`, which installs new requirements into the active Python environment and restarts the systemd service.

Notes & caveats
- The deploy script assumes either a virtualenv at `.venv` or system Python.
- `deploy.sh` uses `sudo systemctl restart vatsim-watchlist-bot.service` — ensure the service name matches your unit and the user has sudo rights.
- Running `pip install` on every deploy may be slow; for faster deploys consider building a Docker image or using CI to push artifacts.
- For safer deployments, consider adding logging and health checks to ensure service restarted successfully.
