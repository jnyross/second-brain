#!/bin/bash
# =============================================================================
# Rollback Script for Second Brain
# =============================================================================
# Reverts to the previous Docker image version when a deployment fails.
# Automatically finds the previous image tag and restarts the container.
#
# Usage:
#   ./rollback.sh              # Rollback to previous version
#   ./rollback.sh --list       # List available image versions
#   ./rollback.sh --to TAG     # Rollback to specific tag
#   ./rollback.sh --dry-run    # Show what would happen without executing
#
# Exit codes:
#   0 - Rollback successful
#   1 - Rollback failed
#   2 - Invalid arguments
#   3 - No previous image available
#
# Requirements:
#   - Docker installed and running
#   - GHCR image available locally or pullable
# =============================================================================

set -euo pipefail

# Configuration
CONTAINER_NAME="${CONTAINER_NAME:-second-brain}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/second-brain}"
# Repository name - defaults to johnross/personal-assistant but can be overridden
REPO="${GHCR_REPO:-johnross/personal-assistant}"
REGISTRY="ghcr.io"
IMAGE="${REGISTRY}/${REPO}"

# Script directory for health-check.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Mode flags
DRY_RUN=false
LIST_ONLY=false
TARGET_TAG=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --list)
            LIST_ONLY=true
            shift
            ;;
        --to)
            TARGET_TAG="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --container)
            CONTAINER_NAME="$2"
            shift 2
            ;;
        --compose-dir)
            COMPOSE_DIR="$2"
            shift 2
            ;;
        --repo)
            REPO="$2"
            IMAGE="${REGISTRY}/${REPO}"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Rollback the Second Brain container to a previous version."
            echo ""
            echo "Options:"
            echo "  --list             List available image versions"
            echo "  --to TAG           Rollback to specific tag (e.g., 'abc1234')"
            echo "  --dry-run          Show what would happen without executing"
            echo "  --container NAME   Container name (default: second-brain)"
            echo "  --compose-dir DIR  Docker compose directory (default: /opt/second-brain)"
            echo "  --repo REPO        GHCR repository (default: johnross/personal-assistant)"
            echo "  --help             Show this help message"
            echo ""
            echo "Exit codes:"
            echo "  0 - Rollback successful"
            echo "  1 - Rollback failed"
            echo "  2 - Invalid arguments"
            echo "  3 - No previous image available"
            echo ""
            echo "Examples:"
            echo "  ./rollback.sh              # Rollback to previous version"
            echo "  ./rollback.sh --list       # Show available versions"
            echo "  ./rollback.sh --to abc1234 # Rollback to specific commit"
            echo "  ./rollback.sh --dry-run    # Preview rollback"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 2
            ;;
    esac
done

# Check if docker is available
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: docker command not found${NC}"
    exit 1
fi

# Function to get available image tags (sorted by creation time, newest first)
get_available_tags() {
    # Get local images with our repository, sorted by creation time
    docker images "${IMAGE}" --format "{{.Tag}}\t{{.CreatedAt}}" 2>/dev/null | \
        grep -v "^<none>" | \
        sort -t$'\t' -k2 -r | \
        cut -f1
}

# Function to get the current running image tag
get_current_tag() {
    local current_image
    current_image=$(docker inspect --format='{{.Config.Image}}' "${CONTAINER_NAME}" 2>/dev/null || echo "")
    if [ -z "$current_image" ]; then
        echo ""
        return
    fi
    # Extract tag from image name (e.g., ghcr.io/repo:tag -> tag)
    echo "${current_image##*:}"
}

# Function to get the previous image tag (second in the sorted list, excluding 'latest')
get_previous_tag() {
    local current_tag="$1"
    local tags
    tags=$(get_available_tags)

    # Filter out 'latest' and current tag, get the first remaining
    echo "$tags" | grep -v "^latest$" | grep -v "^${current_tag}$" | head -1
}

# List available versions
if [ "$LIST_ONLY" = true ]; then
    echo "Available image versions for ${IMAGE}:"
    echo ""

    current_tag=$(get_current_tag)
    tags=$(get_available_tags)

    if [ -z "$tags" ]; then
        echo -e "${YELLOW}No local images found${NC}"
        echo ""
        echo "To pull images from registry:"
        echo "  docker pull ${IMAGE}:latest"
        exit 0
    fi

    while IFS= read -r tag; do
        if [ "$tag" = "$current_tag" ]; then
            echo -e "  ${GREEN}${tag}${NC} (current)"
        elif [ "$tag" = "latest" ]; then
            echo -e "  ${BLUE}${tag}${NC}"
        else
            echo "  ${tag}"
        fi
    done <<< "$tags"

    exit 0
fi

# Get current and target tags
echo "Preparing rollback for ${CONTAINER_NAME}..."
echo ""

current_tag=$(get_current_tag)
echo "Current image tag: ${current_tag:-<unknown>}"

if [ -n "$TARGET_TAG" ]; then
    # User specified a target tag
    previous_tag="$TARGET_TAG"
else
    # Find the previous tag automatically
    previous_tag=$(get_previous_tag "${current_tag}")
fi

