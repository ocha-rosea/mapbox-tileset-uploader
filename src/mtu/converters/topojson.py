"""
TopoJSON to GeoJSON converter.
"""

import json
from pathlib import Path
from typing import Any

from mtu.converters.base import BaseConverter, ConversionResult
from mtu.converters.registry import register_converter


@register_converter
class TopoJSONConverter(BaseConverter):
    """Converter for TopoJSON files."""

    format_name = "TopoJSON"
    file_extensions = [".topojson"]
    mime_types = ["application/topojson+json"]
    requires_packages: list[str] = []  # Built-in

    def convert(
        self,
        source: str | Path | dict[str, Any],
        object_name: str | None = None,
        **options: Any,
    ) -> ConversionResult:
        """
        Convert TopoJSON to GeoJSON.

        Args:
            source: File path or TopoJSON dictionary.
            object_name: Name of the object to convert. If None, converts the first.
            **options: Additional options.

        Returns:
            ConversionResult with the GeoJSON data.
        """
        warnings: list[str] = []

        if isinstance(source, dict):
            topojson = source
        else:
            self.validate_source(source)
            with open(source, encoding="utf-8") as f:
                topojson = json.load(f)

        if topojson.get("type") != "Topology":
            raise ValueError("Input is not a valid TopoJSON (missing 'Topology' type)")

        objects = topojson.get("objects", {})
        if not objects:
            raise ValueError("TopoJSON contains no objects")

        # Get the object to convert
        if object_name:
            if object_name not in objects:
                raise ValueError(f"Object '{object_name}' not found in TopoJSON")
            obj = objects[object_name]
        else:
            object_name = next(iter(objects))
            if len(objects) > 1:
                warnings.append(
                    f"Multiple objects found, using '{object_name}'. "
                    f"Available: {', '.join(objects.keys())}"
                )
            obj = objects[object_name]

        arcs = topojson.get("arcs", [])
        transform = topojson.get("transform")

        features = []
        geometries = obj.get("geometries", [obj])

        for geometry in geometries:
            feature: dict[str, Any] = {
                "type": "Feature",
                "properties": geometry.get("properties", {}),
                "geometry": self._decode_geometry(geometry, arcs, transform),
            }
            if "id" in geometry:
                feature["id"] = geometry["id"]
            features.append(feature)

        geojson = {"type": "FeatureCollection", "features": features}
        geojson, norm_warnings = self.normalize_geojson_for_json(geojson)
        warnings.extend(norm_warnings)

        return ConversionResult(
            geojson=geojson,
            source_format="TopoJSON",
            feature_count=len(features),
            warnings=warnings,
            metadata={"source_object": object_name},
        )

    def convert_from_bytes(
        self,
        data: bytes,
        **options: Any,
    ) -> ConversionResult:
        """Convert TopoJSON from bytes."""
        topojson = json.loads(data.decode("utf-8"))
        return self.convert(topojson, **options)

    def _decode_geometry(
        self,
        geometry: dict[str, Any],
        arcs: list[list[list[int]]],
        transform: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Decode a TopoJSON geometry to GeoJSON geometry."""
        geom_type = geometry.get("type")

        if geom_type is None or geom_type == "null":
            return None

        if geom_type == "Point":
            coords = geometry.get("coordinates", [])
            return {"type": "Point", "coordinates": self._transform_point(coords, transform)}

        if geom_type == "MultiPoint":
            coords = geometry.get("coordinates", [])
            return {
                "type": "MultiPoint",
                "coordinates": [self._transform_point(c, transform) for c in coords],
            }

        if geom_type == "LineString":
            arc_indices = geometry.get("arcs", [])
            return {
                "type": "LineString",
                "coordinates": self._decode_arcs(arc_indices, arcs, transform),
            }

        if geom_type == "MultiLineString":
            arc_groups = geometry.get("arcs", [])
            return {
                "type": "MultiLineString",
                "coordinates": [self._decode_arcs(ag, arcs, transform) for ag in arc_groups],
            }

        if geom_type == "Polygon":
            arc_groups = geometry.get("arcs", [])
            return {
                "type": "Polygon",
                "coordinates": [self._decode_arcs(ring, arcs, transform) for ring in arc_groups],
            }

        if geom_type == "MultiPolygon":
            polygon_groups = geometry.get("arcs", [])
            return {
                "type": "MultiPolygon",
                "coordinates": [
                    [self._decode_arcs(ring, arcs, transform) for ring in polygon]
                    for polygon in polygon_groups
                ],
            }

        if geom_type == "GeometryCollection":
            geometries = geometry.get("geometries", [])
            return {
                "type": "GeometryCollection",
                "geometries": [self._decode_geometry(g, arcs, transform) for g in geometries],
            }

        raise ValueError(f"Unknown geometry type: {geom_type}")

    def _decode_arcs(
        self,
        arc_indices: list[int],
        arcs: list[list[list[int]]],
        transform: dict[str, Any] | None,
    ) -> list[list[float]]:
        """Decode arc indices to coordinates."""
        coordinates: list[list[float]] = []

        for arc_index in arc_indices:
            if arc_index < 0:
                arc = list(reversed(arcs[~arc_index]))
            else:
                arc = arcs[arc_index]

            decoded_arc = self._decode_arc(arc, transform)
            start = 0 if not coordinates else 1
            coordinates.extend(decoded_arc[start:])

        return coordinates

    def _decode_arc(
        self,
        arc: list[list[int]],
        transform: dict[str, Any] | None,
    ) -> list[list[float]]:
        """Decode a single arc with delta encoding and optional transform."""
        coordinates: list[list[float]] = []
        x, y = 0, 0

        for point in arc:
            x += point[0]
            y += point[1]
            coordinates.append(self._transform_point([x, y], transform))

        return coordinates

    def _transform_point(
        self,
        point: list[int | float],
        transform: dict[str, Any] | None,
    ) -> list[float]:
        """Apply transform to a point."""
        if transform is None:
            return [float(point[0]), float(point[1])]

        scale = transform.get("scale", [1, 1])
        translate = transform.get("translate", [0, 0])

        return [
            point[0] * scale[0] + translate[0],
            point[1] * scale[1] + translate[1],
        ]
