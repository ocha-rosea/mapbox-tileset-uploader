"""
GeoPackage converter using fiona.
"""

from pathlib import Path
from typing import Any

from mtu.converters.base import BaseConverter, ConversionResult
from mtu.converters.registry import register_converter


@register_converter
class GeoPackageConverter(BaseConverter):
    """Converter for GeoPackage files."""

    format_name = "GeoPackage"
    file_extensions = [".gpkg"]
    mime_types = ["application/geopackage+sqlite3"]
    requires_packages = ["fiona"]

    def convert(
        self,
        source: str | Path | dict[str, Any],
        layer: str | None = None,
        **options: Any,
    ) -> ConversionResult:
        """
        Convert GeoPackage to GeoJSON.

        Args:
            source: Path to .gpkg file.
            layer: Layer name to convert. If None, uses the first layer.
            **options: Additional options.

        Returns:
            ConversionResult with the GeoJSON data.
        """
        import fiona

        warnings: list[str] = []
        self.validate_source(source)

        path = Path(source)

        # List available layers
        layers = fiona.listlayers(str(path))
        if not layers:
            raise ValueError("GeoPackage contains no layers")

        if layer:
            if layer not in layers:
                raise ValueError(f"Layer '{layer}' not found. Available: {', '.join(layers)}")
            selected_layer = layer
        else:
            selected_layer = layers[0]
            if len(layers) > 1:
                warnings.append(
                    f"Multiple layers found, using '{selected_layer}'. "
                    f"Available: {', '.join(layers)}"
                )

        features = []
        metadata: dict[str, Any] = {}

        with fiona.open(str(path), layer=selected_layer) as src:
            # Check CRS
            if src.crs:
                crs_str = str(src.crs)
                if "4326" not in crs_str and "WGS" not in crs_str.upper():
                    warnings.append(
                        f"CRS is {crs_str}, not WGS84. Data may need reprojection for web mapping."
                    )
                metadata["crs"] = crs_str

            for feature in src:
                # Convert fiona feature to GeoJSON
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

        metadata["layer"] = selected_layer
        metadata["available_layers"] = layers

        geojson = {"type": "FeatureCollection", "features": features}
        geojson, norm_warnings = self.normalize_geojson_for_json(geojson)
        warnings.extend(norm_warnings)

        return ConversionResult(
            geojson=geojson,
            source_format="GeoPackage",
            feature_count=len(features),
            warnings=warnings,
            metadata=metadata,
        )

    def convert_from_bytes(
        self,
        data: bytes,
        **options: Any,
    ) -> ConversionResult:
        """Convert GeoPackage from bytes."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False) as f:
            f.write(data)
            temp_path = Path(f.name)

        try:
            return self.convert(temp_path, **options)
        finally:
            temp_path.unlink(missing_ok=True)
