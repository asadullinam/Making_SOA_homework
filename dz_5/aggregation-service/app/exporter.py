from __future__ import annotations

import io
import logging
from datetime import date

import boto3
import pandas as pd
from botocore.exceptions import BotoCoreError, ClientError
from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings
from app.repository import MetricsRepository

logger = logging.getLogger(__name__)


class ExportService:
    def __init__(self, settings: Settings, repository: MetricsRepository) -> None:
        self.repository = repository
        self.bucket = settings.minio_bucket
        self.s3 = boto3.client(
            "s3",
            endpoint_url=f"http{'s' if settings.minio_secure else ''}://{settings.minio_endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
        )

    @retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def export_for_date(self, target_date: date) -> str:
        key = f"daily/{target_date.isoformat()}/aggregates.csv"
        logger.info("Export started for %s to s3://%s/%s", target_date.isoformat(), self.bucket, key)

        try:
            rows = self.repository.fetch_metrics_for_export(target_date)
            frame = pd.DataFrame(rows)
            if frame.empty:
                frame = pd.DataFrame(
                    [
                        {
                            "metric_date": target_date.isoformat(),
                            "metric_name": "NO_DATA",
                            "dimension_key": "",
                            "dimension_value": "",
                            "metric_value": 0.0,
                            "computed_at": None,
                            "metadata": {},
                        }
                    ]
                )

            buffer = io.StringIO()
            frame.to_csv(buffer, index=False)
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=buffer.getvalue().encode("utf-8"),
                ContentType="text/csv",
            )
        except (BotoCoreError, ClientError):
            logger.exception("S3 export failed for %s", target_date.isoformat())
            raise
        except Exception:
            logger.exception("Export failed for %s", target_date.isoformat())
            raise

        logger.info("Exported %s metric rows to s3://%s/%s", len(frame), self.bucket, key)
        return key
