#!/bin/sh
set -eu

alias_name=local
endpoint=http://minio:9000

mc alias set "$alias_name" "$endpoint" "$S3_ACCESS_KEY" "$S3_SECRET_KEY"

for bucket in \
  vehicle-originals \
  vehicle-derived \
  vehicle-results \
  vehicle-models \
  vehicle-temporary \
  vehicle-backups
do
  mc mb --ignore-existing "$alias_name/$bucket"
  mc version enable "$alias_name/$bucket"
  mc anonymous set none "$alias_name/$bucket"
done

printf 'MinIO development buckets initialized (CORS via MINIO_API_CORS_ALLOW_ORIGIN).\n'
