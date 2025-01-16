import os
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from cassandra.cluster import Cluster
from confluent_kafka import Consumer, Producer


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

    
# KAFKA________________________________________________________________________________________________________________
@dataclass
class Config:
    environment: str 
    kafka_servers: List[str] 
    topic_data: str 
    keyspace_name: str 

@dataclass
class UsageSummary:
    total_bytes_up: int
    total_bytes_down: int
    call_cost_zar: float
    data_cost_zar: float

def create_config(environment: str = os.getenv('ENVIRONMENT', 'dev')) -> Config:
    return Config(
        environment=environment,
        kafka_servers=['localhost:19092', 'localhost:9092', 'localhost:39092'] 
            if environment == 'dev' 
            else ['redpanda-0:9092', 'redpanda-1:9092', 'redpanda-2:9092'],
        topic_data='cdr_data' if environment == 'dev' else 'cdr-data',
        keyspace_name = 'wtc_prod'
    )

def create_kafka_producer(config: Config) -> Optional[Producer]:
    try:
        producer = Producer({
            'bootstrap.servers': ','.join(config.kafka_servers),
        })
        logger.info("Kafka producer created successfully.")
        return producer
    except Exception as e:
        logger(f"Failed to create Kafka producer: {e}")
        return None
    
def send_message_to_kafka(producer: Producer, topic: str, key: str, value: dict):
    try:
        producer.produce(
            topic,
            key=key,
            value=json.dumps(value),
            callback=delivery_report
        )
        producer.flush()
    except Exception as e:
        logger.error(f"Failed to send message to Kafka: {e}")    
    
def delivery_report(err, msg):
    if err is not None:
        logger.error(f"Message delivery failed: {err}")
    else:
        logger.info(f"Message delivered to {msg.topic()} [{msg.partition()}]")    
    
def create_kafka_consumer(config: Config) -> Optional[Consumer]:
    try:
        consumer = Consumer({
            'bootstrap.servers': ','.join(config.kafka_servers),
            'group.id': 'cdr-consumer',
            'auto.offset.reset': 'earliest',
        })
        consumer.subscribe([config.topic_data])
        logger.info("Kafka consumer created and subscribed to topics.")
        return consumer
    except Exception as e:
        logger.error(f"Failed to create Kafka consumer: {e}")
        return None

def calculate_voice_usage(duration: float) -> UsageSummary:
    """Pure function to calculate voice usage"""
    return UsageSummary(
        total_bytes_up=0,
        total_bytes_down=0,
        call_cost_zar=duration / 60,
        data_cost_zar=0.0
    )

def calculate_data_usage(bytes_up: int, bytes_down: int) -> UsageSummary:
    """Pure function to calculate data usage"""
    total_bytes = bytes_up + bytes_down
    return UsageSummary(
        total_bytes_up=bytes_up,
        total_bytes_down=bytes_down,
        call_cost_zar=0.0,
        data_cost_zar=(total_bytes / 1e9) * 49
    )

def process_cdr_message(message: dict) -> Tuple[str, UsageSummary]:
    """Pure function to process a CDR message and return a tuple of (msisdn, usage)"""
    msisdn = message['msisdn']
    usage = (calculate_voice_usage(message['duration']) 
            if message['usage_type'] == 'voice'
            else calculate_data_usage(message['bytes_up'], message['bytes_down']))
    return msisdn, usage

def process_kafka_message(msg) -> Optional[dict]:
    """Pure function to process a Kafka message"""
    if msg is None or msg.error():
        return None
    try:
        return json.loads(msg.value().decode('utf-8'))
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        return None
    
def handle_processed_cdr(msisdn: str, usage: UsageSummary, producer: Producer, config: Config):
    if producer:
        summary_topic = 'cdr_summary' if config.environment == 'dev' else 'cdr_summary'
        message = {
            'msisdn': msisdn,
            'usage': usage.__dict__,
            'timestamp': datetime.utcnow().isoformat(),
        }
        send_message_to_kafka(producer, summary_topic, key=msisdn, value=message)
    
    
# Scylla_______________________________________________________________________________________________________________
def create_scylla_session() -> Optional[Tuple[Cluster, any]]:
    """Create a ScyllaDB session"""
    try:
        cluster = Cluster(['127.0.0.1'])
        session = cluster.connect()
        logger.info("Connected to ScyllaDB!")
        return cluster, session
    except Exception as e:
        logger.error(f"Failed to connect to ScyllaDB: {e}")
        return None

def initialize_schema(session) -> None:
    """Set up the database schema"""
    session.execute(f'''
        CREATE KEYSPACE IF NOT EXISTS {'wtc_prod'}
        WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': 3}};
    ''')
    session.set_keyspace('wtc_prod')
    session.execute('''
        CREATE TABLE IF NOT EXISTS cdr_summary (
            msisdn text PRIMARY KEY,
            total_bytes_up bigint,
            total_bytes_down bigint,
            call_cost_zar float,
            data_cost_zar float,
            event_time timestamp
        );
    ''')
    logger.info("Schema setup complete.")

def write_to_scylla(session, msisdn: str, summary: UsageSummary, timestamp: datetime) -> bool:
    try:
        session.execute("""
            INSERT INTO cdr_summary (msisdn, total_bytes_up, total_bytes_down, 
                                   call_cost_zar, data_cost_zar, event_time)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (msisdn, summary.total_bytes_up, summary.total_bytes_down, 
              summary.call_cost_zar, summary.data_cost_zar, timestamp))
        logger.info(f"Written to ScyllaDB: {msisdn}")
        return True
    except Exception as e:
        logger.error(f"Failed to write MSISDN {msisdn}: {e}")
        return False


# Main_________________________________________________________________________________________________________________
def main():
    config = create_config()
    scylla_connection = create_scylla_session()
    if not scylla_connection:
        logger.error("Failed to initialize ScyllaDB session.")
        return
    cluster, session = scylla_connection
    initialize_schema(session)

    consumer = create_kafka_consumer(config)
    if not consumer:
        logger.error("Failed to initialize Kafka consumer.")
        return
    
    producer = create_kafka_producer(config)
    if not producer:
        logger.error("Failed to initialize Kafka producer.")
        return

    messages_processed = 0
    last_status_time = time.time()
    status_interval = 5
    logger.info("Consuming Kafka messages...")

    try:
        while True:
            msg = consumer.poll(timeout_ms=1000)
            if msg:

                cdr_message = process_kafka_message(msg)
                if cdr_message:
                    msisdn, usage = process_cdr_message(cdr_message)
                    write_to_scylla(session, msisdn, usage, datetime.now())
                    
                    summary_message = {
                        "msisdn": msisdn,
                        "usage": usage.__dict__,
                        "event_time": datetime.utcnow().isoformat()
                    }
                    send_message_to_kafka(producer, 'cdr_summary', key=msisdn, value=summary_message)
                    
                    messages_processed += 1

                current_time = time.time()
                if current_time - last_status_time >= status_interval:
                    rate = messages_processed / status_interval
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    logger.info(f"[{timestamp}] Processed {messages_processed} messages (Rate: {rate:.2f} messages/sec)")
                    messages_processed = 0
                    last_status_time = current_time
            else:
                logger.error('No messages detected')

    except KeyboardInterrupt:
        final_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"\n[{final_timestamp}] Shutting down gracefully...")
    finally:
        consumer.close()
        cluster.shutdown()
        producer.flush()
        producer.close()


if __name__ == '__main__':
    main()