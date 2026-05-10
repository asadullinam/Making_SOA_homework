CREATE DATABASE IF NOT EXISTS movie_analytics;

CREATE TABLE IF NOT EXISTS movie_analytics.movie_events_queue
(
    event_id UUID,
    user_id String,
    movie_id String,
    event_type LowCardinality(String),
    timestamp DateTime64(3, 'UTC'),
    device_type LowCardinality(String),
    session_id String,
    progress_seconds Nullable(Int32),
    search_query Nullable(String),
    schema_version Int32
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'kafka-1:9092,kafka-2:9092',
    kafka_topic_list = 'movie-events',
    kafka_group_name = 'clickhouse-movie-events',
    kafka_format = 'AvroConfluent',
    kafka_num_consumers = 1,
    kafka_thread_per_consumer = 0,
    format_avro_schema_registry_url = 'http://schema-registry:8081';

CREATE TABLE IF NOT EXISTS movie_analytics.movie_events
(
    event_date Date DEFAULT toDate(timestamp),
    event_id UUID,
    user_id String,
    movie_id String,
    event_type LowCardinality(String),
    timestamp DateTime64(3, 'UTC'),
    device_type LowCardinality(String),
    session_id String,
    progress_seconds Nullable(Int32),
    search_query Nullable(String),
    schema_version Int32
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_date)
ORDER BY (event_date, user_id, timestamp, event_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS movie_analytics.movie_events_mv
TO movie_analytics.movie_events
AS
SELECT
    toDate(timestamp) AS event_date,
    event_id,
    user_id,
    movie_id,
    event_type,
    timestamp,
    device_type,
    session_id,
    progress_seconds,
    search_query,
    schema_version
FROM movie_analytics.movie_events_queue;

CREATE TABLE IF NOT EXISTS movie_analytics.daily_dau
(
    metric_date Date,
    dau UInt64,
    computed_at DateTime('UTC')
)
ENGINE = ReplacingMergeTree(computed_at)
ORDER BY metric_date;

CREATE TABLE IF NOT EXISTS movie_analytics.daily_avg_watch_time
(
    metric_date Date,
    avg_watch_seconds Float64,
    computed_at DateTime('UTC')
)
ENGINE = ReplacingMergeTree(computed_at)
ORDER BY metric_date;

CREATE TABLE IF NOT EXISTS movie_analytics.daily_top_movies
(
    metric_date Date,
    movie_id String,
    views UInt64,
    rank UInt8,
    computed_at DateTime('UTC')
)
ENGINE = ReplacingMergeTree(computed_at)
ORDER BY (metric_date, rank, movie_id);

CREATE TABLE IF NOT EXISTS movie_analytics.daily_conversion
(
    metric_date Date,
    started UInt64,
    finished UInt64,
    conversion_rate Float64,
    computed_at DateTime('UTC')
)
ENGINE = ReplacingMergeTree(computed_at)
ORDER BY metric_date;

CREATE TABLE IF NOT EXISTS movie_analytics.daily_retention
(
    metric_date Date,
    retention_d1 Float64,
    retention_d7 Float64,
    computed_at DateTime('UTC')
)
ENGINE = ReplacingMergeTree(computed_at)
ORDER BY metric_date;

CREATE TABLE IF NOT EXISTS movie_analytics.device_distribution
(
    metric_date Date,
    device_type LowCardinality(String),
    events UInt64,
    computed_at DateTime('UTC')
)
ENGINE = ReplacingMergeTree(computed_at)
ORDER BY (metric_date, device_type);

CREATE TABLE IF NOT EXISTS movie_analytics.retention_cohorts
(
    cohort_date Date,
    lifecycle_day UInt8,
    users UInt64,
    cohort_size UInt64,
    retention_rate Float64,
    computed_at DateTime('UTC')
)
ENGINE = ReplacingMergeTree(computed_at)
ORDER BY (cohort_date, lifecycle_day);
