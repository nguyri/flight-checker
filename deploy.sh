#!/bin/bash
cd /home/richard/code/python-general/flight-checker

echo "Webhook triggered: Pulling changes..."
git fetch --all
git reset --hard origin/main

echo "Automating Docker rebuild & cleaning old logs..."
cd infra
# The down command clears the container instances, wiping the logs completely
docker compose down --remove-orphans

# The build flag spins up a completely fresh logging layer
docker compose up -d --build --force-recreate

echo "Deployment complete at $(date)"