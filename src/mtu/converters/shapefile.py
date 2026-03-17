"""
Shapefile converter using pyshp or fiona.
"""

import tempfile
import zipfile
from pathlib import Path
from typing import Any

from mtu.converters.base import BaseConverter, ConversionResult
from mtu.converters.registry import register_converter


@register_converter
class ShapefileConverter(BaseConverter):
    """Converter for ESRI Shapefiles."""

    format_name = "Shapefile"
    file_extensions = [".shp", ".zip"]
    mime_types = ["application/x-shapefile", "application/zip"]
    requires_packages = ["shapefile"]  # pyshp

    def convert(
        self,
        source: str | Path | dict[str, Any],
        encoding: str = "utf-8",
        **options: Any,
    ) -> ConversionResult:
        """
        Convert Shapefile to GeoJSON.

        Args:
            source: Path to .shp file or .zip containing shapefile.
            encoding: Character encoding for DBF file.
            **options: Additional options.

        Returns:
            ConversionResult with the GeoJSON data.
        """
        import shapefile

        warnings: list[str] = []
        path = Path(source)

        # Handle ZIP files
        if path.suffix.lower() == ".zip":
            return self._convert_from_zip(path, encoding, **options)

        self.validate_source(source)

        # Check for companion files
        base = path.with_suffix("")
        if not base.with_suffix(".dbf").exists():
            warnings.append("Missing .dbf file - attributes may be empty")
        if not base.with_suffix(".prj").exists():
            warnings.append("Missing .prj file - assuming WGS84 (EPSG:4326)")

        try:
            with shapefile.Reader(str(path), encoding=encoding) as sf:
                features = []
                field_names = [field[0] for field in sf.fields[1:]]  # Skip DeletionFlag

                for shaperec in sf.iterShapeRecords():
                    geom = shaperec.shape.__geo_interface__
                    props = dict(zip(field_names, shaperec.record))

                    # Check for null geometry
                    if geom.get("type") is None:
                        warnings.append("Feature with null geometry skipped")
                        continue

                    features.append(
                        {
                            "type": "Feature",
                            "geometry": geom,
                            "properties": props,
                        }
                    )

        except shapefile.ShapefileException as e:
            raise ValueError(f"Invalid shapefile: {e}")

        geojson = {"type": "FeatureCollection", "features": features}
        geojson, norm_warnings = self.normalize_geojson_for_json(geojson)
        warnings.extend(norm_warnings)

        return ConversionResult(
            geojson=geojson,
            source_format="Shapefile",
            feature_count=len(features),
            warnings=warnings,
        )

    def _convert_from_zip(
        self,
        zip_path: Path,
        encoding: str,
        **options: Any,
    ) -> ConversionResult:
        """Extract and convert shapefile from ZIP."""

        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmpdir)

            # Find .shp file
            shp_files = list(Path(tmpdir).rglob("*.shp"))
            if not shp_files:
                raise ValueError("No .shp file found in ZIP archive")

            if len(shp_files) > 1:
                # Try to find one not in __MACOSX
                shp_files = [f for f in shp_files if "__MACOSX" not in str(f)]

            return self.convert(shp_files[0], encoding=encoding, **options)

    def convert_from_bytes(
        self,
        data: bytes,
        **options: Any,
    ) -> ConversionResult:
        """Convert shapefile from bytes (must be ZIP)."""
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            f.write(data)
            temp_path = Path(f.name)

        try:
            return self.convert(temp_path, **options)
        finally:
            temp_path.unlink(missing_ok=True)

    @classmethod
    def can_handle(cls, file_path: str | Path) -> bool:
        """Check if this is a shapefile."""
        path = Path(file_path)
        suffix = path.suffix.lower()

        if suffix == ".shp":
            return True

        # Check if ZIP contains shapefile
        if suffix == ".zip":
            try:
                with zipfile.ZipFile(path, "r") as zf:
                    names = zf.namelist()
                    return any(n.lower().endswith(".shp") for n in names)
            except (OSError, zipfile.BadZipFile):
                return False

        return False
