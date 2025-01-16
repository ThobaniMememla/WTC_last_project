#!/bin/bash

# Clean up Docker environment
docker compose down

docker container list -a | grep wtc | tr -s ' ' | cut -d' ' -f 1 | xargs -r docker container stop
docker container list -a | grep wtc | tr -s ' ' | cut -d' ' -f 1 | xargs -r docker container rm
docker image ls | grep wtc | tr -s ' ' | cut -d' ' -f 3 | xargs -r docker image rm
rm -rf ./volumes/data

sleep 5

docker compose up -d


if [ $? -ne 0 ]; then
    echo "ERROR: Failed to start all required containers"
    exit 1
fi

# Wait for Debezium Connect to start
echo "Waiting for Debezium Connect to start..."
timeout=300
elapsed=0
while ! curl -s http://localhost:8083/ | grep -q '"version"'; do
    sleep 5
    elapsed=$((elapsed + 5))
    echo "Still waiting for Debezium Connect... ($elapsed seconds elapsed)"
    docker ps | grep debezium_connect || echo "Debezium container not running"
    if [ $elapsed -ge $timeout ]; then
        echo "ERROR: Timed out waiting for Debezium Connect to start"
        exit 1
    fi
done
echo "Debezium Connect is up and running!"

# Copy configuration file
CONFIG_FILE="./volumes/config/debezium/source_config.json"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: Configuration file not found at $CONFIG_FILE"
    exit 1
fi
docker cp "$CONFIG_FILE" debezium_connect:/tmp/source_config.json
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to copy configuration file"
    exit 1
fi

# Create Debezium connector
echo "Creating the Debezium connector..."
curl -X POST http://localhost:8083/connectors \
  -H "Content-Type: application/json" \
  -d @"$CONFIG_FILE"
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to create the connector"
    exit 1
fi

# Check connector status
echo "Checking connector status..."
curl -X GET http://localhost:8083/connectors/inventory-connector/status
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to retrieve connector status"
    exit 1
fi
