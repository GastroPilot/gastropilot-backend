# GastroPilot Backend

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-13+-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)

> FastAPI-basierte REST-API für das GastroPilot Restaurant Management System.

## Features

- **JWT Authentication** – Sichere Token-basierte Authentifizierung
- **Restaurant Management** – Locations, Bereiche, Tische
- **Reservierungssystem** – Intelligente Zeitslot- und Tischzuweisung
- **Bestellverwaltung** – Vollständiges Bestellsystem mit Statistik
- **KI-Integration** – OpenAI-gestützte Tischvorschläge
- **Multi-Channel** – WhatsApp-Bot und Web-Reservierungen
- **Benachrichtigungen** – E-Mail, SMS, WhatsApp via Twilio
- **Audit-Logging** – Vollständige Aktivitätsprotokolle

## Schnellstart

### Voraussetzungen

- Python 3.11+
- PostgreSQL 13+ oder SQLite

### Installation

```bash
# Virtual Environment erstellen
python -m venv venv
source venv/bin/activate  # Linux/macOS
# .\venv\Scripts\Activate.ps1  # Windows

# Dependencies installieren
pip install -r requirements.txt

# Environment konfigurieren
cp env.example .env

# Server starten
uvicorn app.main:app --reload --port 8001
```

### API-Dokumentation

Nach dem Start verfügbar unter:

- **Swagger UI:** http://localhost:8001/api/docs
- **ReDoc:** http://localhost:8001/api/redoc
- **Health Check:** http://localhost:8001/health

## Konfiguration

### Environment Variables

```env
# Core
ENV=development
DATABASE_URL=sqlite+aiosqlite:///./reservation_dev.db
JWT_SECRET=your-secret-key-min-32-characters

# CORS
CORS_ORIGINS=http://localhost:3001

# AI (optional)
AI_ENABLED=true
OPENAI_API_KEY=sk-...

# Twilio (optional)
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+49...
TWILIO_WHATSAPP_NUMBER=whatsapp:+49...

# Email (optional)
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
```

## API-Endpoints

### Authentifizierung

| Method | Endpoint | Beschreibung |
|--------|----------|--------------|
| POST | `/api/v1/auth/login` | Login mit Bedienernummer/PIN |
| POST | `/api/v1/auth/refresh` | Token erneuern |
| POST | `/api/v1/auth/logout` | Logout |

### Reservierungen

| Method | Endpoint | Beschreibung |
|--------|----------|--------------|
| GET | `/api/v1/reservations` | Alle Reservierungen |
| POST | `/api/v1/reservations` | Neue Reservierung |
| GET | `/api/v1/reservations/{id}` | Details |
| PUT | `/api/v1/reservations/{id}` | Aktualisieren |
| DELETE | `/api/v1/reservations/{id}` | Löschen |

### Öffentliche API (ohne Auth)

| Method | Endpoint | Beschreibung |
|--------|----------|--------------|
| GET | `/api/v1/public/restaurants/{slug}/info` | Restaurant-Info |
| GET | `/api/v1/public/restaurants/{slug}/availability` | Verfügbarkeit |
| POST | `/api/v1/public/restaurants/{slug}/reserve` | Reservierung erstellen |

### WhatsApp Webhook

| Method | Endpoint | Beschreibung |
|--------|----------|--------------|
| POST | `/api/v1/webhook/whatsapp/{slug}` | Twilio Webhook |

## Datenbank

### Migrationen

```bash
# Public Booking Felder hinzufügen
python scripts/migrate_public_booking.py
```

### Schema

Hauptmodelle: `Restaurant`, `Table`, `Reservation`, `Order`, `Guest`, `MenuItem`, `Operator`, `AuditLog`

## Deployment

### Mit Screen

```bash
screen -dmS gastropilot-backend \
  bash -c "source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8001"
```

### Mit Docker

```bash
docker build -t gastropilot-backend .
docker run -p 8001:8001 --env-file .env gastropilot-backend
```

### Mit systemd

```ini
[Unit]
Description=GastroPilot Backend
After=network.target

[Service]
User=deploy
WorkingDirectory=/opt/gastropilot/backend
ExecStart=/opt/gastropilot/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001
Restart=always

[Install]
WantedBy=multi-user.target
```

## Testing

```bash
# Unit Tests
pytest tests/

# Mit Coverage
pytest --cov=app tests/
```

## Troubleshooting

### Database Connection Error

```bash
# SQLite Rechte prüfen
ls -la *.db

# PostgreSQL Connection testen
psql $DATABASE_URL -c "SELECT 1"
```

### CORS Error

Prüfe `CORS_ORIGINS` in `.env` – muss Frontend-URL enthalten.

### Module not found

```bash
source venv/bin/activate
pip install -r requirements.txt
```

## Lizenz

[MIT](../LICENSE.md)
