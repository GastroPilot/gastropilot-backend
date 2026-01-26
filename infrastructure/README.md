# Gastropilot Infrastructure

## Server Overview

| Node | IP | Role |
|------|-----|------|
| Node 1 | 46.225.31.48 | Swarm Manager |
| Node 2 | 91.99.232.51 | Swarm Worker |

## Initial Setup

### Step 1: Install Docker (beide Nodes)

```bash
# SSH zu jedem Node
ssh root@46.225.31.48
ssh root@91.99.232.51

# Docker installieren (auf beiden)
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker
```

### Step 2: Swarm initialisieren (nur Node 1)

```bash
ssh root@46.225.31.48

# Swarm initialisieren
docker swarm init --advertise-addr 46.225.31.48

# Worker Token speichern (wird angezeigt)
# Oder später abrufen:
docker swarm join-token worker -q
```

### Step 3: Worker joinen (nur Node 2)

```bash
ssh root@91.99.232.51

# Mit dem Token von Step 2
docker swarm join --token <WORKER_TOKEN> 46.225.31.48:2377
```

### Step 4: Verzeichnisse erstellen (Node 1)

```bash
ssh root@46.225.31.48

mkdir -p /opt/gastropilot/{staging,demo,production}
```

### Step 5: Docker Compose File kopieren

```bash
# Von deinem lokalen Rechner:
scp infrastructure/stacks/docker-compose.staging.yml root@46.225.31.48:/opt/gastropilot/staging/docker-compose.yml
```

### Step 6: Environment Variables setzen

```bash
ssh root@46.225.31.48
cd /opt/gastropilot/staging

# .env Datei erstellen
cat > .env << 'EOF'
DB_PASSWORD=dein_sicheres_passwort
JWT_SECRET=dein_jwt_secret
SECRET_KEY=dein_secret_key
EOF

chmod 600 .env
```

### Step 7: Services starten

```bash
cd /opt/gastropilot/staging

# GitHub Container Registry Login
echo "YOUR_GITHUB_PAT" | docker login ghcr.io -u duhrkah --password-stdin

# Services starten
docker compose up -d
```

## GitHub Secrets konfigurieren

In beiden Repositories (frontend & backend) unter Settings → Secrets and variables → Actions:

| Secret | Wert |
|--------|------|
| `SSH_USER` | `root` (oder dein SSH User) |
| `SSH_PRIVATE_KEY` | SSH Private Key (siehe unten) |
| `GHCR_TOKEN` | GitHub Personal Access Token mit `write:packages` |

### SSH Key generieren

```bash
# Lokal einen neuen Key generieren
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/gastropilot_deploy

# Public Key auf Server kopieren
ssh-copy-id -i ~/.ssh/gastropilot_deploy.pub root@46.225.31.48
ssh-copy-id -i ~/.ssh/gastropilot_deploy.pub root@91.99.232.51

# Private Key als GitHub Secret verwenden
cat ~/.ssh/gastropilot_deploy
```

## Port Mapping

| Environment | Frontend | Backend | DB |
|-------------|----------|---------|-----|
| Staging | 3003 | 8003 | 5433 |
| Demo | 3001 | 8001 | 5431 |
| Production | 3000 | 8000 | 5432 |

## Nützliche Befehle

```bash
# Service Status
docker compose ps

# Logs anzeigen
docker compose logs -f backend
docker compose logs -f frontend

# Service neustarten
docker compose restart backend

# Alles stoppen
docker compose down

# Images aktualisieren
docker compose pull
docker compose up -d
```
