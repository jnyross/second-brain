# UptimeRobot Monitoring Setup (T-211)

This guide explains how to set up external uptime monitoring for Second Brain using UptimeRobot with Telegram alerts.

## Overview

Second Brain uses **Heartbeat monitoring** instead of HTTP endpoint monitoring because:
- The bot uses Telegram long-polling (no HTTP server exposed)
- No ports need to be opened in firewalls
- Works naturally with Docker/NAT environments
- Simpler security configuration

The bot sends periodic "heartbeats" to UptimeRobot. If no heartbeat is received within the configured interval, UptimeRobot marks the service as DOWN and sends Telegram alerts.

## Setup Steps

### 1. Create UptimeRobot Account

1. Go to [UptimeRobot](https://uptimerobot.com/) and sign up (free tier available)
2. Verify your email address

### 2. Create a Heartbeat Monitor

1. Click **"Add New Monitor"**
2. Select **"Heartbeat"** as monitor type
3. Configure:
   - **Friendly Name**: `Second Brain Bot`
   - **Heartbeat Interval**: `5 minutes` (matches our default)
   - **Grace Period**: `1 minute` (optional delay before alerting)
4. Click **"Create Monitor"**
5. **Copy the Heartbeat URL** (format: `https://heartbeat.uptimerobot.com/xxxxx`)

### 3. Create Telegram Alert Contact

1. Go to **My Settings** → **Alert Contacts**
2. Click **"Add Alert Contact"**
3. Select **"Telegram"**
4. Click **"Connect Telegram Account"**
5. Open the link in Telegram and click **Start** on @uptikibot
6. Follow the verification steps
7. Name the contact (e.g., "My Telegram")
8. Save the contact

### 4. Attach Alert Contact to Monitor

1. Go back to your **Second Brain Bot** monitor
2. Click **Edit**
3. Under **Alert Contacts**, check the Telegram contact you created
4. Save changes

### 5. Configure Second Brain

Add the heartbeat URL to your environment:

**Development (`.env` file):**
```bash
UPTIMEROBOT_HEARTBEAT_URL=https://heartbeat.uptimerobot.com/xxxxx
UPTIMEROBOT_HEARTBEAT_INTERVAL=300  # Optional, default 5 min
```

**Production (`/etc/second-brain.env`):**
```bash
UPTIMEROBOT_HEARTBEAT_URL=https://heartbeat.uptimerobot.com/xxxxx
```

### 6. Restart the Bot

```bash
# Development
python -m assistant run

# Production
sudo systemctl restart second-brain.service
```

## Verification

### Check Heartbeat is Working

1. In UptimeRobot dashboard, your monitor should show **"Up"** (green)
2. Check the bot logs:
   ```bash
   journalctl -u second-brain.service | grep -i heartbeat
   ```
   You should see: `Starting heartbeat loop (interval: 300s)`

### Test Alerts

1. Stop the bot: `sudo systemctl stop second-brain.service`
2. Wait for the heartbeat interval + grace period
3. You should receive a Telegram notification about downtime
4. Restart the bot and verify the "Up" notification

## Configuration Options

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `UPTIMEROBOT_HEARTBEAT_URL` | (none) | Heartbeat URL from UptimeRobot |
| `UPTIMEROBOT_HEARTBEAT_INTERVAL` | `300` | Seconds between heartbeats |

## Troubleshooting

### Monitor shows DOWN but bot is running

1. Check network connectivity: `curl -I https://heartbeat.uptimerobot.com/xxxxx`
2. Check logs for errors: `journalctl -u second-brain.service | grep heartbeat`
3. Verify URL is correct (no typos)

### No Telegram alerts

1. Verify Telegram contact is connected in UptimeRobot
2. Check that contact is attached to the monitor
3. Try triggering a test alert in UptimeRobot

### Heartbeat not starting

Check that `UPTIMEROBOT_HEARTBEAT_URL` is set:
```bash
grep UPTIMEROBOT /etc/second-brain.env
```

If not configured, the heartbeat service is silently skipped (by design).

## Free Tier Limits

UptimeRobot's free tier includes:
- 50 monitors
- 5-minute check intervals
- Telegram alerts
- Email alerts
- No credit card required

This is more than sufficient for personal use.
