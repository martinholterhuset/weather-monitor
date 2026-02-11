# Prosjektstruktur

```
weather-monitor/
├── .github/
│   └── workflows/
│       └── weather-monitor.yml    # GitHub Actions workflow
├── .gitignore                     # Git ignore-fil
├── weather_monitor.py             # Hovedscript
├── requirements.txt               # Python-avhengigheter
├── README.md                      # Hovedguide
├── GITHUB_ACTIONS_SETUP.md        # GitHub Actions oppsett (anbefalt)
├── SYSTEMD_SETUP.md               # Systemd oppsett (Linux)
└── .env.example                   # Eksempel på miljøvariabler
```

## Filer du trenger å redigere

### 1. weather_monitor.py
Rediger `LOCATIONS`-listen for å legge til dine egne lokasjoner:

```python
LOCATIONS = [
    {"name": "Oslo", "lat": 59.9139, "lon": 10.7522},
    {"name": "Bergen", "lat": 60.3913, "lon": 5.3221},
    {"name": "Trondheim", "lat": 63.4305, "lon": 10.3951},
    # Legg til dine egne lokasjoner her
]
```

### 2. GitHub Secrets (hvis du bruker GitHub Actions)
Legg til i repository settings:
- `SLACK_WEBHOOK_URL` - Din Slack webhook URL
- `USER_EMAIL` - Din epostadresse

### 3. .env fil (hvis du kjører lokalt)
Kopier `.env.example` til `.env` og fyll inn:
```bash
cp .env.example .env
# Rediger .env med dine verdier
```

## Deployment-alternativer

| Metode | Fordeler | Ulemper |
|--------|----------|---------|
| **GitHub Actions** ✅ | Gratis, ingen server, enkel oppsett | Krever GitHub repo |
| **Cron (Linux/Mac)** | Full kontroll, lokal kjøring | Krever server som alltid er på |
| **Systemd (Linux)** | Robust, god logging | Mer kompleks oppsett |
| **Task Scheduler (Windows)** | Enkel på Windows | Krever PC som alltid er på |

## Quick Start

### Med GitHub Actions (anbefalt)
```bash
# 1. Opprett repository
git init
git add .
git commit -m "Initial commit"

# 2. Push til GitHub
git remote add origin https://github.com/DIN-BRUKER/weather-monitor.git
git push -u origin main

# 3. Legg til secrets i GitHub
# Se GITHUB_ACTIONS_SETUP.md
```

### Lokal testing
```bash
# 1. Installer avhengigheter
pip install -r requirements.txt

# 2. Sett miljøvariabler
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
export USER_EMAIL="din@epost.no"

# 3. Kjør
python weather_monitor.py
```
