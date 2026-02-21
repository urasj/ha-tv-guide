#!/bin/bash
set -e

CONFIG=/data/options.json

export SONARR_URL=$(jq --raw-output '.sonarr_url' $CONFIG)
export SONARR_KEY=$(jq --raw-output '.sonarr_key' $CONFIG)
export TMDB_KEY=$(jq --raw-output '.tmdb_key' $CONFIG)
export HA_URL=$(jq --raw-output '.ha_url' $CONFIG)
export HA_TOKEN=$(jq --raw-output '.ha_token' $CONFIG)
export FIRETV_ENTITY=$(jq --raw-output '.firetv_entity' $CONFIG)
export SONOS_ENTITY=$(jq --raw-output '.sonos_entity' $CONFIG)
export INGRESS_PATH=""

echo "Starting TV Guide on port 8099..."
exec python3 /app/main.py
