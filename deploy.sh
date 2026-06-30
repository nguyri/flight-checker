#!/bin/bash

# Navigate to the project directory
cd /home/richard/code/flight-checker

# Fetch latest code from your repository
echo "Checking for code updates..."
GIT_OUTPUT=$(git pull origin main)

# If Git pulled new changes, trigger Docker Compose to rebuild automatically
if [ "$GIT_OUTPUT" != "Already up to date." ]; then
    echo "New code detected! Automating Docker rebuild..."
    cd infra
    docker compose up -d --build
    echo "Deployment complete."
else
    echo "No code changes found. Keeping current image."
fi