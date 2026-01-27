#!/bin/bash
# =============================================================================
# Update all Gastropilot customer instances
# Pulls latest images and restarts all services
# =============================================================================

BASE_DIR="/opt/gastropilot"
CUSTOMERS_DIR="${BASE_DIR}/customers"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=== Updating All Gastropilot Instances ==="
echo ""

# Login to GHCR first
if [ -n "$GHCR_TOKEN" ]; then
    echo "Logging in to GitHub Container Registry..."
    echo "$GHCR_TOKEN" | docker login ghcr.io -u duhrkah --password-stdin
fi

# Update staging first
if [ -d "${BASE_DIR}/staging" ]; then
    echo -e "${YELLOW}Updating: staging${NC}"
    cd "${BASE_DIR}/staging"
    docker compose pull
    docker compose up -d
    echo -e "${GREEN}✓ staging updated${NC}"
    echo ""
fi

# Update all customers
if [ -d "$CUSTOMERS_DIR" ]; then
    for customer_dir in "$CUSTOMERS_DIR"/*; do
        if [ -d "$customer_dir" ] && [ -f "$customer_dir/docker-compose.yml" ]; then
            customer_name=$(basename "$customer_dir")
            echo -e "${YELLOW}Updating: ${customer_name}${NC}"
            cd "$customer_dir"
            docker compose pull
            docker compose up -d
            echo -e "${GREEN}✓ ${customer_name} updated${NC}"
            echo ""
        fi
    done
fi

echo "=== Update Complete ==="
