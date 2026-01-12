#!/bin/bash
# setup-server.sh - One-time setup for fresh Ubuntu 24.04 droplet
# Run as root: curl -sSL <url> | sudo bash
# Or: sudo ./setup-server.sh
#
# This script:
# 1. Updates system packages
# 2. Installs Docker
# 3. Installs and configures fail2ban
# 4. Configures UFW firewall
# 5. Creates deploy user with Docker access
# 6. Creates app directories
# 7. Disables SSH password authentication
#
# Prerequisites:
# - Fresh Ubuntu 24.04 LTS droplet
# - Root access (run with sudo)
# - Your SSH public key ready for deploy user

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

# Check Ubuntu version
if ! grep -q "Ubuntu" /etc/os-release 2>/dev/null; then
    log_warn "This script is designed for Ubuntu. Proceeding anyway..."
fi

log_info "Starting Second Brain server setup..."

# ============================================
# Step 1: Update system packages
# ============================================
log_info "Updating system packages..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq

# ============================================
# Step 2: Install Docker
# ============================================
if command -v docker &> /dev/null; then
    log_info "Docker already installed, skipping..."
else
    log_info "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

# Verify Docker is working
if ! docker info &> /dev/null; then
    log_error "Docker installation failed"
    exit 1
fi
log_info "Docker installed successfully"

# Install Docker Compose plugin if not present
if ! docker compose version &> /dev/null; then
    log_info "Installing Docker Compose plugin..."
    apt-get install -y -qq docker-compose-plugin
fi

# ============================================
# Step 3: Install fail2ban
# ============================================
if dpkg -l | grep -q fail2ban; then
    log_info "fail2ban already installed, skipping..."
else
    log_info "Installing fail2ban..."
    apt-get install -y -qq fail2ban
fi

# Configure fail2ban for SSH
cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 86400
EOF

systemctl enable fail2ban
systemctl restart fail2ban
log_info "fail2ban configured and started"

# ============================================
# Step 4: Configure UFW firewall
# ============================================
log_info "Configuring UFW firewall..."
apt-get install -y -qq ufw

# Set default policies
ufw default deny incoming
ufw default allow outgoing

# Allow SSH (critical - do this before enabling!)
ufw allow ssh

# Enable firewall (--force skips confirmation)
ufw --force enable
log_info "UFW firewall enabled (SSH allowed)"

# ============================================
# Step 5: Create deploy user
# ============================================
DEPLOY_USER="deploy"

if id "$DEPLOY_USER" &>/dev/null; then
    log_info "User '$DEPLOY_USER' already exists, updating groups..."
else
    log_info "Creating deploy user..."
    useradd -m -s /bin/bash "$DEPLOY_USER"
fi

# Add to docker group
usermod -aG docker "$DEPLOY_USER"

# Create .ssh directory for deploy user
DEPLOY_HOME="/home/$DEPLOY_USER"
mkdir -p "$DEPLOY_HOME/.ssh"
chmod 700 "$DEPLOY_HOME/.ssh"
touch "$DEPLOY_HOME/.ssh/authorized_keys"
chmod 600 "$DEPLOY_HOME/.ssh/authorized_keys"
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$DEPLOY_HOME/.ssh"

log_info "Deploy user created. Add your SSH public key to:"
log_info "  $DEPLOY_HOME/.ssh/authorized_keys"

# ============================================
# Step 6: Create app directories
# ============================================
log_info "Creating application directories..."
APP_DIR="/opt/second-brain"
mkdir -p "$APP_DIR"/{data,logs,scripts,backups}
mkdir -p "$APP_DIR/data"/{tokens,cache,queue,nudges}
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"

# Create var directory for Docker volume mounts
VAR_DIR="/var/lib/second-brain"
mkdir -p "$VAR_DIR"/{tokens,cache,logs,queue,nudges}
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$VAR_DIR"

log_info "Directories created:"
log_info "  $APP_DIR (app home)"
log_info "  $VAR_DIR (Docker volumes)"

# ============================================
# Step 7: Disable SSH password authentication
# ============================================
SSHD_CONFIG="/etc/ssh/sshd_config"
SSHD_BACKUP="/etc/ssh/sshd_config.backup.$(date +%Y%m%d%H%M%S)"

log_info "Hardening SSH configuration..."

# Backup original config
cp "$SSHD_CONFIG" "$SSHD_BACKUP"

# Disable password authentication
if grep -q "^PasswordAuthentication" "$SSHD_CONFIG"; then
    sed -i 's/^PasswordAuthentication.*/PasswordAuthentication no/' "$SSHD_CONFIG"
else
    echo "PasswordAuthentication no" >> "$SSHD_CONFIG"
fi

# Disable root login via password (keep key-based if needed)
if grep -q "^PermitRootLogin" "$SSHD_CONFIG"; then
    sed -i 's/^PermitRootLogin.*/PermitRootLogin prohibit-password/' "$SSHD_CONFIG"
else
    echo "PermitRootLogin prohibit-password" >> "$SSHD_CONFIG"
