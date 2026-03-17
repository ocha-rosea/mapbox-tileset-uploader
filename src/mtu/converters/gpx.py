"""
GPX (GPS Exchange Format) converter.
"""

import tempfile
from pathlib import Path
from typing import Any

from mtu.converters.base import BaseConverter, ConversionResult
from mtu.converters.registry import register_converter


@register_converter
class GPXConverter(BaseConverter):
    """Converter for GPX files."""

    format_name = "GPX"
    file_extensions = [".gpx"]
    mime_types = ["application/gpx+xml"]
    requires_packages = ["gpxpy"]

    def convert(
        self,
        source: str | Path | dict[str, Any],
        include_tracks: bool = True,
        include_routes: bool = True,
        include_waypoints: bool = True,
        **options: Any,
    ) -> ConversionResult:
        """
        Convert GPX to GeoJSON.

        Args:
            source: Path to .gpx file.
            include_tracks: Include track data as LineStrings.
            include_routes: Include route data as LineStrings.
            include_waypoints: Include waypoint data as Points.
            **options: Additional options.

        Returns:
            ConversionResult with the GeoJSON data.
        """
        import gpxpy

        warnings: list[str] = []
        self.validate_source(source)

        path = Path(source)
        features: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {
            "tracks": 0,
            "routes": 0,
            "waypoints": 0,
        }

        with open(path, encoding="utf-8") as f:
            try:
                gpx = gpxpy.parse(f)
            except Exception as e:
                raise ValueError(f"Failed to parse GPX: {e}")

        # Process waypoints
        if include_waypoints:
            for wpt in gpx.waypoints:
                props: dict[str, Any] = {
                    "type": "waypoint",
                    "name": wpt.name,
                    "description": wpt.description,
                    "elevation": wpt.elevation,
                    "time": wpt.time.isoformat() if wpt.time else None,
                }
                # Remove None values
                props = {k: v for k, v in props.items() if v is not None}

                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": self._point_coords(wpt),
                        },
                        "properties": props,
                    }
                )
                metadata["waypoints"] += 1

        # Process routes
        if include_routes:
            for route in gpx.routes:
                if not route.points:
                    warnings.append(f"Empty route '{route.name}' skipped")
                    continue

                coords = [self._point_coords(pt) for pt in route.points]
                props = {
                    "type": "route",
                    "name": route.name,
                    "description": route.description,
                }
                props = {k: v for k, v in props.items() if v is not None}

                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": coords,
                        },
                        "properties": props,
                    }
                )
                metadata["routes"] += 1

        # Process tracks
        if include_tracks:
            for track in gpx.tracks:
                for i, segment in enumerate(track.segments):
                    if not segment.points:
                        warnings.append(f"Empty track segment in '{track.name}' skipped")
                        continue

                    coords = [self._point_coords(pt) for pt in segment.points]
                    props = {
                        "type": "track",
                        "name": track.name,
                        "segment": i,
                        "description": track.description,
                    }
                    props = {k: v for k, v in props.items() if v is not None}

                    # Calculate track statistics
                    if segment.points:
                        times = [pt.time for pt in segment.points if pt.time]
                        if len(times) >= 2:
                            props["start_time"] = times[0].isoformat()
                            props["end_time"] = times[-1].isoformat()
                            props["duration_seconds"] = (times[-1] - times[0]).total_seconds()

                    features.append(
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "LineString",
                                "coordinates": coords,
                            },
                            "properties": props,
                        }
                    )
                    metadata["tracks"] += 1

        if not features:
            warnings.append("No features found in GPX file")

        geojson = {"type": "FeatureCollection", "features": features}
        geojson, norm_warnings = self.normalize_geojson_for_json(geojson)
        warnings.extend(norm_warnings)

        return ConversionResult(
            geojson=geojson,
            source_format="GPX",
            feature_count=len(features),
            warnings=warnings,
            metadata=metadata,
        )

    def _point_coords(self, point: Any) -> list[float]:
        """Extract coordinates from GPX point."""
        if point.elevation is not None:
            return [point.longitude, point.latitude, point.elevation]
        return [point.longitude, point.latitude]

    def convert_from_bytes(
        self,
        data: bytes,
        **options: Any,
    ) -> ConversionResult:
        """Convert GPX from bytes."""
        with tempfile.NamedTemporaryFile(suffix=".gpx", delete=False, mode="wb") as f:
            f.write(data)
            temp_path = Path(f.name)

        try:
            return self.convert(temp_path, **options)
        finally:
            temp_path.unlink(missing_ok=True)
