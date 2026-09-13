"""Pulls files off a device via DeviceClient.read_device_file and persists them locally."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Iterable, Optional, Union

from .client import DeviceClient, DeviceConnectionError, DeviceProtocolError

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Raised when file extraction fails."""


class DataExtractor:
    """Extracts files from a device and saves them locally."""

    def __init__(self, client: DeviceClient, output_dir: Union[str, Path]) -> None:
        """Sets up the extractor with an active client and target folder."""
        self._client = client
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def extract_file(self, device_path: str, local_name: Optional[str] = None) -> Path:
        """Reads a single file from the device and saves it locally."""
        try:
            data = self._client.read_device_file(device_path)
        except (DeviceProtocolError, DeviceConnectionError) as exc:
            raise ExtractionError(f"Failed to extract {device_path!r}: {exc}") from exc

        name = local_name or Path(device_path).name or "extracted_data.bin"
        dest = self.output_dir / name
        dest.write_bytes(data)
        logger.info("Extracted %d bytes from %s to %s", len(data), device_path, dest)
        return dest

    def extract_files(self, device_paths: Iterable[str]) -> Dict[str, Path]:
        """Extracts multiple files, skipping individual failures."""
        results: Dict[str, Path] = {}
        for device_path in device_paths:
            try:
                results[device_path] = self.extract_file(device_path)
            except ExtractionError as exc:
                logger.warning("%s", exc)
        return results