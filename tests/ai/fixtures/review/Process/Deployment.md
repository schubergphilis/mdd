---
title: Deployment Process
updated_at: "2025-03-01"
---

# Deployment Process

This document describes how to deploy services.

## Rollout Strategy

Blue-green is the default deployment strategy for all services.
Traffic is switched atomically once the new version is healthy.

## Pre-deployment Checklist

1. Run all unit tests
2. Deploy to staging
3. Run smoke tests
4. Get approval from team lead

## Rollback

If deployment fails, switch traffic back to the blue environment immediately.
