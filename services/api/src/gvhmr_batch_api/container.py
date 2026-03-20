from __future__ import annotations

from gvhmr_batch_api.config import APISettings
from gvhmr_batch_api.store import SQLControlPlaneStore
from gvhmr_batch_common.database import create_engine_from_dsn, create_session_factory
from gvhmr_batch_common.storage import MinIOStorage

_settings = APISettings()
_engine = create_engine_from_dsn(_settings.postgres_dsn)
_session_factory = create_session_factory(_engine)
_storage = MinIOStorage(
    endpoint=_settings.minio_endpoint,
    access_key=_settings.minio_access_key,
    secret_key=_settings.minio_secret_key,
    bucket=_settings.minio_bucket,
    secure=_settings.minio_secure,
)
_store = SQLControlPlaneStore(_session_factory, _storage)


def get_settings() -> APISettings:
    return _settings


def get_store() -> SQLControlPlaneStore:
    return _store
