CREATE TABLE IF NOT EXISTS daily_metrics (
    metric_date DATE NOT NULL,
    metric_name TEXT NOT NULL,
    dimension_key TEXT NOT NULL DEFAULT '',
    dimension_value TEXT NOT NULL DEFAULT '',
    metric_value DOUBLE PRECISION NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (metric_date, metric_name, dimension_key, dimension_value)
);

CREATE INDEX IF NOT EXISTS idx_daily_metrics_lookup
    ON daily_metrics (metric_date, metric_name);
