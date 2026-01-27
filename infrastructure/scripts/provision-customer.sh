#!/bin/bash
# =============================================================================
# Gastropilot Customer Provisioning Script
# Usage: ./provision-customer.sh <customer-name> [environment]
# Example: ./provision-customer.sh restaurant-muster production
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
BASE_DIR="/opt/gastropilot"
TEMPLATE_DIR="$(dirname "$0")/../templates"
GHCR_USER="duhrkah"

# Parse arguments
CUSTOMER_NAME="$1"
ENVIRONMENT="${2:-production}"

if [ -z "$CUSTOMER_NAME" ]; then
    echo -e "${RED}Error: Customer name required${NC}"
    echo "Usage: $0 <customer-name> [environment]"
    echo "Example: $0 restaurant-muster production"
    exit 1
fi

# Validate customer name (lowercase, alphanumeric, hyphens only)
if ! [[ "$CUSTOMER_NAME" =~ ^[a-z0-9-]+$ ]]; then
    echo -e "${RED}Error: Customer name must be lowercase alphanumeric with hyphens only${NC}"
    exit 1
fi

# Set ports based on existing customers
CUSTOMER_DIR="${BASE_DIR}/customers/${CUSTOMER_NAME}"
PORTS_FILE="${BASE_DIR}/.port-registry"

# Initialize port registry if not exists
if [ ! -f "$PORTS_FILE" ]; then
    echo "# Port Registry - DO NOT EDIT MANUALLY" > "$PORTS_FILE"
    echo "# Format: customer_name:frontend_port:backend_port:db_port" >> "$PORTS_FILE"
    # Reserve staging ports
    echo "staging:3003:8003:5433" >> "$PORTS_FILE"
fi

# Get next available ports
get_next_ports() {
    local last_frontend=$(grep -v "^#" "$PORTS_FILE" | cut -d: -f2 | sort -n | tail -1)
    local last_backend=$(grep -v "^#" "$PORTS_FILE" | cut -d: -f3 | sort -n | tail -1)
    local last_db=$(grep -v "^#" "$PORTS_FILE" | cut -d: -f4 | sort -n | tail -1)

    # Default starting ports if registry is empty
    [ -z "$last_frontend" ] && last_frontend=3009
    [ -z "$last_backend" ] && last_backend=8009
    [ -z "$last_db" ] && last_db=5439

    FRONTEND_PORT=$((last_frontend + 1))
    BACKEND_PORT=$((last_backend + 1))
    DB_PORT=$((last_db + 1))
}

# Check if customer already exists
if [ -d "$CUSTOMER_DIR" ]; then
    echo -e "${YELLOW}Warning: Customer ${CUSTOMER_NAME} already exists${NC}"
    read -p "Do you want to update the configuration? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
    # Get existing ports
    existing=$(grep "^${CUSTOMER_NAME}:" "$PORTS_FILE" || true)
    if [ -n "$existing" ]; then
        FRONTEND_PORT=$(echo "$existing" | cut -d: -f2)
        BACKEND_PORT=$(echo "$existing" | cut -d: -f3)
        DB_PORT=$(echo "$existing" | cut -d: -f4)
    else
        get_next_ports
    fi
else
    get_next_ports
fi

echo -e "${GREEN}=== Provisioning Customer: ${CUSTOMER_NAME} ===${NC}"
echo "Environment: ${ENVIRONMENT}"
echo "Directory: ${CUSTOMER_DIR}"
echo "Ports: Frontend=${FRONTEND_PORT}, Backend=${BACKEND_PORT}, DB=${DB_PORT}"
echo ""

# Generate secure passwords
generate_password() {
    openssl rand -base64 32 | tr -d '/+=' | head -c 32
}

DB_PASSWORD=$(generate_password)
JWT_SECRET=$(generate_password)
SECRET_KEY=$(generate_password)

# Create customer directory
mkdir -p "${CUSTOMER_DIR}"

# Create docker-compose.yml
cat > "${CUSTOMER_DIR}/docker-compose.yml" << EOF
# =============================================================================
# Gastropilot - ${CUSTOMER_NAME}
# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# =============================================================================

version: "3.8"

