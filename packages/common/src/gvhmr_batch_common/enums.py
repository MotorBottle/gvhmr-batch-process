from enum import Enum


class JobStatus(str, Enum):
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class BatchStatus(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    PARTIAL_FAILED = "partial_failed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class WorkerStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    OFFLINE = "offline"


class ArtifactKind(str, Enum):
    INPUT_VIDEO = "input_video"
    PREPROCESS = "preprocess"
    HMR4D_RESULTS = "hmr4d_results"
    RENDER_VIDEO = "render_video"
    JOINTS_JSON = "joints_json"
    LOG = "log"
    ARCHIVE = "archive"


class JobPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class FailureCategory(str, Enum):
    INFRA_TRANSIENT = "infra_transient"
    INFRA_PERMANENT = "infra_permanent"
    ALGORITHM_FAILURE = "algorithm_failure"
    INPUT_INVALID = "input_invalid"
    TIMEOUT = "timeout"
    CANCELED = "canceled"
