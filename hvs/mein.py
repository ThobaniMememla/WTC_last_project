# from cassandra.cluster import Cluster
# import cassandra.io.geventreactor
# cassandra.io.geventreactor.install()

import os
import json
from datetime import datetime
from cassandra.cluster import Cluster
from confluent_kafka import Consumer, KafkaError

# Environment Configuration
environment = os.getenv('ENVIRONMENT', 'dev')
KAFKA_SERVERS = ['localhost:19092', 'localhost:29092', 'localhost:39092'] if environment == 'dev' else ['redpanda-0:9092', 'redpanda-1:9092', 'redpanda-2:9092']
TOPIC_DATA = 'cdr_data' if environment == 'dev' else 'cdr-data'

# Initialize Usage Summary
usage_summary = {}

def connect_to_scylla():
    try:
        cluster = Cluster(['127.0.0.1'])
        session = cluster.connect()
        print("Connected to ScyllaDB!")
        return session
    except Exception as e:
        print(f"Failed to connect to ScyllaDB: {e}")
        return None

def setup_schema(session, keyspace_name='cdr_keyspace'):
    session.execute(f'''
        CREATE KEYSPACE IF NOT EXISTS {keyspace_name}
        WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': 3}};
    ''')
    session.set_keyspace(keyspace_name)
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
    print(f"Schema setup complete for keyspace {keyspace_name}.")

def create_kafka_consumer():
    try:
        consumer = Consumer({
            'bootstrap.servers': ','.join(KAFKA_SERVERS),
            'group.id': 'cdr-consumer',
            'auto.offset.reset': 'earliest',
        })
        consumer.subscribe([TOPIC_DATA])
        print("Kafka consumer created and subscribed to topics.")
        return consumer
    except Exception as e:
        print(f"Failed to create Kafka consumer: {e}")
        return None

def process_cdr_message(cdr_message):
    msisdn = cdr_message['msisdn']
    usage_type = cdr_message['usage_type']
    if msisdn not in usage_summary:
        usage_summary[msisdn] = {'total_bytes_up': 0, 'total_bytes_down': 0, 'call_cost_zar': 0.0, 'data_cost_zar': 0.0}
    if usage_type == 'voice':
        usage_summary[msisdn]['call_cost_zar'] += (cdr_message['duration'] / 60)
    elif usage_type == 'data':
        usage_summary[msisdn]['total_bytes_up'] += cdr_message['bytes_up']
        usage_summary[msisdn]['total_bytes_down'] += cdr_message['bytes_down']
        total_bytes = cdr_message['bytes_up'] + cdr_message['bytes_down']
        usage_summary[msisdn]['data_cost_zar'] += (total_bytes / 1e9) * 49

def publish_summary_to_scylla(session):
    timestamp = datetime.now()
    for msisdn, summary in usage_summary.items():
        try:
            session.execute("""
                INSERT INTO cdr_summary (msisdn, total_bytes_up, total_bytes_down, call_cost_zar, data_cost_zar, event_time)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (msisdn, summary['total_bytes_up'], summary['total_bytes_down'], summary['call_cost_zar'], summary['data_cost_zar'], timestamp))
            print(f"Written to ScyllaDB: {msisdn}")
        except Exception as e:
            print(f"Failed to write MSISDN {msisdn}: {e}")

def main():
    session = connect_to_scylla()
        # if not session:
        #     return
    setup_schema(session)


    # consumer = create_kafka_consumer()
    # if not consumer:
    #     return

    # print("Consuming Kafka messages...")
    # try:
    #     while True:
    #         msg = consumer.poll(timeout=1.0)
    #         if msg is None:
    #             continue
    #         if msg.error():
    #             print(f"Kafka error: {msg.error()}")
    #             continue
    #         cdr_message = json.loads(msg.value().decode('utf-8'))
    #         process_cdr_message(cdr_message)
    #         if len(usage_summary) >= 1:
    #             publish_summary_to_scylla(session)
    #             usage_summary.clear()
    # except KeyboardInterrupt:
    #     print("Shutting down...")
    # finally:
    #     consumer.close()

if __name__ == '__main__':
    main()