services:
  frontend:
    image: ghcr.io/${GHCR_USER}/gastropilot-frontend:main
    container_name: gp-${CUSTOMER_NAME}-frontend
    restart: unless-stopped
    ports:
      - "${FRONTEND_PORT}:3000"
    environment:
      - NODE_ENV=production
      - NEXT_PUBLIC_API_URL=\${API_URL}
    networks:
      - gp-${CUSTOMER_NAME}
    depends_on:
      - backend
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:3000"]
      interval: 30s
      timeout: 10s
      retries: 3

  backend:
    image: ghcr.io/${GHCR_USER}/gastropilot-backend:main
    container_name: gp-${CUSTOMER_NAME}-backend
    restart: unless-stopped
    ports:
      - "${BACKEND_PORT}:8000"
    environment:
      - ENV=${ENVIRONMENT}
      - DATABASE_URL=postgresql://gastropilot:\${DB_PASSWORD}@postgres:5432/gastropilot?sslmode=disable
      - JWT_SECRET=\${JWT_SECRET}
      - SECRET_KEY=\${SECRET_KEY}
      - CORS_ORIGINS=\${CORS_ORIGINS}
    networks:
      - gp-${CUSTOMER_NAME}
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  postgres:
    image: postgres:16-alpine
    container_name: gp-${CUSTOMER_NAME}-postgres
    restart: unless-stopped
    ports:
      - "${DB_PORT}:5432"
    environment:
      - POSTGRES_USER=gastropilot
      - POSTGRES_PASSWORD=\${DB_PASSWORD}
      - POSTGRES_DB=gastropilot
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - gp-${CUSTOMER_NAME}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U gastropilot -d gastropilot"]
      interval: 10s
      timeout: 5s
      retries: 5

networks:
  gp-${CUSTOMER_NAME}:
    driver: bridge

volumes:
  postgres-data:
EOF

# Create .env file
cat > "${CUSTOMER_DIR}/.env" << EOF
# Gastropilot - ${CUSTOMER_NAME}
# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# DO NOT COMMIT THIS FILE

# Database
DB_PASSWORD=${DB_PASSWORD}

# Security
JWT_SECRET=${JWT_SECRET}
SECRET_KEY=${SECRET_KEY}

# URLs (update with actual domain)
API_URL=https://api-${CUSTOMER_NAME}.gpilot.app
CORS_ORIGINS=https://${CUSTOMER_NAME}.gpilot.app
EOF

chmod 600 "${CUSTOMER_DIR}/.env"

# Register ports
if ! grep -q "^${CUSTOMER_NAME}:" "$PORTS_FILE" 2>/dev/null; then
    echo "${CUSTOMER_NAME}:${FRONTEND_PORT}:${BACKEND_PORT}:${DB_PORT}" >> "$PORTS_FILE"
fi

# Create management scripts
cat > "${CUSTOMER_DIR}/start.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
docker compose up -d
EOF
chmod +x "${CUSTOMER_DIR}/start.sh"

cat > "${CUSTOMER_DIR}/stop.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
docker compose down
EOF
chmod +x "${CUSTOMER_DIR}/stop.sh"

cat > "${CUSTOMER_DIR}/logs.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
docker compose logs -f "${1:-}"
EOF
chmod +x "${CUSTOMER_DIR}/logs.sh"

cat > "${CUSTOMER_DIR}/update.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
echo "Pulling latest images..."
docker compose pull
echo "Restarting services..."
docker compose up -d
echo "Done!"
EOF
chmod +x "${CUSTOMER_DIR}/update.sh"

cat > "${CUSTOMER_DIR}/backup-db.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="backup_${TIMESTAMP}.sql"
source .env
docker compose exec -T postgres pg_dump -U gastropilot gastropilot > "${BACKUP_FILE}"
gzip "${BACKUP_FILE}"
echo "Backup created: ${BACKUP_FILE}.gz"
EOF
chmod +x "${CUSTOMER_DIR}/backup-db.sh"

echo ""
echo -e "${GREEN}=== Provisioning Complete ===${NC}"
echo ""
echo "Customer directory: ${CUSTOMER_DIR}"
echo ""
echo "Credentials (SAVE THESE!):"
echo "  DB Password: ${DB_PASSWORD}"
echo "  JWT Secret:  ${JWT_SECRET}"
echo "  Secret Key:  ${SECRET_KEY}"
echo ""
echo "Ports:"
echo "  Frontend: ${FRONTEND_PORT}"
echo "  Backend:  ${BACKEND_PORT}"
echo "  Database: ${DB_PORT}"
echo ""
echo "Next steps:"
echo "  1. Update .env with correct domain URLs"
echo "  2. Login to GHCR: echo \$GHCR_TOKEN | docker login ghcr.io -u ${GHCR_USER} --password-stdin"
echo "  3. Start services: cd ${CUSTOMER_DIR} && ./start.sh"
echo "  4. Configure reverse proxy (Nginx/Traefik) for domains"
echo ""
