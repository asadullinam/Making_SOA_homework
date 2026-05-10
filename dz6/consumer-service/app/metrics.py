from prometheus_client import Counter, Gauge, Histogram

consumer_lag = Gauge("consumer_lag", "Kafka consumer lag by partition", ["partition"])
events_processed_total = Counter(
    "events_processed_total",
    "Count of processed warehouse events",
    ["event_type"],
)
event_processing_duration_seconds = Histogram(
    "event_processing_duration_seconds",
    "Duration of single event processing",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
cassandra_write_errors_total = Counter(
    "cassandra_write_errors_total",
    "Count of Cassandra write errors",
)