if [ -z "$previous_tag" ]; then
    echo -e "${RED}Error: No previous image version available for rollback${NC}"
    echo ""
    echo "Available tags:"
    get_available_tags | while read -r tag; do echo "  $tag"; done
    echo ""
    echo "You can specify a tag with: ./rollback.sh --to <tag>"
    exit 3
fi

echo "Target rollback tag: ${previous_tag}"
echo ""

# Verify the target image exists
if ! docker image inspect "${IMAGE}:${previous_tag}" &>/dev/null; then
    echo -e "${YELLOW}Target image not found locally. Attempting to pull...${NC}"
    if [ "$DRY_RUN" = false ]; then
        if ! docker pull "${IMAGE}:${previous_tag}"; then
            echo -e "${RED}Error: Failed to pull ${IMAGE}:${previous_tag}${NC}"
            exit 1
        fi
    else
        echo "[DRY-RUN] Would pull: ${IMAGE}:${previous_tag}"
    fi
fi

# Perform rollback
echo "=========================================="
echo "  Rollback Plan"
echo "=========================================="
echo "  From: ${IMAGE}:${current_tag:-latest}"
echo "  To:   ${IMAGE}:${previous_tag}"
echo "=========================================="
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}[DRY-RUN] Would execute the following:${NC}"
    echo ""
    echo "1. Stop current container:"
    echo "   docker compose -f ${COMPOSE_DIR}/docker-compose.yml down"
    echo ""
    echo "2. Update docker-compose.yml image tag to: ${previous_tag}"
    echo "   (or set SECOND_BRAIN_IMAGE_TAG=${previous_tag})"
    echo ""
    echo "3. Start container with previous image:"
    echo "   docker compose -f ${COMPOSE_DIR}/docker-compose.yml up -d"
    echo ""
    echo "4. Run health check:"
    echo "   ${SCRIPT_DIR}/health-check.sh"
    echo ""
    echo -e "${GREEN}Dry run complete. No changes made.${NC}"
    exit 0
fi

# Stop current container
echo "Step 1: Stopping current container..."
if [ -f "${COMPOSE_DIR}/docker-compose.yml" ]; then
    docker compose -f "${COMPOSE_DIR}/docker-compose.yml" down || true
else
    docker stop "${CONTAINER_NAME}" 2>/dev/null || true
    docker rm "${CONTAINER_NAME}" 2>/dev/null || true
fi

# Start with previous image
echo "Step 2: Starting container with previous image..."

# Set the image tag via environment variable
export SECOND_BRAIN_IMAGE_TAG="${previous_tag}"

if [ -f "${COMPOSE_DIR}/docker-compose.yml" ]; then
    # Create a temporary override to use the specific tag
    OVERRIDE_FILE="${COMPOSE_DIR}/docker-compose.rollback.yml"
    cat > "$OVERRIDE_FILE" << EOF
services:
  second-brain:
    image: ${IMAGE}:${previous_tag}
EOF

    docker compose -f "${COMPOSE_DIR}/docker-compose.yml" -f "$OVERRIDE_FILE" up -d

    # Clean up override file
    rm -f "$OVERRIDE_FILE"
else
    # Fallback: run container directly
    docker run -d \
        --name "${CONTAINER_NAME}" \
        --restart unless-stopped \
        --env-file /etc/second-brain.env \
        -v /var/lib/second-brain/tokens:/var/lib/second-brain/tokens \
        -v /var/lib/second-brain/cache:/var/lib/second-brain/cache \
        -v /var/lib/second-brain/logs:/var/lib/second-brain/logs \
        -v /var/lib/second-brain/queue:/var/lib/second-brain/queue \
        "${IMAGE}:${previous_tag}"
fi

# Wait a moment for container to start
echo "Step 3: Waiting for container to start..."
sleep 3

# Run health check
echo "Step 4: Running health check..."
if [ -x "${SCRIPT_DIR}/health-check.sh" ]; then
    if "${SCRIPT_DIR}/health-check.sh" --retries 5 --interval 2; then
        HEALTH_OK=true
    else
        HEALTH_OK=false
    fi
else
    # Fallback health check
    if docker exec "${CONTAINER_NAME}" python -c "import assistant; print('ok')" 2>/dev/null; then
        HEALTH_OK=true
        echo -e "${GREEN}✓ Health check passed${NC}"
    else
        HEALTH_OK=false
    fi
fi

# Final status
echo ""
if [ "$HEALTH_OK" = true ]; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  Rollback: SUCCESSFUL${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "Rolled back to: ${IMAGE}:${previous_tag}"
    echo ""
    echo "To verify manually:"
    echo "  docker logs ${CONTAINER_NAME}"
    echo "  docker exec ${CONTAINER_NAME} python -m assistant check"
    exit 0
else
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}  Rollback: FAILED${NC}"
    echo -e "${RED}========================================${NC}"
    echo ""
    echo "The previous image also failed health check."
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check container logs: docker logs ${CONTAINER_NAME}"
    echo "  2. Check available images: ./rollback.sh --list"
    echo "  3. Try an older version: ./rollback.sh --to <tag>"
    echo "  4. Check environment: cat /etc/second-brain.env"
    exit 1
fi
