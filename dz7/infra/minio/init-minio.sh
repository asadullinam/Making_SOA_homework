#!/bin/sh
set -eu

mc alias set local http://minio:9000 minio miniosecret
mc mb --ignore-existing local/movie-analytics
