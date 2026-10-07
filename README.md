# Team Draw

A lightweight, self-hosted app for random team draws, balanced assignments, and shareable results.

Paste captains and participants one per line, or enter a comma-separated list on a single line. Set the maximum team size; captains count toward that limit. Participants are shuffled and assigned as evenly as possible; anyone beyond capacity is listed as overflow for the organizer to place. Each draw is saved to SQLite and gets an unlisted share link and downloadable PDF.

The default labels are **Captains** and **Fishermen**. Deployers can change the app name and labels with environment variables, so the same app can be used for other sports or group draws.

## Run locally

Requires Python 3.10 or newer.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

Open http://127.0.0.1:5000. The default database is created at `instance/team_draw.sqlite3`; `.env` can override its location with `DATABASE_PATH`.

To run the focused tests:

```powershell
python -m unittest discover -s tests -v
```

## Configure labels

Set these values in `.env` or in the service environment:

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_NAME` | `Team Draw` | Browser title and app wordmark |
| `APP_DOMAIN` | `team-draw.example.com` | Hostname used by the deployment script for Nginx and HTTPS |
| `CAPTAIN_LABEL` | `Captains` | Label for team leaders |
| `PARTICIPANT_LABEL` | `Fishermen` | Label for assigned people |
| `TEAM_LABEL` | `Team` | Prefix for generated team names |
| `DATABASE_PATH` | `instance/team_draw.sqlite3` | SQLite database location |

## Deploy on Ubuntu with Nginx

The deployment files use the existing `deployuser` account and keep code, service, Nginx site, and database separate from other apps on the droplet. The database is stored outside the Git checkout at `/home/deployuser/data/team-draw/draws.sqlite3`.

One-time setup (replace the clone URL if the GitHub owner differs):

```bash
sudo apt update
sudo apt install -y git nginx python3-venv certbot python3-certbot-nginx
sudo mkdir -p /home/deployuser/apps /home/deployuser/data/team-draw
sudo chown -R deployuser:deployuser /home/deployuser/apps /home/deployuser/data/team-draw
sudo -u deployuser git clone https://github.com/Memosin/team-draw.git /home/deployuser/apps/team-draw
cd /home/deployuser/apps/team-draw
sudo -u deployuser python3 -m venv .venv
sudo -u deployuser .venv/bin/pip install -r requirements.txt
sudo -u deployuser cp .env.example .env
sudo -u deployuser nano .env
```

Set `APP_DOMAIN` to the hostname pointed at the droplet, set the public labels, and confirm `DATABASE_PATH=/home/deployuser/data/team-draw/draws.sqlite3` in `.env`. Then run the deploy script to install the service and render the Nginx site from that hostname:

```bash
chmod +x deploy/deploy.sh
./deploy/deploy.sh
APP_DOMAIN="$(sed -n 's/^APP_DOMAIN=//p' .env)"
sudo certbot --nginx -d "$APP_DOMAIN"
```

For later releases, push to `main`, then run this on the droplet:

```bash
cd /home/deployuser/apps/team-draw
./deploy/deploy.sh
```

Back up the SQLite database file separately from the code. Saved draws contain names and are viewable by anyone with their unlisted share link.
