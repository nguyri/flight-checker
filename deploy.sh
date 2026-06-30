#!/bin/bash
TARGET_DIR="/home/richard/code/flight-checker"

echo "Webhook triggered: Pulling changes..." >&2
cd "$TARGET_DIR" || exit 1

git clean -fd
git fetch --all
git reset --hard origin/main

echo "Automating Docker rebuild..." >&2
cd infra

# The -v flag clears out stalled local volume links, and removes network bindings cleanly
docker compose down -v --remove-orphans

# Spin up completely fresh containers and network bridges
docker compose up -d --build --force-recreate

echo "Deployment complete at $(date)" >&2