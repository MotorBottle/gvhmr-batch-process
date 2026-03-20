from __future__ import annotations

import os
import sys
from pathlib import Path


DEFAULT_GVHMR_ROOT = Path("/app/gvhmr")


def get_gvhmr_root() -> Path:
    return Path(os.environ.get("GVHMR_ROOT", str(DEFAULT_GVHMR_ROOT))).resolve()


def prepare_gvhmr_runtime(*, change_cwd: bool = False) -> Path:
    gvhmr_root = get_gvhmr_root()
    if not gvhmr_root.exists():
        raise FileNotFoundError(f"GVHMR root not found: {gvhmr_root}")

    root_str = str(gvhmr_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    if change_cwd:
        os.chdir(gvhmr_root)

    return gvhmr_root


def body_model_asset_path(filename: str) -> Path:
    return get_gvhmr_root() / "hmr4d" / "utils" / "body_model" / filename
