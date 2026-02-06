# Slack bot setup (Socket Mode)

Step by step:

1. Create a Slack app
- Open Slack API Apps.
- Click "Create New App" -> "From scratch".
- Choose a name and workspace.

2. Enable Socket Mode
- In App settings, enable "Socket Mode".
- Create an App-Level Token with `connections:write` scope.
- Copy the token (starts with `xapp-...`).

3. Set up OAuth scopes for the bot
- In "OAuth & Permissions", add Bot Token Scopes:
  - `app_mentions:read`
  - `chat:write`
  - `im:history`
  - `im:write`
  - `files:read`
  - `channels:history` (required for `AIDE_SLACK_AUTO_THREAD`)
  - `groups:history` (required for auto-thread in private channels)

4. Enable Event Subscriptions
- Enable "Event Subscriptions".
- Add Bot Events:
  - `app_mention`
  - `message.im`
  - `message.channels` (required for `AIDE_SLACK_AUTO_THREAD`)
  - `message.groups` (required for auto-thread in private channels)
Note: If Slack UI requires a Request URL, use your own public endpoint for verification. With Socket Mode, events are delivered via WebSocket.

5. Install app to workspace
- In "OAuth & Permissions", click "Install to Workspace".
- Copy the Bot User OAuth Token (starts with `xoxb-...`).

6. Add the bot to a channel
- In the channel, type `/invite @your-bot-name`.

7. Get your Slack user ID
- Click your profile in the top right.
- Choose "Profile".
- Click the three dots and select "Copy member ID".

8. Configure `.env` in your workspace
```
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
AIDE_SLACK_ENABLED=1
AIDE_SLACK_ALLOWED_USERS=UXXXXXXX
AIDE_SLACK_DEFAULT_TARGET=UXXXXXXX
AIDE_SLACK_AUTO_THREAD=1
AIDE_NOTIFY_PROVIDER=slack
```
Notes:
- `AIDE_SLACK_ALLOWED_USERS`: comma-separated list of Slack user IDs.
- `AIDE_SLACK_DEFAULT_TARGET`: `U...` for DM, or `C.../G...` for a channel.
- To force a target type, use `AIDE_SLACK_DEFAULT_TARGET_TYPE=dm|channel`.
- `AIDE_SLACK_AUTO_THREAD`: `1` = bot automatically replies in threads without requiring @mention (default: `0`). Requires adding event subscriptions `message.channels`/`message.groups` and scopes `channels:history`/`groups:history`.

9. Start the bot
```
./scripts/run.sh /path/to/workspace
```

Troubleshooting:
- Check `slack.log` in `data/logs/`.
- Wrong permissions? Try reinstalling the app (after changing scopes).
