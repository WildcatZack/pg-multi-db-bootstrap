# Postgres Multi-DB Bootstrap (Sidecar)

A lightweight, idempotent sidecar that provisions multiple PostgreSQL databases and matching login roles at startup. Designed for Docker Compose/Kubernetes jobs where you want to **declare DBs once** and reconcile on every `up` without wiping volumes.

## What it does
- Reads a list of database names.
- For each name `X`, ensures:
  - role `X` exists with LOGIN
  - database `X` exists and is owned by `X`
  - ownership and basic grants are re-asserted (idempotent)

## Status
WIP — initial publish. See repo issues/milestones for roadmap.
