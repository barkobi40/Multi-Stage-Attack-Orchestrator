"""Domain models for the attack orchestrator's Python framework.

Data classes representing device state and attack plans.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DeviceState:
    """Represents the current state and properties of a target device."""

    ios_major: int
    ios_minor: int
    model: str
    battery_level: int

    def __post_init__(self) -> None:
        if not 0 <= self.battery_level <= 100:
            raise ValueError(f"battery_level must be 0-100, got {self.battery_level}")
        if self.ios_major < 0 or self.ios_minor < 0:
            raise ValueError("iOS version components must be non-negative")

    @property
    def ios_version(self) -> tuple[int, int]:
        """Returns the iOS version as a tuple."""
        return (self.ios_major, self.ios_minor)

    @property
    def ios_version_string(self) -> str:
        """Returns the iOS version formatted as a string."""
        return f"{self.ios_major}.{self.ios_minor}"


@dataclass(frozen=True)
class AttackStage:
    """Represents a single stage within an attack plan."""

    stage_id: int
    stage_name: str
    description: str = ""

    def __post_init__(self) -> None:
        if not 0 <= self.stage_id <= 0xFF:
            raise ValueError(f"stage_id must be 0-255, got {self.stage_id}")
        if not self.stage_name:
            raise ValueError("stage_name must not be empty")


@dataclass
class Attack:
    """An ordered sequence of attack stages with device-state requirements."""

    stages: list[AttackStage] = field(default_factory=list)
    min_ios_version: tuple[int, int] = (0, 0)
    max_ios_version: tuple[int, int] = (999, 999)
    min_battery_level: int = 0
    compatible_models: tuple[str, ...] | None = None
    success_probability: float = 1.0

    def __post_init__(self) -> None:
        if self.min_ios_version > self.max_ios_version:
            raise ValueError(
                f"min_ios_version {self.min_ios_version} exceeds "
                f"max_ios_version {self.max_ios_version}"
            )
        stage_ids = [stage.stage_id for stage in self.stages]
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("stages must have unique stage_id values")
        if not 0 <= self.min_battery_level <= 100:
            raise ValueError(
                f"min_battery_level must be 0-100, got {self.min_battery_level}"
            )
        if not 0.0 <= self.success_probability <= 1.0:
            raise ValueError(
                f"success_probability must be 0.0-1.0, got {self.success_probability}"
            )

    def is_compatible(self, device: DeviceState) -> bool:
        """Checks if the device state satisfies this attack's requirements.

        Validates iOS version bounds, minimum battery level, and (when
        restricted) the device model.
        """
        if not self.min_ios_version <= device.ios_version <= self.max_ios_version:
            return False
        if device.battery_level < self.min_battery_level:
            return False
        if self.compatible_models is not None and device.model not in self.compatible_models:
            return False
        return True

    def stage_ids(self) -> list[int]:
        """Returns a list of all stage IDs in order."""
        return [stage.stage_id for stage in self.stages]