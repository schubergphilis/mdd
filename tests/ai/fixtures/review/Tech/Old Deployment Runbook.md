---
title: Old Deployment Runbook
updated_at: "2021-06-15"
---

# Old Deployment Runbook

Last reviewed: 2021-06-15

This is our legacy deployment process.

## Steps

1. SSH to the production server.
2. Pull the latest code: `git pull origin main`.
3. Run migrations: `python manage.py migrate`.
4. Restart the application: `sudo systemctl restart app`.
5. Check the logs: `sudo journalctl -u app -f`.
6. Verify health endpoint: `curl http://localhost:8000/health`.

## Rollback

`git revert HEAD && git push` then repeat steps 1-6.
