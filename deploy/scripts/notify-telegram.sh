#!/bin/bash
#
# Telegram Notification Script for CI/CD
# Sends deployment status messages via Telegram Bot API
#
# Usage: ./notify-telegram.sh [success|failure|rollback] [message]
#
# Required environment variables:
#   TELEGRAM_BOT_TOKEN   - Bot token from @BotFather
#   TELEGRAM_CHAT_ID     - Chat ID to send notifications to
#
# Optional environment variables:
#   GITHUB_SHA           - Git commit SHA (short form used)
#   GITHUB_REPOSITORY    - Repository name (owner/repo)
#   GITHUB_ACTOR         - Username who triggered the deployment
#   GITHUB_RUN_ID        - Workflow run ID for linking to logs
#   GITHUB_SERVER_URL    - GitHub server URL (default: https://github.com)

set -e

# Colors for local output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Default values
STATUS="${1:-info}"
CUSTOM_MESSAGE="${2:-}"

# Validate required environment variables
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
    echo -e "${RED}Error: TELEGRAM_BOT_TOKEN is required${NC}" >&2
    exit 1
fi

if [[ -z "${TELEGRAM_CHAT_ID:-}" ]]; then
    echo -e "${RED}Error: TELEGRAM_CHAT_ID is required${NC}" >&2
    exit 1
fi

# Helper to escape markdown special characters
escape_markdown() {
    local text="$1"
    # Escape MarkdownV2 special characters: _ * [ ] ( ) ~ ` > # + - = | { } . !
    echo "$text" | sed 's/[_*\[\]()~`>#+=|{}.!-]/\\&/g'
}

# Build message based on status
build_message() {
    local emoji
    local title
    local color

    case "$STATUS" in
        success)
            emoji="✅"
            title="Deployment Successful"
            ;;
        failure)
            emoji="❌"
            title="Deployment Failed"
            ;;
        rollback)
            emoji="⚠️"
            title="Deployment Rolled Back"
            ;;
        started)
            emoji="🚀"
            title="Deployment Started"
            ;;
        *)
            emoji="ℹ️"
            title="Deployment Info"
            ;;
    esac

    # Start building message
    local message="${emoji} *${title}*"

    # Add repository info if available
    if [[ -n "${GITHUB_REPOSITORY:-}" ]]; then
        local repo_escaped
        repo_escaped=$(escape_markdown "$GITHUB_REPOSITORY")
        message+="\n\n*Repository:* \`${repo_escaped}\`"
    fi

    # Add commit SHA if available
    if [[ -n "${GITHUB_SHA:-}" ]]; then
        local short_sha="${GITHUB_SHA:0:7}"
        message+="\n*Commit:* \`${short_sha}\`"
    fi

    # Add actor if available
    if [[ -n "${GITHUB_ACTOR:-}" ]]; then
        local actor_escaped
        actor_escaped=$(escape_markdown "$GITHUB_ACTOR")
        message+="\n*Triggered by:* ${actor_escaped}"
    fi

    # Add custom message if provided
    if [[ -n "${CUSTOM_MESSAGE}" ]]; then
        local custom_escaped
        custom_escaped=$(escape_markdown "$CUSTOM_MESSAGE")
        message+="\n\n${custom_escaped}"
    fi

    # Add link to workflow run if available
    if [[ -n "${GITHUB_RUN_ID:-}" && -n "${GITHUB_REPOSITORY:-}" ]]; then
        local server_url="${GITHUB_SERVER_URL:-https://github.com}"
        local run_url="${server_url}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
        message+="\n\n[View Workflow Run](${run_url})"
    fi

    # Add timestamp
    local timestamp
    timestamp=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
    local timestamp_escaped
    timestamp_escaped=$(escape_markdown "$timestamp")
    message+="\n\n_${timestamp_escaped}_"

    echo -e "$message"
}

# Send message via Telegram API
send_telegram_message() {
    local message="$1"
    local api_url="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"

    # Send request with retry
    local max_retries=3
    local retry=0
    local response

    while [[ $retry -lt $max_retries ]]; do
        response=$(curl -s -w "\n%{http_code}" -X POST "$api_url" \
            -H "Content-Type: application/json" \
            -d "{
                \"chat_id\": \"${TELEGRAM_CHAT_ID}\",
                \"text\": $(echo "$message" | jq -Rs .),
                \"parse_mode\": \"MarkdownV2\",
                \"disable_web_page_preview\": true
            }" 2>&1) || true

        local http_code
        http_code=$(echo "$response" | tail -n1)
        local body
        body=$(echo "$response" | sed '$d')

        if [[ "$http_code" == "200" ]]; then
            echo -e "${GREEN}Notification sent successfully${NC}"
            return 0
        fi

        retry=$((retry + 1))

        if [[ $retry -lt $max_retries ]]; then
            echo -e "${YELLOW}Retry $retry/$max_retries after error (HTTP $http_code)${NC}" >&2
            sleep 2
        else
            echo -e "${RED}Failed to send notification after $max_retries attempts${NC}" >&2
            echo "Response: $body" >&2
            return 1
        fi
    done
}

# Main execution
main() {
    local message
    message=$(build_message)

    echo "Sending Telegram notification..."
    echo "Status: $STATUS"

    if send_telegram_message "$message"; then
        echo -e "${GREEN}Done!${NC}"
        exit 0
    else
        # Don't fail the pipeline for notification failures
        echo -e "${YELLOW}Warning: Notification failed but continuing...${NC}"
        exit 0
    fi
}

# Run main if not being sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
