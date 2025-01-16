import csv
from faker import Faker
from faker.providers import phone_number
from faker.providers import file
import random
from datetime import datetime, timedelta
import time
from pathlib import PosixPath
import paramiko
from paramiko import SSHClient
import os
import stat
import logging
import json
from kafka import KafkaProducer
from kafka.errors import KafkaError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S ')
#Added this two line for paraiko logging and kafka logging
logging.getLogger('parimiko').setLevel(level=logging.WARN)
logging.getLogger('kafka').setLevel(level=logging.ERROR)

environment = 'dev' if os.getenv('USER', '') != '' else 'prod'

# Config Data
if environment == 'dev':
    SFTP_HOSTNAME = "localhost"  # Replace with your SFTP server address
    SFTP_PORT = 10022  # Default SFTP port
else:
    SFTP_HOSTNAME = "sftp"  # Replace with your SFTP server address
    SFTP_PORT = 22  # Default SFTP port

SFTP_USERNAME = "cdr_data"  # Replace with your SFTP username
SFTP_PASSWORD = "password"  # Replace with your SFTP password
SLEEP_TIME = 1

# Added Kafka Configuration
if environment == 'dev':
    KAFKA_SERVERS = ['localhost:19092', 'localhost:29092', 'localhost:39092']
    TOPIC_DATA = 'cdr_data'
    TOPIC_VOICE = 'cdr_voice'
else:
    KAFKA_SERVERS = ['redpanda-0:9092', 'redpanda-1:9092', 'redpanda-2:9092']
    TOPIC_DATA = 'cdr-data'
    TOPIC_VOICE = 'cdr-voice'


if environment == 'dev':
    TOTAL_SECONDS = 86400 * 1
    LINE_COUNT = 1000
    LINES_PER_SECOND = 1
    FILE_COUNT = int(round((TOTAL_SECONDS * LINES_PER_SECOND) / LINE_COUNT))
else:
    TOTAL_SECONDS = 86400 * 2
    LINE_COUNT = 1000
    LINES_PER_SECOND = 5
    FILE_COUNT = int(round((TOTAL_SECONDS * LINES_PER_SECOND) / LINE_COUNT))

import socket

try:
    socket.gethostbyname(SFTP_HOSTNAME)
    logger.info(f"Hostname {SFTP_HOSTNAME} resolved successfully.")
except socket.error as e:
    logger.error(f"Hostname {SFTP_HOSTNAME} could not be resolved: {e}")

logger.info(f"TOTAL_SECONDS={TOTAL_SECONDS}")
logger.info(f"LINE_COUNT={LINE_COUNT}")
logger.info(f"LINES_PER_SECOND={LINES_PER_SECOND}")
logger.info(f"FILE_COUNT={FILE_COUNT}")

INTERVAL_TIME_SEC = round((TOTAL_SECONDS / FILE_COUNT), 0)
logger.info(f"Interval time [{INTERVAL_TIME_SEC}ms]")
if INTERVAL_TIME_SEC == 0:
    raise Exception(f"INTERVAL_TIME_SEC can not be 0")

fake = Faker()
fake.add_provider(phone_number)
fake.add_provider(file)
Faker.seed(418001)
random.seed(27418001)

MSISDN_COUNT = 50000
IP_ADDRESS_COUNT = 500000
WEBSITE_URL_COUNT = 500000
DEST_NR_COUNT = 100000

logger.info("Generating faker data...")
MSISDNS = [fake.msisdn() for _ in range(MSISDN_COUNT)]
IP_ADDRESSES = [fake.ipv4_public() for _ in range(MSISDN_COUNT)]
WEBSITE_URLS = [fake.url() for _ in range(MSISDN_COUNT)]
DEST_NRS = [fake.msisdn() for _ in range(MSISDN_COUNT)]
logger.info("Faker data created...")

cdr_voice_counter = 0
cdr_data_counter = 0

