#!/bin/bash
# =============================================================================
# Docker Swarm Worker Join Script
# Run this ONLY on Node 2 (91.99.232.51)
# =============================================================================

set -e

NODE1_IP="46.225.31.48"

echo "=== Joining Docker Swarm as Worker ==="

# Check if token is provided as argument
if [ -z "$1" ]; then
    echo "Usage: $0 <worker-token>"
    echo ""
    echo "Get the token from Node 1 by running:"
    echo "  docker swarm join-token worker -q"
    exit 1
fi

WORKER_TOKEN="$1"

# Join the swarm
docker swarm join --token ${WORKER_TOKEN} ${NODE1_IP}:2377

echo "=== Successfully joined swarm as worker ==="

# Create directories for persistent data (same structure as manager)
mkdir -p /opt/gastropilot/{staging,demo,production}
mkdir -p /opt/gastropilot/data/{postgres,redis}
mkdir -p /opt/gastropilot/logs

echo "=== Created directories ==="

# Verify join
docker info | grep -A 5 "Swarm:"
