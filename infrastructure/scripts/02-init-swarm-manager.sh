#!/bin/bash
# =============================================================================
# Docker Swarm Manager Initialization
# Run this ONLY on Node 1 (46.225.31.48)
# =============================================================================

set -e

NODE1_IP="46.225.31.48"
NODE2_IP="91.99.232.51"

echo "=== Initializing Docker Swarm on Manager Node ==="

# Initialize Swarm (use public IP for advertise)
docker swarm init --advertise-addr ${NODE1_IP}

# Get worker join token
WORKER_TOKEN=$(docker swarm join-token worker -q)

echo ""
echo "=== Swarm initialized! ==="
echo ""
echo "Run the following command on Node 2 (${NODE2_IP}):"
echo ""
echo "docker swarm join --token ${WORKER_TOKEN} ${NODE1_IP}:2377"
echo ""

# Create overlay network for Gastropilot
docker network create --driver overlay --attachable gastropilot-network || true

echo "=== Created overlay network: gastropilot-network ==="

# Create directories for persistent data
mkdir -p /opt/gastropilot/{staging,demo,production}
mkdir -p /opt/gastropilot/data/{postgres,redis}
mkdir -p /opt/gastropilot/logs
mkdir -p /opt/gastropilot/backups

echo "=== Created directories ==="
echo "  /opt/gastropilot/staging"
echo "  /opt/gastropilot/demo"
echo "  /opt/gastropilot/production"
echo "  /opt/gastropilot/data"
echo "  /opt/gastropilot/logs"
echo "  /opt/gastropilot/backups"

# Save worker token to file for reference
echo "${WORKER_TOKEN}" > /opt/gastropilot/worker-token.txt
chmod 600 /opt/gastropilot/worker-token.txt

echo ""
echo "=== Manager setup complete! ==="
echo "Worker token saved to: /opt/gastropilot/worker-token.txt"
