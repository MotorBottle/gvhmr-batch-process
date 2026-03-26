from __future__ import annotations

import json
from datetime import datetime
from datetime import timezone

from gvhmr_batch_worker.config import WorkerSettings


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def main() -> None:
    settings = WorkerSettings()
    if not settings.healthcheck_file.exists():
        raise SystemExit("healthcheck file is missing")

    payload = json.loads(settings.healthcheck_file.read_text(encoding="utf-8"))
    updated_at = _parse_timestamp(payload["updated_at"])
    age_seconds = (datetime.now(timezone.utc) - updated_at).total_seconds()
    if age_seconds > settings.healthcheck_max_age_seconds:
        raise SystemExit(
            f"healthcheck state is stale: age_seconds={age_seconds:.3f} "
            f"threshold={settings.healthcheck_max_age_seconds}"
        )

    if payload.get("status") == "fatal":
        raise SystemExit(payload.get("detail") or "worker is in fatal state")

    if settings.runner_backend != "mock":
        import torch

        if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
            raise SystemExit("CUDA is unavailable inside worker container")


if __name__ == "__main__":
    main()
