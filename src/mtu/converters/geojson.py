"""
GeoJSON converter (native format - passthrough with validation).
"""

import json
from pathlib import Path
from typing import Any

from mtu.converters.base import BaseConverter, ConversionResult
from mtu.converters.registry import register_converter


@register_converter
class GeoJSONConverter(BaseConverter):
    """Converter for GeoJSON files (native format)."""

    format_name = "GeoJSON"
    file_extensions = [".geojson", ".json"]
    mime_types = ["application/geo+json", "application/json"]
    requires_packages: list[str] = []  # Built-in

    def convert(
        self,
        source: str | Path | dict[str, Any],
        **options: Any,
    ) -> ConversionResult:
        """
        Load and validate GeoJSON.

        Args:
            source: File path or GeoJSON dictionary.
            **options: Not used for GeoJSON.

        Returns:
            ConversionResult with the GeoJSON data.
        """
        warnings: list[str] = []

        if isinstance(source, dict):
            geojson = source
        else:
            self.validate_source(source)
            with open(source, encoding="utf-8") as f:
                geojson = json.load(f)

        # Normalize to FeatureCollection
        geojson, norm_warnings = self._normalize_geojson(geojson)
        warnings.extend(norm_warnings)
        geojson, norm_warnings = self.normalize_geojson_for_json(geojson)
        warnings.extend(norm_warnings)

        feature_count = len(geojson.get("features", []))

        return ConversionResult(
            geojson=geojson,
            source_format="GeoJSON",
            feature_count=feature_count,
            warnings=warnings,
        )

    def convert_from_bytes(
        self,
        data: bytes,
        **options: Any,
    ) -> ConversionResult:
        """Convert GeoJSON from bytes."""
        geojson = json.loads(data.decode("utf-8"))
        return self.convert(geojson, **options)

    def _normalize_geojson(
        self,
        geojson: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        """
        Normalize GeoJSON to FeatureCollection.

        Returns:
            Tuple of (normalized GeoJSON, warnings list).
        """
        warnings: list[str] = []
        geojson_type = geojson.get("type")

        if geojson_type == "FeatureCollection":
            return geojson, warnings

        if geojson_type == "Feature":
            warnings.append("Wrapped single Feature in FeatureCollection")
            return {
                "type": "FeatureCollection",
                "features": [geojson],
            }, warnings

        if geojson_type == "GeometryCollection":
            warnings.append("Converted GeometryCollection to FeatureCollection")
            features = [
                {"type": "Feature", "geometry": geom, "properties": {}}
                for geom in geojson.get("geometries", [])
            ]
            return {"type": "FeatureCollection", "features": features}, warnings

        if geojson_type in (
            "Point",
            "MultiPoint",
            "LineString",
            "MultiLineString",
            "Polygon",
            "MultiPolygon",
        ):
            warnings.append(f"Wrapped {geojson_type} geometry in FeatureCollection")
            return {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "geometry": geojson, "properties": {}}],
            }, warnings

        raise ValueError(f"Invalid GeoJSON type: {geojson_type}")
