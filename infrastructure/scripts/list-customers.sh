#!/bin/bash
# =============================================================================
# List all Gastropilot customer instances
# =============================================================================

BASE_DIR="/opt/gastropilot"
CUSTOMERS_DIR="${BASE_DIR}/customers"
PORTS_FILE="${BASE_DIR}/.port-registry"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=== Gastropilot Customer Instances ==="
echo ""

if [ ! -d "$CUSTOMERS_DIR" ]; then
    echo "No customers found."
    exit 0
fi

printf "%-20s %-10s %-8s %-8s %-8s %-10s\n" "CUSTOMER" "STATUS" "FE-PORT" "BE-PORT" "DB-PORT" "CONTAINERS"
printf "%-20s %-10s %-8s %-8s %-8s %-10s\n" "--------" "------" "-------" "-------" "-------" "----------"

for customer_dir in "$CUSTOMERS_DIR"/*; do
    if [ -d "$customer_dir" ]; then
        customer_name=$(basename "$customer_dir")

        # Get ports from registry
        if [ -f "$PORTS_FILE" ]; then
            ports=$(grep "^${customer_name}:" "$PORTS_FILE" 2>/dev/null || echo "")
            if [ -n "$ports" ]; then
                fe_port=$(echo "$ports" | cut -d: -f2)
                be_port=$(echo "$ports" | cut -d: -f3)
                db_port=$(echo "$ports" | cut -d: -f4)
            else
                fe_port="-"
                be_port="-"
                db_port="-"
            fi
        else
            fe_port="-"
            be_port="-"
            db_port="-"
        fi

        # Check container status
        cd "$customer_dir"
        if [ -f "docker-compose.yml" ]; then
            running=$(docker compose ps --format "{{.State}}" 2>/dev/null | grep -c "running" || echo "0")
            total=$(docker compose ps --format "{{.State}}" 2>/dev/null | wc -l | tr -d ' ' || echo "0")

            if [ "$running" -eq "$total" ] && [ "$total" -gt 0 ]; then
                status="${GREEN}running${NC}"
            elif [ "$running" -gt 0 ]; then
                status="${YELLOW}partial${NC}"
            else
                status="${RED}stopped${NC}"
            fi
            containers="${running}/${total}"
        else
            status="${RED}no-config${NC}"
            containers="-"
        fi

        printf "%-20s ${status}%-10s %-8s %-8s %-8s %-10s\n" "$customer_name" "" "$fe_port" "$be_port" "$db_port" "$containers"
    fi
done

echo ""
echo "Total customers: $(ls -1 "$CUSTOMERS_DIR" 2>/dev/null | wc -l | tr -d ' ')"
