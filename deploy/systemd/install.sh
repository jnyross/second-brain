#!/bin/bash
# Second Brain systemd installation script
#
# Usage:
#   sudo ./install.sh
#
# This script:
#   1. Creates the second-brain user
#   2. Creates required directories
#   3. Installs systemd service and timer files
#   4. Enables the services
#
# Prerequisites:
#   - Docker installed and running
#   - second-brain Docker image built
#   - /etc/second-brain.env configured with secrets

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root (use sudo)"
    exit 1
fi

# Check for Docker
if ! command -v docker &> /dev/null; then
    log_error "Docker is not installed. Please install Docker first."
    exit 1
fi

log_info "Installing Second Brain systemd services..."

# Create user and group if they don't exist
if ! id "second-brain" &>/dev/null; then
    log_info "Creating second-brain user..."
    useradd --system --no-create-home --shell /usr/sbin/nologin second-brain
    usermod -aG docker second-brain
fi

# Create directories
log_info "Creating directories..."
mkdir -p /opt/second-brain
mkdir -p /var/lib/second-brain/tokens
mkdir -p /var/lib/second-brain/cache
mkdir -p /var/lib/second-brain/logs

# Set ownership
chown -R second-brain:second-brain /var/lib/second-brain

# Check for environment file
if [[ ! -f /etc/second-brain.env ]]; then
    log_warn "/etc/second-brain.env not found. Creating template..."
    cat > /etc/second-brain.env << 'EOF'
# Second Brain Environment Configuration
# Replace these values with your actual credentials

# Required: Telegram Bot Token from @BotFather
TELEGRAM_BOT_TOKEN=your-telegram-bot-token

# Required: Notion API Key from notion.so/my-integrations
NOTION_API_KEY=your-notion-api-key

# Required: Your Telegram chat ID (send /start to @userinfobot to get it)
USER_TELEGRAM_CHAT_ID=your-chat-id

# Required: Notion Database IDs
NOTION_INBOX_DB_ID=your-inbox-db-id
NOTION_TASKS_DB_ID=your-tasks-db-id
NOTION_PEOPLE_DB_ID=your-people-db-id
NOTION_PROJECTS_DB_ID=your-projects-db-id
NOTION_PLACES_DB_ID=your-places-db-id
NOTION_PREFERENCES_DB_ID=your-preferences-db-id
NOTION_PATTERNS_DB_ID=your-patterns-db-id
NOTION_EMAILS_DB_ID=your-emails-db-id
NOTION_LOG_DB_ID=your-log-db-id

# Optional: OpenAI API Key for Whisper transcription
OPENAI_API_KEY=your-openai-api-key

# Optional: Google OAuth (for Calendar/Gmail)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_MAPS_API_KEY=your-google-maps-api-key

# Settings
USER_TIMEZONE=America/Los_Angeles
CONFIDENCE_THRESHOLD=80
LOG_LEVEL=INFO
EOF
    chmod 600 /etc/second-brain.env
    log_warn "Please edit /etc/second-brain.env with your credentials"
fi

# Copy systemd files
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log_info "Installing systemd unit files..."
cp "${SCRIPT_DIR}/second-brain.service" /etc/systemd/system/
cp "${SCRIPT_DIR}/second-brain-briefing.service" /etc/systemd/system/
cp "${SCRIPT_DIR}/second-brain-briefing.timer" /etc/systemd/system/
cp "${SCRIPT_DIR}/second-brain-nudge.service" /etc/systemd/system/
cp "${SCRIPT_DIR}/second-brain-nudge.timer" /etc/systemd/system/

# Set permissions
chmod 644 /etc/systemd/system/second-brain.service
chmod 644 /etc/systemd/system/second-brain-briefing.service
chmod 644 /etc/systemd/system/second-brain-briefing.timer
chmod 644 /etc/systemd/system/second-brain-nudge.service
chmod 644 /etc/systemd/system/second-brain-nudge.timer

# Reload systemd
log_info "Reloading systemd daemon..."
systemctl daemon-reload

# Enable services
log_info "Enabling services..."
systemctl enable second-brain.service
systemctl enable second-brain-briefing.timer
systemctl enable second-brain-nudge.timer

log_info "Installation complete!"
echo
echo "Next steps:"
echo "  1. Edit /etc/second-brain.env with your credentials"
echo "  2. Build or pull the Docker image: docker build -t second-brain:latest ."
echo "  3. Start the bot: sudo systemctl start second-brain.service"
echo "  4. Start the timers:"
echo "     sudo systemctl start second-brain-briefing.timer  # 7am briefing"
echo "     sudo systemctl start second-brain-nudge.timer     # 9am/2pm/6pm nudges"
echo
echo "Useful commands:"
echo "  systemctl status second-brain.service     # Check bot status"
echo "  journalctl -u second-brain.service -f    # View bot logs"
echo "  systemctl list-timers                    # Check all timer schedules"
echo "  systemctl start second-brain-briefing    # Send briefing now"
echo "  systemctl start second-brain-nudge       # Send nudges now"