def ensure_write_permission(file_path):
    if not os.access(file_path, os.W_OK):
        try:
            os.chmod(file_path, stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
            logger.info(f"Changed permissions for file: {file_path}")
        except Exception as e:
            logger.error(f"Failed to change permissions for file: {file_path} - {e}")

def store_idx(idx):
    try:
        ensure_write_permission("idx_data.dat")
        with open("idx_data.dat", mode='+w') as f:
            f.write(f"{idx}\n")
        logger.info(f"Successfully stored idx: {idx}")
    except PermissionError as e:
        logger.error(f"Permission denied for file: idx_data.dat - {e}")
    except Exception as e:
        logger.error(f"An error occurred while storing idx: {e}")

def read_last_idx() -> int:
    idx_file = PosixPath('idx_data.dat')
    if not idx_file.exists():
        return 0

    try:
        ensure_write_permission("idx_data.dat")
        with open(idx_file, mode='+r') as f:
            lines = f.readlines()
            return int(lines[0])
    except PermissionError as e:
        logger.error(f"Permission denied for file: idx_data.dat - {e}")
    except Exception as e:
        logger.error(f"An error occurred while reading idx: {e}")
        return 0

def upload_file_to_sftp(local_file, remote_file):
    for i in range(10):
        try:
            ssh = SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(hostname=SFTP_HOSTNAME, port=SFTP_PORT, username=SFTP_USERNAME, password=SFTP_PASSWORD, disabled_algorithms={'keys': ['rsa-sha2-256', 'rsa-sha2-512']})
            sftp = ssh.open_sftp()
            sftp.put(local_file, remote_file)
            logger.debug(f"File '{local_file}' successfully uploaded to '{remote_file}'.")
            sftp.close()
            ssh.close()
            time.sleep(2)
            return
        except PermissionError as e:
            logger.error(f"Permission denied for file: {local_file} - {e}")
        except Exception as e:
            logger.error(f"An upload error occurred: {e}")
        time.sleep(1)

def generate_cdr_data(file_datetime, num_records):
    data_types = ['video', 'audio', 'image', 'text', 'application']

    cdr_records = []
    for _ in range(num_records):
        record = {
            "msisdn": random.choice(MSISDNS),
            "tower_id": random.randint(1, 2000),
            "up_bytes": random.randint(100000, 1000000),
            "down_bytes": random.randint(100000, 1000000),
            "data_type": random.choice(data_types),
            "ip_address": random.choice(IP_ADDRESSES),
            "website_url": random.choice(WEBSITE_URLS),
            "event_datetime": fake.date_time_between(start_date=file_datetime, end_date=(file_datetime + timedelta(seconds=INTERVAL_TIME_SEC)))
        }
        cdr_records.append(record)

    logger.debug(f"Completed generating [{num_records}] cdr_data records")
    return cdr_records

def generate_cdr_voice(file_datetime, num_records):
    call_types = ['voice', 'video']

    cdr_records = []
    for _ in range(num_records):
        record = {
            "msisdn": random.choice(MSISDNS),
            "tower_id": random.randint(1, 2000),
            "call_type": random.choice(call_types),
            "dest_nr": random.choice(DEST_NRS),
            "call_duration_sec": random.randint(1, 1800),
            "start_time": fake.date_time_between(start_date=file_datetime, end_date=(file_datetime + timedelta(seconds=INTERVAL_TIME_SEC)))
        }
        cdr_records.append(record)

    logger.debug(f"Completed generating [{num_records}] cdr_voice records")
    return cdr_records

#Added helper functions for kafka
def json_serializer(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()  # Convert datetime to ISO 8601 string
    raise TypeError(f"Type {type(obj)} not serializable")

def connect_to_kafka():
    def serializer(v):
        return json.dumps(v, default=json_serializer).encode('utf-8')
    producer = KafkaProducer(
        bootstrap_servers= KAFKA_SERVERS,
        key_serializer=serializer,
        value_serializer=serializer
    )
    logger.info('Producer constructed...')
    return producer

def produce_to_kafka(producer, topic, key, record):
    for attempt in range(100):
        future = producer.send(topic, key=key, value=record)
        try:
            result = future.get(timeout=10)
            logger.debug(f"Produced record: {result}")
            return
        except KafkaError as error:
            logger.error(f"Failed to produce the message: {error}")
            time.sleep(0.5)


file_datetime = datetime(2024, 1, 1, 0, 0, 0)
last_idx = read_last_idx()
logger.info(f"Loaded last_idx: {last_idx}")
STARTING = True

start_time = None

#Added new code below for taking data from sftp to redpanda 
producer = connect_to_kafka()
logger.info("Starting CDR data generation...")

for idx in range(FILE_COUNT):
    start_time = time.time()
    file_datetime = file_datetime + timedelta(seconds=INTERVAL_TIME_SEC)
    logger.debug(f"Generating data for [{file_datetime}]")
    run_active = (not idx < last_idx)

    if run_active and STARTING:
        logger.info(f'Starting at idx: {idx}')
        STARTING = False

    cdr_data = generate_cdr_data(file_datetime=file_datetime, num_records=LINE_COUNT)
    cdr_data_counter += len(cdr_data)
    cdr_voice = generate_cdr_voice(file_datetime=file_datetime, num_records=LINE_COUNT)
    cdr_voice_counter += len(cdr_voice)
    
    #Added this code
    for record in cdr_data:
        key = f"{record['msisdn']}-{record['event_datetime']:%Y-%m-%d %H:%M}"  
        produce_to_kafka(producer, TOPIC_DATA, key, record)

    cdr_voice = generate_cdr_voice(file_datetime=file_datetime, num_records=LINE_COUNT)
    cdr_voice_counter += len(cdr_voice)
    # added more for process of sftp to Redpanda

    for record in cdr_voice:
        key = f"{record['msisdn']}-{record['start_time']:%Y-%m-%d %H:%M}"  # Use start_time
        produce_to_kafka(producer, TOPIC_VOICE, key, record)

 
    if run_active:
        try:
            ensure_write_permission('cdr_data.csv')
            with open('cdr_data.csv', mode='w', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=["msisdn", "tower_id", "up_bytes", "down_bytes", "data_type", "ip_address", "website_url", "event_datetime"])
                writer.writeheader()
                writer.writerows(cdr_data)
            logger.debug('Completed writing out cdr_data.csv')
        except PermissionError as e:
            logger.error(f"Permission denied for file: cdr_data.csv - {e}")
        except Exception as e:
            logger.error(f"An error occurred while writing cdr_data.csv: {e}")

        dest_filename = f"cdr_data_{file_datetime.strftime('%Y%m%d_%H%M%S')}.csv"
        upload_file_to_sftp('cdr_data.csv', f"{dest_filename}")

        try:
            ensure_write_permission('cdr_voice.csv')
            with open('cdr_voice.csv', mode='w', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=["msisdn", "tower_id", "call_type", "dest_nr", "call_duration_sec", "start_time"])
                writer.writeheader()
                writer.writerows(cdr_voice)
            logger.debug('Completed writing out cdr_voice.csv')
        except PermissionError as e:
            logger.error(f"Permission denied for file: cdr_voice.csv - {e}")
        except Exception as e:
            logger.error(f"An error occurred while writing cdr_voice.csv: {e}")

        dest_filename = f"cdr_voice_{file_datetime.strftime('%Y%m%d_%H%M%S')}.csv"
        upload_file_to_sftp('cdr_voice.csv', f"{dest_filename}")

        store_idx(idx=idx)
        elapsed_time = (time.time() - start_time) * 1000
        remaining_time = max(0, (SLEEP_TIME * 1000) - elapsed_time)
        if environment == 'prod':
            time.sleep(0.1)

        logger.info('Generated 2 cdr files...')

logger.info(f'Completed data generation. cdr_data [{cdr_data_counter}], cdr_voice [{cdr_voice_counter}], files [{FILE_COUNT}]')
try:
    os.unlink('idx_data.dat')
    logger.info("Successfully deleted idx_data.dat")
except PermissionError as e:
    logger.error(f"Permission denied for file: idx_data.dat - {e}")
except Exception as e:
    logger.error(f"An error occurred while deleting idx_data.dat: {e}")