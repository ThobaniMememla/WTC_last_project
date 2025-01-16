from fastapi import FastAPI, HTTPException, Query, Depends
from pydantic import BaseModel
from cassandra.cluster import Cluster
from cassandra.policies import DCAwareRoundRobinPolicy
from typing import List
from datetime import datetime
import logging
from fastapi.middleware.cors import CORSMiddleware
import os
import json
from confluent_kafka import Consumer, Producer


app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React frontend URL
    allow_credentials=True,
    allow_methods=["*"],  
    allow_headers=["*"],  
)


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

@app.middleware("http")
async def log_requests(request, call_next):
    logging.info(f"Request: {request.method} {request.url}")
    response = await call_next(request)
    logging.info(f"Response: {response.status_code}")
    return response

@app.get("/data_usage", response_model=UsageResponse)
async def get_data_usage(
    query: QueryParams = Depends(QueryParams)  
):
    try:
        start_time_dt = datetime.strptime(query.start_time, "%Y%m%d%H%M%S")
        end_time_dt = datetime.strptime(query.end_time, "%Y%m%d%H%M%S")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYYMMDDHHMMSS.")

 
    query_str = """
    SELECT category, usage_type, total, measure, start_time
    FROM cdr_summary
    WHERE msisdn = %s AND start_time >= %s AND start_time <= %s
    """
    rows = session.execute(query_str, (query.msisdn, start_time_dt, end_time_dt))


    if not rows:
        return UsageResponse(
            msisdn=query.msisdn,
            start_time=start_time_dt.isoformat(),
            end_time=end_time_dt.isoformat(),
            usage=[]
        )

   
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


    return UsageResponse(
        msisdn=query.msisdn,
        start_time=start_time_dt.isoformat(),
        end_time=end_time_dt.isoformat(),
        usage=usage_records
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)