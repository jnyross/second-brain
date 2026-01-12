#!/bin/bash
# =============================================================================
# Health Check Script for Second Brain
# =============================================================================
# Verifies container is healthy after deployment.
# Used by CD pipeline and manual health verification.
#
# Usage:
#   ./health-check.sh              # Check with defaults (10 retries, 3s interval)
#   ./health-check.sh --quick      # Quick check (3 retries, 1s interval)
#   ./health-check.sh --retries 5  # Custom retry count
#
# Exit codes:
#   0 - Container is healthy
#   1 - Health check failed
#   2 - Invalid arguments
#
# Requirements:
#   - Docker installed and running
#   - Container named 'second-brain' running
# =============================================================================

set -euo pipefail

# Configuration (can be overridden by environment or arguments)
MAX_RETRIES="${HEALTH_CHECK_RETRIES:-10}"
RETRY_INTERVAL="${HEALTH_CHECK_INTERVAL:-3}"
CONTAINER_NAME="${CONTAINER_NAME:-second-brain}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --quick)
            MAX_RETRIES=3
            RETRY_INTERVAL=1
            shift
            ;;
        --retries)
            MAX_RETRIES="$2"
            shift 2
            ;;
        --interval)
            RETRY_INTERVAL="$2"
            shift 2
            ;;
        --container)
            CONTAINER_NAME="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --quick            Quick check (3 retries, 1s interval)"
            echo "  --retries N        Number of retries (default: 10)"
            echo "  --interval N       Seconds between retries (default: 3)"
            echo "  --container NAME   Container name (default: second-brain)"
            echo "  --help             Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 2
            ;;
    esac
done

# Validate configuration
if ! [[ "$MAX_RETRIES" =~ ^[0-9]+$ ]] || [ "$MAX_RETRIES" -lt 1 ]; then
    echo -e "${RED}Error: --retries must be a positive integer${NC}"
    exit 2
fi

if ! [[ "$RETRY_INTERVAL" =~ ^[0-9]+$ ]] || [ "$RETRY_INTERVAL" -lt 1 ]; then
    echo -e "${RED}Error: --interval must be a positive integer${NC}"
    exit 2
fi

# Check if docker is available
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: docker command not found${NC}"
    exit 1
fi

# Check if container exists
if ! docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${RED}Error: Container '${CONTAINER_NAME}' not found${NC}"
    exit 1
fi

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${RED}Error: Container '${CONTAINER_NAME}' is not running${NC}"
    exit 1
fi

echo "Checking health of container '${CONTAINER_NAME}'..."
echo "Max retries: ${MAX_RETRIES}, Interval: ${RETRY_INTERVAL}s"

# Health check loop
for i in $(seq 1 "$MAX_RETRIES"); do
    # Try to execute health check command inside container
    if docker exec "$CONTAINER_NAME" python -c "import assistant; print('ok')" 2>/dev/null; then
        echo -e "${GREEN}✓ Health check passed${NC}"

        # Additional checks for comprehensive health verification
        echo "Running additional verification..."

        # Check if the assistant CLI works
        if docker exec "$CONTAINER_NAME" python -m assistant check 2>/dev/null; then
            echo -e "${GREEN}✓ CLI check passed${NC}"
        else
            echo -e "${YELLOW}! CLI check warning (non-critical)${NC}"
        fi

        # Get container health status from Docker
        HEALTH_STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "no-healthcheck")
        if [ "$HEALTH_STATUS" = "healthy" ]; then
            echo -e "${GREEN}✓ Docker health status: healthy${NC}"
        elif [ "$HEALTH_STATUS" = "no-healthcheck" ]; then
            echo -e "${YELLOW}! No Docker healthcheck configured${NC}"
        else
            echo -e "${YELLOW}! Docker health status: ${HEALTH_STATUS}${NC}"
        fi

        echo ""
        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}  Health Check: PASSED${NC}"
        echo -e "${GREEN}========================================${NC}"
        exit 0
    fi

    echo -e "${YELLOW}Waiting for container... ($i/$MAX_RETRIES)${NC}"
    sleep "$RETRY_INTERVAL"
done

# Health check failed after all retries
echo ""
echo -e "${RED}========================================${NC}"
echo -e "${RED}  Health Check: FAILED${NC}"
echo -e "${RED}========================================${NC}"
echo ""
echo "Troubleshooting steps:"
echo "  1. Check container logs: docker logs $CONTAINER_NAME"
echo "  2. Check container status: docker inspect $CONTAINER_NAME"
echo "  3. Check environment file: cat /etc/second-brain.env"
echo "  4. Verify Notion API connectivity from host"
exit 1
