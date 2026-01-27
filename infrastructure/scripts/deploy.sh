#!/bin/bash
# =============================================================================
# Gastropilot Deployment Script
# Usage: ./deploy.sh <environment> [image-tag]
# Example: ./deploy.sh staging main
# =============================================================================

set -e

ENVIRONMENT=${1:-staging}
IMAGE_TAG=${2:-main}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Deploying Gastropilot to ${ENVIRONMENT} ==="

# Validate environment
if [[ ! "$ENVIRONMENT" =~ ^(staging|demo|production)$ ]]; then
    echo "Error: Invalid environment. Use: staging, demo, or production"
    exit 1
fi

# Load environment config
ENV_FILE="${INFRA_DIR}/configs/${ENVIRONMENT}.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "Error: Environment file not found: ${ENV_FILE}"
    exit 1
fi

# Export environment variables
set -a
source "$ENV_FILE"
set +a

# Login to GitHub Container Registry
echo "Logging in to GitHub Container Registry..."
echo "${GITHUB_TOKEN}" | docker login ghcr.io -u "${GITHUB_ACTOR}" --password-stdin

# Pull latest images
echo "Pulling latest images..."
docker pull ghcr.io/duhrkah/gastropilot-frontend:${IMAGE_TAG}
docker pull ghcr.io/duhrkah/gastropilot-backend:${IMAGE_TAG}

# Deploy stack
echo "Deploying stack..."
docker stack deploy \
    -c "${INFRA_DIR}/stacks/gastropilot-stack.yml" \
    --with-registry-auth \
    "gastropilot-${ENVIRONMENT}"

# Wait for services to be ready
echo "Waiting for services to be ready..."
sleep 10

# Check service status
echo "Service status:"
docker stack services "gastropilot-${ENVIRONMENT}"

# Health check
echo ""
echo "Running health checks..."

FRONTEND_URL="https://${FRONTEND_DOMAIN}"
BACKEND_URL="https://${BACKEND_DOMAIN}/health"

for i in {1..10}; do
    echo "Attempt $i/10..."

    # Check backend health
    if curl -sf "${BACKEND_URL}" > /dev/null 2>&1; then
        echo "Backend health check passed!"
        BACKEND_OK=true
    else
        BACKEND_OK=false
    fi

    # Check frontend health
    if curl -sf "${FRONTEND_URL}" > /dev/null 2>&1; then
        echo "Frontend health check passed!"
        FRONTEND_OK=true
    else
        FRONTEND_OK=false
    fi

    if [ "$BACKEND_OK" = true ] && [ "$FRONTEND_OK" = true ]; then
        echo ""
        echo "=== Deployment successful! ==="
        echo "Frontend: ${FRONTEND_URL}"
        echo "Backend:  https://${BACKEND_DOMAIN}"
        exit 0
    fi

    sleep 5
done

echo ""
echo "=== Health checks failed ==="
echo "Check logs with: docker service logs gastropilot-${ENVIRONMENT}_frontend"
echo "                 docker service logs gastropilot-${ENVIRONMENT}_backend"
exit 1
