"""Runs the attack plan stages on the device one by one."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from .client import DeviceClient, DeviceConnectionError, DeviceProtocolError
from .models import Attack, AttackStage, DeviceState


class OrchestratorError(Exception):
    """Base error for orchestrator failures."""


class NoCompatiblePlanError(OrchestratorError):
    """Raised when no attack plan's device-state requirements are met."""


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
    error: str | None = None


@dataclass
class AttackResult:
    """The overall outcome of running an attack plan."""

    plan: Attack
    stage_results: list[StageResult] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        """Checks if all stages finished successfully."""
        return bool(self.stage_results) and all(
            result.status == StageStatus.SUCCESS for result in self.stage_results
        )

    @property
    def failed_stage(self) -> StageResult | None:
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
        """Picks the most viable plan compatible with the device state.

        A plan is viable when the device satisfies its iOS version, battery,
        and model requirements (see `Attack.is_compatible`). When more than
        one plan is viable, the one with the highest `success_probability`
        wins; ties keep the order the plans were given in.
        """
        compatible = [plan for plan in plans if plan.is_compatible(device)]
        if not compatible:
            raise NoCompatiblePlanError(
                f"No attack plan supports device iOS {device.ios_version_string}, "
                f"model {device.model}, battery {device.battery_level}%"
            )
        return max(compatible, key=lambda plan: plan.success_probability)

    def run(
        self, plan: Attack, device: DeviceState | None = None
    ) -> AttackResult:
        """Runs all stages in the plan sequentially."""
        if device is not None and not plan.is_compatible(device):
            raise OrchestratorError(
                f"Device iOS {device.ios_version_string}, model {device.model}, "
                f"battery {device.battery_level}% does not satisfy plan requirements "
                f"(iOS {plan.min_ios_version}-{plan.max_ios_version}, "
                f"min battery {plan.min_battery_level}%, "
                f"models {plan.compatible_models or 'any'})"
            )

        results: list[StageResult] = []
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