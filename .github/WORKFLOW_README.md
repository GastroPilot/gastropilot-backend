# 🚀 CI/CD Setup - Backend

Dieses Verzeichnis enthält GitHub Actions Workflows für automatisches Deployment des Backends in verschiedene Umgebungen.

## 📋 Übersicht

Die Workflows deployen automatisch bei Push auf die entsprechenden Branches:

- **Production**: `main` oder `master` → Port 8000
- **Staging**: `staging` → Port 8001
- **Demo**: `demo` → Port 8002
- **Test**: `test` → Port 8003

## 🔧 Konfiguration

### 1. GitHub Secrets und Environments einrichten

#### Repository Secrets (einmalig für alle Environments)

Gehe zu deinem GitHub Repository → Settings → Secrets and variables → Actions

Füge folgende Repository Secrets hinzu (diese gelten für alle Environments):

```
SSH_PRIVATE_KEY                 # SSH Private Key für Server
SSH_HOST                        # Server-Hostname oder IP (z.B. example.com)
SSH_USER                        # SSH Benutzername (z.B. deploy)
SLACK_WEBHOOK_URL               # Slack Webhook URL für Benachrichtigungen (optional)
```

#### Environment Secrets (pro Environment unterschiedlich)

Gehe zu deinem GitHub Repository → Settings → Environments

Erstelle für jede Umgebung ein Environment:
- `production`
- `staging`
- `demo`
- `test`

Für jedes Environment füge folgende Secrets hinzu:

```
BACKEND_ENV                     # Komplette .env-Datei für das Backend
DEPLOY_PATH                     # Deployment-Pfad (optional, Standard: /opt/gastropilot/app/{environment})
HEALTH_URL                      # Health Check URL (optional, Standard: http://localhost:{port}/health)
```

**Wichtig**: 
- SSH-Secrets (`SSH_PRIVATE_KEY`, `SSH_HOST`, `SSH_USER`) sind Repository-Secrets und gelten für alle Environments
- Environment-spezifische Secrets (`BACKEND_ENV`, `DEPLOY_PATH`, `HEALTH_URL`) werden automatisch aus dem Environment-Kontext geladen
- Du musst die Environment-Secrets in jedem Environment separat konfigurieren, nicht mit Environment-Präfixen wie `BACKEND_ENV_PRODUCTION`

### 2. Slack Webhook einrichten (optional)

Um Benachrichtigungen in Slack zu erhalten, erstelle einen Incoming Webhook:

1. Gehe zu deinem Slack Workspace → Apps → Incoming Webhooks
2. Klicke auf "Add to Slack"
3. Wähle den Kanal aus, in dem die Benachrichtigungen erscheinen sollen
4. Kopiere die Webhook URL
5. Füge sie als Repository Secret `SLACK_WEBHOOK_URL` hinzu

Die Benachrichtigungen werden automatisch bei jedem Deployment (Erfolg oder Fehler) gesendet.

### 3. SSH Key generieren

```bash
# Auf deinem lokalen Rechner
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_actions_deploy

# Öffentlichen Schlüssel auf Server kopieren
ssh-copy-id -i ~/.ssh/github_actions_deploy.pub user@server

# Privaten Schlüssel für GitHub Secrets kopieren
cat ~/.ssh/github_actions_deploy
```

**Wichtig**: Der private Schlüssel muss komplett kopiert werden (inkl. `-----BEGIN` und `-----END` Zeilen).

### 4. Server-Vorbereitung

Auf dem Server müssen folgende Tools installiert sein:

```bash
# Python 3.11+
python3 --version

# screen (für Session-Management)
sudo apt-get install screen  # Debian/Ubuntu
# oder
sudo yum install screen      # CentOS/RHEL

# curl (für Health Checks)
curl --version
```

### 5. Deployment-Verzeichnis erstellen

```bash
# Beispiel für Production
sudo mkdir -p /opt/gastropilot/app
sudo chown -R $USER:$USER /opt/gastropilot/app

# Für andere Umgebungen entsprechend anpassen
```

## 🔄 Workflow-Ablauf

1. **Checkout**: Code wird aus dem Repository gecheckt
2. **Build**: Python-Dependencies werden installiert
3. **Package**: Deployment-Paket wird erstellt
4. **Deploy**: 
   - Paket wird per SSH auf Server hochgeladen
   - Alte Version wird durch neue ersetzt
   - Virtual Environment wird aktualisiert
   - Screen-Session wird gestoppt und neu gestartet
5. **Health Check**: Prüft ob der Service läuft

## 📊 Screen-Sessions

Jede Umgebung läuft in einer eigenen Screen-Session:

- Production: `app-production`
- Staging: `app-staging`
- Demo: `app-demo`
- Test: `app-test`

### Screen-Session verwalten

```bash
# Session anzeigen/verbinden
screen -r app-prod

# Session detachen (Service läuft weiter)
# Drücke: Ctrl+A dann D

# Alle Sessions anzeigen
screen -ls

# Session beenden
screen -S app-prod -X quit
```

## 🐛 Troubleshooting

### Problem: SSH-Verbindung schlägt fehl

- Prüfe ob der SSH-Key korrekt in GitHub Secrets eingetragen ist
- Prüfe ob der öffentliche Key auf dem Server installiert ist
- Teste SSH-Verbindung manuell: `ssh -i ~/.ssh/key user@host`

### Problem: Screen-Session startet nicht

- Prüfe ob `screen` installiert ist: `which screen`
- Prüfe Logs in der Screen-Session: `screen -r <session-name>`
- Prüfe ob Port bereits belegt ist: `netstat -tulpn | grep 8001`

### Problem: Health Check schlägt fehl

- Prüfe ob der Service läuft: `screen -ls`
- Prüfe ob der Port erreichbar ist: `curl http://localhost:8001/health`
- Prüfe Logs in der Screen-Session

### Problem: Dependencies werden nicht installiert

- Prüfe ob `requirements.txt` im Repository vorhanden ist
- Prüfe ob Python 3.11+ installiert ist
- Prüfe ob Virtual Environment erstellt werden kann

## 🔒 Sicherheit

- **Niemals** SSH-Keys im Repository committen
- Verwende separate SSH-Keys für jede Umgebung
- Beschränke SSH-Zugriff auf notwendige Benutzer
- Regelmäßig SSH-Keys rotieren
- Nutze SSH-Keys mit Passphrase für zusätzliche Sicherheit

## 📝 Anpassungen

### Ports ändern

Bearbeite die entsprechenden Workflow-Dateien und ändere den Port in der `uvicorn`-Zeile:

```yaml
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### Deployment-Pfad ändern

Setze das Secret `DEPLOY_PATH_<ENVIRONMENT>` in GitHub oder ändere den Standardwert im Workflow.

### Zusätzliche Schritte hinzufügen

Füge weitere Steps vor oder nach dem Deploy-Step hinzu:

```yaml
- name: Custom Step
  run: |
    # Deine Befehle hier
```

## 📚 Weitere Ressourcen

- [GitHub Actions Dokumentation](https://docs.github.com/en/actions)
- [SSH Agent Setup](https://github.com/webfactory/ssh-agent)
- [Screen Dokumentation](https://www.gnu.org/software/screen/)

