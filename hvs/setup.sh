#!/bin/bash

# Pull the docker image 
echo "Setting up the environment"

if ! docker images | grep -q 'scylladb/scylla'; then
  echo "Scylla image not found locally, pulling the image..."
  docker pull scylladb/scylla
  if [ $? -ne 0 ]; then
    echo "Error: Failed to pull the Scylla image"
    exit 1
  fi
else
  echo "Scylla image already exists locally."
fi

#Run ScyllaDB docker imgae
echo "Running ScyllaDB..."
docker run -d --name scylla -p 9042:9042 scylladb/scylla
echo "Waiting for ScyllaDB to initialize..."
sleep 30 

# Variables
CQLSH_HOST="127.0.0.1" 
CQLSH_PORT="9042"      
KEYSPACE_NAME="wtc_prod"

echo "Using keyspace: $KEYSPACE_NAME"

CQL_COMMANDS=$(cat <<EOF
CREATE KEYSPACE IF NOT EXISTS ${KEYSPACE_NAME}
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 3};

USE ${KEYSPACE_NAME};

CREATE TABLE IF NOT EXISTS cdr_summary (
    msisdn text,
    usage_type text,
    total_bytes_up bigint,
    total_bytes_down bigint,
    call_cost_zar float,
    data_cost_zar float,
    event_time timestamp,
    PRIMARY KEY (msisdn, usage_type)
);
EOF
)

# Execute CQL commands
echo "Executing CQL commands..."
echo "$CQL_COMMANDS" | cqlsh $CQLSH_HOST $CQLSH_PORT

echo "Executing App"
wait
