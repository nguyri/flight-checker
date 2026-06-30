#!/bin/bash
# /home/richard/code/python-general/flight-checker/deploy.sh

cd /home/richard/code/python-general/flight-checker

echo "Webhook triggered: Pulling changes from main..."
git fetch --all
git reset --hard origin/main

echo "Automating Docker rebuild..."
cd infra
docker compose up -d --build --remove-orphans

echo "Deployment complete at $(date)"