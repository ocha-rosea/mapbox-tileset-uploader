"""
KML/KMZ converter using fiona or fastkml.
"""

import tempfile
import zipfile
from pathlib import Path
from typing import Any

from mtu.converters.base import BaseConverter, ConversionResult
from mtu.converters.registry import register_converter


@register_converter
class KMLConverter(BaseConverter):
    """Converter for KML and KMZ files."""

    format_name = "KML"
    file_extensions = [".kml", ".kmz"]
    mime_types = [
        "application/vnd.google-earth.kml+xml",
        "application/vnd.google-earth.kmz",
    ]
    requires_packages = ["fiona"]

    def convert(
        self,
        source: str | Path | dict[str, Any],
        **options: Any,
    ) -> ConversionResult:
        """
        Convert KML/KMZ to GeoJSON.

        Args:
            source: Path to .kml or .kmz file.
            **options: Additional options.

        Returns:
            ConversionResult with the GeoJSON data.
        """
        import fiona

        warnings: list[str] = []
        path = Path(source)

        # Handle KMZ (zipped KML)
        if path.suffix.lower() == ".kmz":
            return self._convert_from_kmz(path, **options)

        self.validate_source(source)

        features = []

        # Enable KML driver
        fiona.drvsupport.supported_drivers["KML"] = "r"

        try:
            with fiona.open(str(path), driver="KML") as src:
                for feature in src:
                    geom = dict(feature.get("geometry", {}))
                    props = dict(feature.get("properties", {}))

                    if not geom or geom.get("type") is None:
                        warnings.append("Feature with null geometry skipped")
                        continue

                    # KML often has HTML in description
                    if "description" in props and props["description"]:
                        desc = props["description"]
                        if "<" in str(desc) and ">" in str(desc):
                            warnings.append("Description contains HTML markup - may need cleaning")

                    feat: dict[str, Any] = {
                        "type": "Feature",
                        "geometry": geom,
                        "properties": props,
                    }

                    if feature.get("id") is not None:
                        feat["id"] = feature["id"]

                    features.append(feat)

        except Exception as e:
            raise ValueError(f"Failed to read KML: {e}")

        geojson = {"type": "FeatureCollection", "features": features}
        geojson, norm_warnings = self.normalize_geojson_for_json(geojson)
        warnings.extend(norm_warnings)

        return ConversionResult(
            geojson=geojson,
            source_format="KML",
            feature_count=len(features),
            warnings=warnings,
        )

    def _convert_from_kmz(
        self,
        kmz_path: Path,
        **options: Any,
    ) -> ConversionResult:
        """Extract and convert KML from KMZ."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(kmz_path, "r") as zf:
                zf.extractall(tmpdir)

            # Find .kml file
            kml_files = list(Path(tmpdir).rglob("*.kml"))
            if not kml_files:
                raise ValueError("No .kml file found in KMZ archive")

            # Usually doc.kml is the main file
            main_kml = None
            for kf in kml_files:
                if kf.name.lower() == "doc.kml":
                    main_kml = kf
                    break

            if main_kml is None:
                main_kml = kml_files[0]

            result = self.convert(main_kml, **options)
            # Update source format
            return ConversionResult(
                geojson=result.geojson,
                source_format="KMZ",
                feature_count=result.feature_count,
                warnings=result.warnings,
                metadata=result.metadata,
            )

    def convert_from_bytes(
        self,
        data: bytes,
        **options: Any,
    ) -> ConversionResult:
        """Convert KML/KMZ from bytes."""
        # Detect if ZIP (KMZ)
        is_kmz = data[:4] == b"PK\x03\x04"
        suffix = ".kmz" if is_kmz else ".kml"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(data)
            temp_path = Path(f.name)

        try:
            return self.convert(temp_path, **options)
        finally:
            temp_path.unlink(missing_ok=True)
