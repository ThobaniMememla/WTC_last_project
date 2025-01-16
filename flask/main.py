from flask import Flask, request, jsonify
from pydantic import BaseModel, ValidationError
from cassandra.cluster import Cluster
from cassandra.policies import DCAwareRoundRobinPolicy
from typing import List
from datetime import datetime
import logging
import os

app = Flask(__name__)

SCYLLA_CONTACT_POINTS = os.getenv('SCYLLA_CONTACT_POINTS', 'scylla').split(',')
SCYLLA_KEYSPACE = "wtc_prod"
PROTOCOL_VERSION = 4

cluster = Cluster(
    SCYLLA_CONTACT_POINTS,
    load_balancing_policy=DCAwareRoundRobinPolicy(local_dc="datacenter1"),
    protocol_version=PROTOCOL_VERSION
)
session = cluster.connect()
session.set_keyspace(SCYLLA_KEYSPACE)

KAFKA_BROKERS = os.getenv('KAFKA_BROKERS', 'redpanda-0:9092,redpanda-1:9092,redpanda-2:9092').split(',')


class UsageRecord(BaseModel):
    category: str
    usage_type: str
    total: float
    measure: str
    start_time: str

class UsageResponse(BaseModel):
    msisdn: str
    start_time: str
    end_time: str
    usage: List[UsageRecord]

class QueryParams(BaseModel):
    msisdn: str
    start_time: str
    end_time: str

logging.basicConfig(level=logging.INFO)

@app.before_request
def log_requests():
    logging.info(f"Request: {request.method} {request.url}")

@app.after_request
def log_response(response):
    logging.info(f"Response: {response.status_code}")
    return response

@app.route("/data_usage", methods=["GET"])
def get_data_usage():
    try:
        query_params = QueryParams(
            msisdn=request.args.get('msisdn'),
            start_time=request.args.get('start_time'),
            end_time=request.args.get('end_time')
        )
    except ValidationError as e:
        return jsonify(e.errors()), 400

    try:
        start_time_dt = datetime.strptime(query_params.start_time, "%Y%m%d%H%M%S")
        end_time_dt = datetime.strptime(query_params.end_time, "%Y%m%d%H%M%S")
    except ValueError:
        return jsonify({"detail": "Invalid date format. Use YYYYMMDDHHMMSS."}), 400

    query_str = """
    SELECT category, usage_type, total, measure, start_time
    FROM cdr_summary
    WHERE msisdn = %s AND start_time >= %s AND start_time <= %s
    """
    rows = session.execute(query_str, (query_params.msisdn, start_time_dt, end_time_dt))

    if not rows:
        return jsonify(UsageResponse(
            msisdn=query_params.msisdn,
            start_time=start_time_dt.isoformat(),
            end_time=end_time_dt.isoformat(),
            usage=[]
        ).dict())

    usage_records = [
        UsageRecord(
            category=row.category,
            usage_type=row.usage_type,
            total=row.total,
            measure=row.measure,
            start_time=row.start_time.isoformat()
        )
        for row in rows
    ]

    return jsonify(UsageResponse(
        msisdn=query_params.msisdn,
        start_time=start_time_dt.isoformat(),
        end_time=end_time_dt.isoformat(),
        usage=usage_records
    ).dict())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)