fi

# Disable empty passwords
if grep -q "^PermitEmptyPasswords" "$SSHD_CONFIG"; then
    sed -i 's/^PermitEmptyPasswords.*/PermitEmptyPasswords no/' "$SSHD_CONFIG"
else
    echo "PermitEmptyPasswords no" >> "$SSHD_CONFIG"
fi

# Restart SSH to apply changes
systemctl restart sshd
log_info "SSH hardened (password auth disabled, backup at $SSHD_BACKUP)"

# ============================================
# Step 8: Create environment file template
# ============================================
ENV_FILE="/etc/second-brain.env"
if [[ ! -f "$ENV_FILE" ]]; then
    log_info "Creating environment file template..."
    cat > "$ENV_FILE" << 'EOF'
# Second Brain Environment Configuration
# IMPORTANT: Fill in these values before starting the container

# === Required ===
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
NOTION_API_KEY=your_notion_api_key_here

# === Notion Database IDs ===
NOTION_INBOX_DB_ID=
NOTION_TASKS_DB_ID=
NOTION_PEOPLE_DB_ID=
NOTION_PROJECTS_DB_ID=
NOTION_PLACES_DB_ID=
NOTION_PREFERENCES_DB_ID=
NOTION_PATTERNS_DB_ID=
NOTION_EMAILS_DB_ID=
NOTION_LOG_DB_ID=

# === Optional ===
OPENAI_API_KEY=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# === Settings ===
USER_TIMEZONE=America/Los_Angeles
CONFIDENCE_THRESHOLD=80
LOG_LEVEL=INFO

# === Internal (do not change) ===
SECOND_BRAIN_HOME=/var/lib/second-brain
PYTHONDONTWRITEBYTECODE=1
PYTHONUNBUFFERED=1
EOF
    chmod 600 "$ENV_FILE"
    log_info "Environment template created at $ENV_FILE"
    log_warn "IMPORTANT: Edit $ENV_FILE and fill in your API keys!"
else
    log_info "Environment file already exists at $ENV_FILE"
fi

# ============================================
# Step 9: Create systemd timer directory structure
# ============================================
# Note: Timers are configured by T-207 after initial deployment.
# This step creates the directory and documents the process.
log_info "Preparing for systemd timers..."
SYSTEMD_USER_DIR="/etc/systemd/system"

# Create note about timer installation
cat > "$APP_DIR/scripts/install-timers.sh" << 'EOF'
#!/bin/bash
# Install systemd timers for scheduled tasks
# Run after first deployment copies the timer files

set -euo pipefail

TIMER_SOURCE_DIR="/opt/second-brain/deploy/systemd"
SYSTEMD_DIR="/etc/systemd/system"

if [[ ! -d "$TIMER_SOURCE_DIR" ]]; then
    echo "Timer files not found. Run deployment first."
    exit 1
fi

# Copy service and timer files
cp "$TIMER_SOURCE_DIR"/*.service "$SYSTEMD_DIR/" 2>/dev/null || true
cp "$TIMER_SOURCE_DIR"/*.timer "$SYSTEMD_DIR/" 2>/dev/null || true

# Reload and enable
systemctl daemon-reload

# Enable briefing timer (7am daily)
if [[ -f "$SYSTEMD_DIR/second-brain-briefing.timer" ]]; then
    systemctl enable second-brain-briefing.timer
    systemctl start second-brain-briefing.timer
    echo "Enabled: second-brain-briefing.timer"
fi

# Enable nudge timer (9am, 2pm, 6pm daily)
if [[ -f "$SYSTEMD_DIR/second-brain-nudge.timer" ]]; then
    systemctl enable second-brain-nudge.timer
    systemctl start second-brain-nudge.timer
    echo "Enabled: second-brain-nudge.timer"
fi

echo "Timers installed. Check with: systemctl list-timers"
EOF
chmod +x "$APP_DIR/scripts/install-timers.sh"
chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR/scripts/install-timers.sh"
log_info "Timer installer script created at $APP_DIR/scripts/install-timers.sh"

# ============================================
# Summary
# ============================================
echo ""
echo "============================================"
echo -e "${GREEN}Server setup complete!${NC}"
echo "============================================"
echo ""
echo "Next steps:"
echo "1. Add your SSH public key to:"
echo "   $DEPLOY_HOME/.ssh/authorized_keys"
echo ""
echo "2. Edit the environment file:"
echo "   sudo nano $ENV_FILE"
echo ""
echo "3. Configure GitHub Actions secrets:"
echo "   - DO_HOST: $(hostname -I | awk '{print $1}')"
echo "   - DO_USER: deploy"
echo "   - DO_SSH_KEY: (your private key)"
echo ""
echo "4. Deploy will happen automatically on push to main"
echo ""
echo "Security status:"
echo "  - UFW: $(ufw status | grep -o 'active')"
echo "  - fail2ban: $(systemctl is-active fail2ban)"
echo "  - SSH password auth: disabled"
echo ""
log_info "Done! Server is ready for deployment."
