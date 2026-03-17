"""
Base converter interface for GIS format conversion.
"""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from pathlib import Path as SysPath
from typing import Any


@dataclass
class ConversionResult:
    """Result of a format conversion operation."""

    geojson: dict[str, Any]
    """The converted GeoJSON data."""

    source_format: str
    """Original format name."""

    feature_count: int
    """Number of features converted."""

    warnings: list[str] = field(default_factory=list)
    """Non-fatal warnings encountered during conversion."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata from the source file."""

    def __post_init__(self) -> None:
        """Validate the result after initialization."""
        if not isinstance(self.geojson, dict):
            raise ValueError("geojson must be a dictionary")
        if self.geojson.get("type") not in (
            "FeatureCollection",
            "Feature",
            "GeometryCollection",
            "Point",
            "MultiPoint",
            "LineString",
            "MultiLineString",
            "Polygon",
            "MultiPolygon",
        ):
            raise ValueError(f"Invalid GeoJSON type: {self.geojson.get('type')}")


class BaseConverter(ABC):
    """
    Abstract base class for GIS format converters.

    All format-specific converters must inherit from this class
    and implement the required abstract methods.
    """

    # Class-level format metadata
    format_name: str = "Unknown"
    file_extensions: list[str] = []
    mime_types: list[str] = []
    requires_packages: list[str] = []

    def __init__(self) -> None:
        """Initialize the converter."""
        self._check_dependencies()

    def _check_dependencies(self) -> None:
        """Check if required packages are installed."""
        missing = []
        for package in self.requires_packages:
            try:
                __import__(package.replace("-", "_"))
            except ImportError:
                missing.append(package)

        if missing:
            extra_name = self.format_name.lower().replace(" ", "-")
            raise ImportError(
                f"Missing required packages for {self.format_name}: {', '.join(missing)}. "
                f"Install with: pip install mtu[{extra_name}]"
            )

    @classmethod
    def can_handle(cls, file_path: str | Path) -> bool:
        """
        Check if this converter can handle the given file.

        Args:
            file_path: Path to the file to check.

        Returns:
            True if this converter can handle the file.
        """
        path = Path(file_path)
        suffix = path.suffix.lower()

        # Handle compound extensions like .tar.gz
        if suffix in (".gz", ".zip"):
            suffix = "".join(path.suffixes[-2:]).lower()

        return suffix in cls.file_extensions

    @abstractmethod
    def convert(
        self,
        source: str | Path | dict[str, Any],
        **options: Any,
    ) -> ConversionResult:
        """
        Convert the source to GeoJSON.

        Args:
            source: File path, URL, or data dictionary to convert.
            **options: Format-specific conversion options.

        Returns:
            ConversionResult containing the GeoJSON and metadata.

        Raises:
            ValueError: If the source is invalid.
            IOError: If the file cannot be read.
        """
        pass

    @abstractmethod
    def convert_from_bytes(
        self,
        data: bytes,
        **options: Any,
    ) -> ConversionResult:
        """
        Convert raw bytes to GeoJSON.

        Args:
            data: Raw file bytes.
            **options: Format-specific conversion options.

        Returns:
            ConversionResult containing the GeoJSON and metadata.
        """
        pass

    def validate_source(self, source: str | Path | dict[str, Any]) -> None:
        """
        Validate the source before conversion.

        Args:
            source: Source to validate.

        Raises:
            ValueError: If source is invalid.
            FileNotFoundError: If file doesn't exist.
        """
        if isinstance(source, dict):
            return  # Assume valid data dict

        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {source}")

        if not self.can_handle(path):
            raise ValueError(
                f"Cannot handle file type: {path.suffix}. "
                f"Supported: {', '.join(self.file_extensions)}"
            )

    @classmethod
    def get_info(cls) -> dict[str, Any]:
        """
        Get converter information.

        Returns:
            Dictionary with converter metadata.
        """
        return {
            "format_name": cls.format_name,
            "file_extensions": cls.file_extensions,
            "mime_types": cls.mime_types,
            "requires_packages": cls.requires_packages,
        }

    def normalize_geojson_for_json(
        self,
        geojson: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        """
        Normalize GeoJSON values to JSON-serializable primitives.

        This ensures values from source formats (for example date/time objects
        from DBF/Fiona-backed properties) can always be serialized safely.
        """
        warnings: list[str] = []
        normalized = self._normalize_json_value(geojson, "$", warnings)
        if not isinstance(normalized, dict):
            raise ValueError("Converted GeoJSON root must be an object")
        return normalized, warnings

    def _normalize_json_value(
        self,
        value: Any,
        path: str,
        warnings: list[str],
    ) -> Any:
        """Recursively convert values to JSON-safe primitives."""
        if value is None or isinstance(value, (str, int, bool)):
            return value

        if isinstance(value, float):
            if not math.isfinite(value):
                warnings.append(f"Non-finite float at {path} converted to null")
                return None
            return value

        if isinstance(value, (datetime, date, time)):
            return value.isoformat()

        if isinstance(value, Decimal):
            return float(value)

        if isinstance(value, (bytes, bytearray, memoryview)):
            warnings.append(f"Binary value at {path} converted to UTF-8 text")
            return bytes(value).decode("utf-8", errors="replace")

        if isinstance(value, SysPath):
            return str(value)

        if isinstance(value, dict):
            normalized_dict: dict[str, Any] = {}
            for key, item in value.items():
                key_str = key if isinstance(key, str) else str(key)
                if not isinstance(key, str):
                    warnings.append(
                        f"Non-string object key at {path} converted to '{key_str}'"
                    )
                normalized_dict[key_str] = self._normalize_json_value(
                    item,
                    f"{path}.{key_str}",
                    warnings,
                )
            return normalized_dict

        if isinstance(value, (list, tuple, set, frozenset)):
            return [
                self._normalize_json_value(item, f"{path}[{idx}]", warnings)
                for idx, item in enumerate(value)
            ]

        warnings.append(
            f"Unsupported value type {type(value).__name__} at {path} converted to string"
        )
        return str(value)
