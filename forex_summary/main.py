import pandas as pd
from kafka import KafkaConsumer
import json
from datetime import datetime
import logging
import os
import psycopg2

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

environment = 'dev' if os.getenv('USER', '') != '' else 'prod'

if environment == 'dev':
    KAFKA_SERVERS = ['localhost:19092', 'localhost:29092', 'localhost:39092', 'localhost:49092', 'localhost:59092']
    TOPIC_NAME = 'tick-data-dev'
else:
    KAFKA_SERVERS = ['redpanda-0:9092', 'redpanda-1:9092', 'redpanda-2:9092']
    TOPIC_NAME = 'tick-data'

consumer = KafkaConsumer(
    TOPIC_NAME,
    bootstrap_servers=KAFKA_SERVERS,
    auto_offset_reset='earliest',
    enable_auto_commit=True,
    group_id='forex-summary-group',
    value_deserializer=lambda x: json.loads(x.decode('utf-8'))
)
logger.info("Connected to Kafka.")

def calculate_ema(data, period):
    return data.ewm(span=period, adjust=False).mean()

def calculate_atr(data, period):
    high_low = data['high'] - data['low']
    high_close = (data['high'] - data['close'].shift()).abs()
    low_close = (data['low'] - data['close'].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    atr = true_range.rolling(window=period).mean()
    return atr

def summarize_data(df, interval):
    resampled = df.resample(interval).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    })
    resampled['EMA_8'] = calculate_ema(resampled['open'], 8)
    resampled['EMA_21'] = calculate_ema(resampled['open'], 21)
    resampled['ATR_8'] = calculate_atr(resampled, 8)
    resampled['ATR_21'] = calculate_atr(resampled, 21)
    return resampled

def insert_data_to_db(data, conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prepared_layers.forex_summary (
            id SERIAL PRIMARY KEY,
            pair_name VARCHAR(50),
            interval VARCHAR(10),
            timestamp TIMESTAMP,
            open FLOAT,
            high FLOAT,
            low FLOAT,
            close FLOAT,
            ema_8 FLOAT,
            ema_21 FLOAT,
            atr_8 FLOAT,
            atr_21 FLOAT
        );
    """)
    for index, row in data.iterrows():
        cur.execute("""
            INSERT INTO prepared_layers.forex_summary (pair_name, interval, timestamp, open, high, low, close, ema_8, ema_21, atr_8, atr_21)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
        """, (row['pair_name'], row['interval'], index, row['open'], row['high'], row['low'], row['close'], row['EMA_8'], row['EMA_21'], row['ATR_8'], row['ATR_21']))
    conn.commit()
    cur.close()

data = []

try:
    conn = psycopg2.connect(
        dbname="wtc_analytics",
        user="postgres",
        password="your_password",
        host="localhost",
        port="5432"
    )
    logger.info("Connected to PostgreSQL.")

    for message in consumer:
        record = message.value
        timestamp = datetime.strptime(record['timestamp'], '%Y-%m-%d %H:%M:%S.%f')
        pair_name = record['pair_name']
        bid_price = record['bid_price']
        ask_price = record['ask_price']
        spread = record['spread']
        open_price = bid_price  
        close_price = ask_price  
        high_price = max(bid_price, ask_price)
        low_price = min(bid_price, ask_price)
        data.append([timestamp, pair_name, open_price, high_price, low_price, close_price])

        if len(data) % 1000 == 0:  
            df = pd.DataFrame(data, columns=['timestamp', 'pair_name', 'open', 'high', 'low', 'close'])
            df.set_index('timestamp', inplace=True)

            pairs = df['pair_name'].unique()
            summarized_data = []

            for pair in pairs:
                pair_data = df[df['pair_name'] == pair]
                for interval in ['1T', '30T', '1H']:
                    summary = summarize_data(pair_data, interval)
                    summary['pair_name'] = pair
                    summary['interval'] = interval
                    summarized_data.append(summary)

            summarized_df = pd.concat(summarized_data)
            insert_data_to_db(summarized_df, conn)

            data = []

except KeyboardInterrupt:
    logger.info("Consumer stopped.")
finally:
    if conn:
        conn.close()
        logger.info("PostgreSQL connection closed.")

logger.info("Kafka consumer finished.")