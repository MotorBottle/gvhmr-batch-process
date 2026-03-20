from __future__ import annotations

import io
from pathlib import Path
from threading import Lock

from minio import Minio


class MinIOStorage:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        self.bucket = bucket
        self._client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._bucket_lock = Lock()
        self._bucket_ready = False

    def ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        with self._bucket_lock:
            if self._bucket_ready:
                return
            if not self._client.bucket_exists(self.bucket):
                self._client.make_bucket(self.bucket)
            self._bucket_ready = True

    def put_bytes(self, object_name: str, data: bytes, *, content_type: str = "application/octet-stream") -> None:
        self.ensure_bucket()
        payload = io.BytesIO(data)
        self._client.put_object(
            self.bucket,
            object_name,
            payload,
            length=len(data),
            content_type=content_type,
        )

    def fput_file(
        self,
        object_name: str,
        file_path: Path,
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.ensure_bucket()
        self._client.fput_object(
            self.bucket,
            object_name,
            str(file_path),
            content_type=content_type,
        )

    def get_bytes(self, object_name: str) -> bytes:
        self.ensure_bucket()
        response = self._client.get_object(self.bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def download_file(self, object_name: str, destination: Path) -> Path:
        self.ensure_bucket()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._client.fget_object(self.bucket, object_name, str(destination))
        return destination

    def object_exists(self, object_name: str) -> bool:
        self.ensure_bucket()
        try:
            self._client.stat_object(self.bucket, object_name)
        except Exception:
            return False
        return True

