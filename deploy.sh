#!/bin/bash
cd /home/richard/code/flight-checker || exit 1

echo "Webhook triggered: Pulling changes..." >&2
git clean -fd
git fetch --all
git reset --hard origin/main

echo "Automating Docker rebuild..." >&2
cd infra
docker compose down --remove-orphans
docker compose up -d --build --force-recreate

echo "Deployment complete at $(date)" >&2