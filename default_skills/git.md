# Git

## When to activate
- User wants to commit, push, pull, or manage git repositories
- User asks about git status, branches, or history
- User needs to set up GitHub access (token)

## Setup

Git authentication uses a personal access token (GITHUB_TOKEN) stored in the user's `.env` file.

### How to create a GitHub token
1. Go to https://github.com/settings/tokens
2. Click "Generate new token (classic)"
3. Select scopes: `repo` (full access to repositories)
4. Copy the token

### How to configure
Add the token to your workspace `.env`:
```
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

The system uses `GIT_ASKPASS` helper that reads this token automatically. No need to run `gh auth login` or configure credentials manually.

## Operations

### Status
```bash
git -C "$AIDE_WORKSPACE" status
```

### Commit and push
```bash
git -C "$AIDE_WORKSPACE" add -A
git -C "$AIDE_WORKSPACE" commit -m "message"
git -C "$AIDE_WORKSPACE" push
```

### Backup (preferred)
Use the backup script which handles auth automatically:
```bash
/opt/aide/engine/scripts/backup.sh "$AIDE_WORKSPACE" --push
```

## Important rules
- Never force push (`--force`)
- Never commit `.env` files or secrets
- Each user has their own GITHUB_TOKEN — never share tokens
- If GITHUB_TOKEN is not set, git push/pull to private repos will fail
- The backup script runs automatically via cron; manual backup is rarely needed
