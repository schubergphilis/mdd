---
title: Platform Deployment
updated_at: "2025-04-20"
---

# Platform Deployment

Platform deployment guide for production services.

## Rollout Strategy

Canary is the default for production deployments.
10% of traffic is shifted to the new version first.
Full rollout happens after 30 minutes if error rate stays below 0.1%.

## Pre-deployment Checklist

1. Run all unit tests
2. Deploy to staging
3. Run smoke tests
4. Get approval from team lead

## Rollback

Use the platform CLI to roll back: `platform rollback <service>`.
