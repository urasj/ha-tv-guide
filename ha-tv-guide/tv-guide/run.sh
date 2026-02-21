#!/usr/bin/with-contenv bashio

export SONARR_URL=$(bashio::config 'sonarr_url')
export SONARR_KEY=$(bashio::config 'sonarr_key')
export TMDB_KEY=$(bashio::config 'tmdb_key')
export HA_URL=$(bashio::config 'ha_url')
export HA_TOKEN=$(bashio::config 'ha_token')
export FIRETV_ENTITY=$(bashio::config 'firetv_entity')
export SONOS_ENTITY=$(bashio::config 'sonos_entity')
export INGRESS_PATH=$(bashio::addon.ingress_entry)

bashio::log.info "Starting TV Guide on port 8099..."
exec python3 /app/main.py
