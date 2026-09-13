"""Runs the attack plan stages on the device one by one."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence

from .client import DeviceClient, DeviceConnectionError, DeviceProtocolError
from .models import DeviceState, AttackStage, Attack


class OrchestratorError(Exception):
    """Base error for orchestrator failures."""


class NoCompatiblePlanError(OrchestratorError):
    """Raised when no attack plan supports the device version."""


class StageStatus(Enum):
    """The result of running a single attack stage."""

    SUCCESS = "success"
    FAILED = "failed"
    DROPPED = "dropped"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class StageResult:
    """The outcome of a single stage execution."""

    stage: AttackStage
    status: StageStatus
    error: Optional[str] = None


@dataclass
class AttackResult:
    """The overall outcome of running an attack plan."""

    plan: Attack
    stage_results: List[StageResult] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        """Checks if all stages finished successfully."""
        return bool(self.stage_results) and all(
            result.status == StageStatus.SUCCESS for result in self.stage_results
        )

    @property
    def failed_stage(self) -> Optional[StageResult]:
        """Returns the first failed or dropped stage, if any."""
        for result in self.stage_results:
            if result.status in (StageStatus.FAILED, StageStatus.DROPPED):
                return result
        return None


class AttackOrchestrator:
    """Selects and runs attack plans against a target device."""

    def __init__(self, client: DeviceClient) -> None:
        """Initializes with an active device client."""
        self._client = client

    def select_plan(
        self, device: DeviceState, plans: Sequence[Attack]
    ) -> Attack:
        """Finds the first plan compatible with the device version."""
        for plan in plans:
            if plan.is_compatible(device):
                return plan
        raise NoCompatiblePlanError(
            f"No attack plan supports iOS {device.ios_version_string}"
        )

    def run(
        self, plan: Attack, device: Optional[DeviceState] = None
    ) -> AttackResult:
        """Runs all stages in the plan sequentially."""
        if device is not None and not plan.is_compatible(device):
            raise OrchestratorError(
                f"Device iOS {device.ios_version_string} is outside plan bounds "
                f"{plan.min_ios_version}-{plan.max_ios_version}"
            )

        results: List[StageResult] = []
        stopped = False

        for stage in plan.stages:
            if stopped:
                results.append(StageResult(stage=stage, status=StageStatus.SKIPPED))
                continue

            try:
                succeeded = self._client.execute_stage(stage.stage_id)
            except DeviceConnectionError as exc:
                results.append(
                    StageResult(stage=stage, status=StageStatus.DROPPED, error=str(exc))
                )
                stopped = True
                continue
            except DeviceProtocolError as exc:
                results.append(
                    StageResult(stage=stage, status=StageStatus.FAILED, error=str(exc))
                )
                stopped = True
                continue

            if succeeded:
                results.append(StageResult(stage=stage, status=StageStatus.SUCCESS))
            else:
                results.append(StageResult(stage=stage, status=StageStatus.FAILED))
                stopped = True

        return AttackResult(plan=plan, stage_results=results)