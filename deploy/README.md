# Second Brain Deployment

This directory contains deployment configurations for Second Brain.

## Quick Start

### 1. Build the Docker Image

```bash
docker build -t second-brain:latest .
```

### 2. Configure Environment

Copy the environment template and fill in your credentials:

```bash
sudo cp deploy/systemd/second-brain.env.example /etc/second-brain.env
sudo chmod 600 /etc/second-brain.env
sudo nano /etc/second-brain.env  # Edit with your credentials
```

### 3. Install systemd Services

```bash
cd deploy/systemd
sudo ./install.sh
```

### 4. Start Services

```bash
# Start the Telegram bot
sudo systemctl start second-brain.service

# Start the 7am briefing timer
sudo systemctl start second-brain-briefing.timer
```

## Files

### systemd/

- **second-brain.service** - Main Telegram bot service (always running)
- **second-brain-briefing.service** - One-shot service to send morning briefing
- **second-brain-briefing.timer** - Timer that triggers briefing at 7:00 AM
- **install.sh** - Installation script

## Architecture

```
┌─────────────────────────────────────────────────┐
│                 systemd                          │
├─────────────────────────────────────────────────┤
│                                                  │
│  second-brain.service                           │
│  └─ Docker container running Telegram bot        │
│                                                  │
│  second-brain-briefing.timer  (7:00 AM daily)   │
│  └─► second-brain-briefing.service              │
│      └─ docker exec ... python -m assistant      │
│                       briefing                   │
│                                                  │
└─────────────────────────────────────────────────┘
```

## Useful Commands

```bash
# Check bot status
sudo systemctl status second-brain.service

# View bot logs
journalctl -u second-brain.service -f

# Check when next briefing is scheduled
systemctl list-timers second-brain-briefing.timer

# Manually trigger a briefing
sudo systemctl start second-brain-briefing.service

# Restart the bot
sudo systemctl restart second-brain.service

# Check briefing log
journalctl -u second-brain-briefing.service --since today
```

## Troubleshooting

### Bot not starting

1. Check logs: `journalctl -u second-brain.service -e`
2. Verify Docker image exists: `docker images | grep second-brain`
3. Check environment file: `sudo cat /etc/second-brain.env`

### Briefing not sending

1. Check timer status: `systemctl status second-brain-briefing.timer`
2. Check service status: `systemctl status second-brain-briefing.service`
3. Verify USER_TELEGRAM_CHAT_ID is set in environment file
4. Try manual send: `sudo systemctl start second-brain-briefing.service`
