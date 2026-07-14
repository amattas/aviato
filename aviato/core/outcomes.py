from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class OperationStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"
    UNATTEMPTED = "unattempted"


@dataclass(frozen=True)
class OperationResult:
    operation_id: str
    kind: str
    path: str
    status: OperationStatus
    detail: str = ""
    before_fingerprint: Any | None = None
    after_fingerprint: Any | None = None


@dataclass(frozen=True)
class TransitionResult:
    journal_id: str
    plan_digest: str
    operations: tuple[OperationResult, ...]
    convergence_accepted: bool = False

    @property
    def success(self) -> bool:
        return self.convergence_accepted and all(
            operation.status is OperationStatus.COMPLETED for operation in self.operations
        )
