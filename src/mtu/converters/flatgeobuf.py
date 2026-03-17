"""
FlatGeobuf converter using fiona.
"""

import tempfile
from pathlib import Path
from typing import Any

from mtu.converters.base import BaseConverter, ConversionResult
from mtu.converters.registry import register_converter


@register_converter
class FlatGeobufConverter(BaseConverter):
    """Converter for FlatGeobuf files."""

    format_name = "FlatGeobuf"
    file_extensions = [".fgb"]
    mime_types = ["application/flatgeobuf"]
    requires_packages = ["fiona"]

    def convert(
        self,
        source: str | Path | dict[str, Any],
        **options: Any,
    ) -> ConversionResult:
        """
        Convert FlatGeobuf to GeoJSON.

        Args:
            source: Path to .fgb file.
            **options: Additional options.

        Returns:
            ConversionResult with the GeoJSON data.
        """
        import fiona

        warnings: list[str] = []
        self.validate_source(source)

        path = Path(source)
        features = []
        metadata: dict[str, Any] = {}

        try:
            with fiona.open(str(path)) as src:
                # Check CRS
                if src.crs:
                    crs_str = str(src.crs)
                    if "4326" not in crs_str and "WGS" not in crs_str.upper():
                        warnings.append(
                            f"CRS is {crs_str}, not WGS84. "
                            "Data may need reprojection for web mapping."
                        )
                    metadata["crs"] = crs_str

                for feature in src:
                    geom = dict(feature.get("geometry", {}))
                    props = dict(feature.get("properties", {}))

                    if not geom or geom.get("type") is None:
                        warnings.append("Feature with null geometry skipped")
                        continue

                    feat: dict[str, Any] = {
                        "type": "Feature",
                        "geometry": geom,
                        "properties": props,
                    }

                    if feature.get("id") is not None:
                        feat["id"] = feature["id"]

                    features.append(feat)

        except Exception as e:
            raise ValueError(f"Failed to read FlatGeobuf: {e}")

        geojson = {"type": "FeatureCollection", "features": features}
        geojson, norm_warnings = self.normalize_geojson_for_json(geojson)
        warnings.extend(norm_warnings)

        return ConversionResult(
            geojson=geojson,
            source_format="FlatGeobuf",
            feature_count=len(features),
            warnings=warnings,
            metadata=metadata,
        )

    def convert_from_bytes(
        self,
        data: bytes,
        **options: Any,
    ) -> ConversionResult:
        """Convert FlatGeobuf from bytes."""
        with tempfile.NamedTemporaryFile(suffix=".fgb", delete=False) as f:
            f.write(data)
            temp_path = Path(f.name)

        try:
            return self.convert(temp_path, **options)
        finally:
            temp_path.unlink(missing_ok=True)
