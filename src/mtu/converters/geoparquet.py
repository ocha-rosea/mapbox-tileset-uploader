"""
GeoParquet converter using geopandas.
"""

import json
import tempfile
from pathlib import Path
from typing import Any

from mtu.converters.base import BaseConverter, ConversionResult
from mtu.converters.registry import register_converter


@register_converter
class GeoParquetConverter(BaseConverter):
    """Converter for GeoParquet files."""

    format_name = "GeoParquet"
    file_extensions = [".parquet", ".geoparquet"]
    mime_types = ["application/x-parquet", "application/geoparquet"]
    requires_packages = ["geopandas", "pyarrow"]

    def convert(
        self,
        source: str | Path | dict[str, Any],
        **options: Any,
    ) -> ConversionResult:
        """
        Convert GeoParquet to GeoJSON.

        Args:
            source: Path to .parquet or .geoparquet file.
            **options: Additional options passed to geopandas.read_parquet.

        Returns:
            ConversionResult with the GeoJSON data.
        """
        import geopandas as gpd

        warnings: list[str] = []
        self.validate_source(source)

        path = Path(source)
        metadata: dict[str, Any] = {}

        try:
            gdf = gpd.read_parquet(str(path))
        except Exception as e:
            raise ValueError(f"Failed to read GeoParquet: {e}")

        # Check CRS
        if gdf.crs:
            crs_str = str(gdf.crs)
            if gdf.crs.to_epsg() != 4326:
                warnings.append(
                    f"CRS is {crs_str} (EPSG:{gdf.crs.to_epsg()}), not WGS84. "
                    "Data may need reprojection for web mapping."
                )
            metadata["crs"] = crs_str
            metadata["epsg"] = gdf.crs.to_epsg()
        else:
            warnings.append("No CRS defined - assuming WGS84 (EPSG:4326)")

        # Check for null geometries
        null_count = gdf.geometry.isna().sum()
        if null_count > 0:
            warnings.append(f"{null_count} features with null geometry will be skipped")
            gdf = gdf[gdf.geometry.notna()]

        # Convert to GeoJSON
        geojson = json.loads(gdf.to_json())
        geojson, norm_warnings = self.normalize_geojson_for_json(geojson)
        warnings.extend(norm_warnings)

        return ConversionResult(
            geojson=geojson,
            source_format="GeoParquet",
            feature_count=len(geojson.get("features", [])),
            warnings=warnings,
            metadata=metadata,
        )

    def convert_from_bytes(
        self,
        data: bytes,
        **options: Any,
    ) -> ConversionResult:
        """Convert GeoParquet from bytes."""
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            f.write(data)
            temp_path = Path(f.name)

        try:
            return self.convert(temp_path, **options)
        finally:
            temp_path.unlink(missing_ok=True)
