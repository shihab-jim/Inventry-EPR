#!/usr/bin/env bash
# Exit on error
set -o errexit

# Install dependencies
pip install -r requirements.txt

# Collect static files for WhiteNoise
python manage.py collectstatic --no-input

# Apply database migrations
python manage.py migrate

# Seed demo data if database is empty (safe to run on every deploy)
python manage.py seed_demo || true

