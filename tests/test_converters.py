"""Tests for the converters module."""

import json
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from mtu.converters import get_converter, get_supported_formats
from mtu.converters.base import ConversionResult
from mtu.converters.geojson import GeoJSONConverter
from mtu.converters.topojson import TopoJSONConverter


class _DummyConverter(GeoJSONConverter):
    """Concrete converter for testing BaseConverter helpers."""

    format_name = "DummyGeoJSON"


class TestConverterRegistry:
    """Test converter registry functionality."""

    def test_get_supported_formats(self) -> None:
        """Test listing supported formats."""
        formats = get_supported_formats()
        assert len(formats) >= 2  # At least GeoJSON and TopoJSON

        format_names = [f["format_name"] for f in formats]
        assert "GeoJSON" in format_names
        assert "TopoJSON" in format_names

    def test_get_converter_by_format(self) -> None:
        """Test getting converter by format name."""
        converter = get_converter(format_name="geojson")
        assert isinstance(converter, GeoJSONConverter)

        converter = get_converter(format_name="topojson")
        assert isinstance(converter, TopoJSONConverter)

    def test_get_converter_by_file_path(self) -> None:
        """Test getting converter by file path."""
        converter = get_converter(file_path="data.geojson")
        assert isinstance(converter, GeoJSONConverter)

        converter = get_converter(file_path="data.topojson")
        assert isinstance(converter, TopoJSONConverter)

        converter = get_converter(file_path="data.json")
        assert isinstance(converter, GeoJSONConverter)

    def test_get_converter_unknown_format(self) -> None:
        """Test error for unknown format."""
        with pytest.raises(ValueError, match="Unknown format"):
            get_converter(format_name="unknown")

    def test_get_converter_unknown_extension(self) -> None:
        """Test error for unknown file extension."""
        with pytest.raises(ValueError, match="Unknown file extension"):
            get_converter(file_path="data.xyz")

    def test_get_converter_requires_argument(self) -> None:
        """Test error when no argument provided."""
        with pytest.raises(ValueError, match="Either format_name or file_path"):
            get_converter()


class TestGeoJSONConverter:
    """Test GeoJSON converter."""

    def test_convert_feature_collection(self) -> None:
        """Test converting a FeatureCollection."""
        converter = GeoJSONConverter()
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                    "properties": {"name": "Test"},
                }
            ],
        }

        result = converter.convert(geojson)
        assert isinstance(result, ConversionResult)
        assert result.feature_count == 1
        assert result.source_format == "GeoJSON"
        assert result.geojson["type"] == "FeatureCollection"

    def test_convert_single_feature(self) -> None:
        """Test converting a single Feature to FeatureCollection."""
        converter = GeoJSONConverter()
        geojson = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {},
        }

        result = converter.convert(geojson)
        assert result.geojson["type"] == "FeatureCollection"
        assert len(result.geojson["features"]) == 1
        assert len(result.warnings) > 0  # Should warn about wrapping

    def test_convert_geometry(self) -> None:
        """Test converting bare geometry to FeatureCollection."""
        converter = GeoJSONConverter()
        geojson = {"type": "Point", "coordinates": [0, 0]}

        result = converter.convert(geojson)
        assert result.geojson["type"] == "FeatureCollection"
        assert len(result.warnings) > 0

    def test_convert_from_file(self) -> None:
        """Test converting from file."""
        converter = GeoJSONConverter()
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [1, 2]},
                    "properties": {"id": 1},
                }
            ],
        }

        with tempfile.NamedTemporaryFile(suffix=".geojson", mode="w", delete=False) as f:
            json.dump(geojson, f)
            temp_path = Path(f.name)

        try:
            result = converter.convert(temp_path)
            assert result.feature_count == 1
        finally:
            temp_path.unlink()

    def test_convert_invalid_type(self) -> None:
        """Test error for invalid GeoJSON type."""
        converter = GeoJSONConverter()
        with pytest.raises(ValueError, match="Invalid GeoJSON type"):
            converter.convert({"type": "InvalidType"})


class TestTopoJSONConverter:
    """Test TopoJSON converter."""

    def test_convert_simple_polygon(self) -> None:
        """Test converting a simple polygon."""
        converter = TopoJSONConverter()
        topojson = {
            "type": "Topology",
            "objects": {
                "test": {
                    "type": "GeometryCollection",
                    "geometries": [
                        {
                            "type": "Polygon",
                            "arcs": [[0]],
                            "properties": {"name": "Test"},
                        }
                    ],
                }
            },
            "arcs": [[[0, 0], [1, 0], [0, 1], [-1, 0], [0, -1]]],
        }

        result = converter.convert(topojson)
        assert result.source_format == "TopoJSON"
        assert result.feature_count == 1
        assert result.geojson["features"][0]["properties"]["name"] == "Test"
        assert result.geojson["features"][0]["geometry"]["type"] == "Polygon"

    def test_convert_with_transform(self) -> None:
        """Test converting with quantization transform."""
        converter = TopoJSONConverter()
        topojson = {
            "type": "Topology",
            "transform": {"scale": [0.001, 0.001], "translate": [-180, -90]},
            "objects": {
                "test": {
                    "type": "GeometryCollection",
                    "geometries": [
                        {
                            "type": "Point",
                            "coordinates": [180000, 90000],
                            "properties": {},
                        }
                    ],
                }
            },
            "arcs": [],
        }

        result = converter.convert(topojson)
        coords = result.geojson["features"][0]["geometry"]["coordinates"]
        assert abs(coords[0] - 0.0) < 0.01
        assert abs(coords[1] - 0.0) < 0.01

    def test_convert_invalid_topology(self) -> None:
        """Test error for invalid TopoJSON."""
        converter = TopoJSONConverter()
        with pytest.raises(ValueError, match="not a valid TopoJSON"):
            converter.convert({"type": "FeatureCollection"})

    def test_convert_empty_objects(self) -> None:
        """Test error for empty objects."""
        converter = TopoJSONConverter()
        with pytest.raises(ValueError, match="no objects"):
            converter.convert({"type": "Topology", "objects": {}})

    def test_convert_specific_object(self) -> None:
        """Test selecting specific object by name."""
        converter = TopoJSONConverter()
        topojson = {
            "type": "Topology",
            "objects": {
                "countries": {
                    "type": "GeometryCollection",
                    "geometries": [
                        {"type": "Point", "coordinates": [0, 0], "properties": {"name": "Country"}}
                    ],
                },
                "cities": {
                    "type": "GeometryCollection",
                    "geometries": [
                        {"type": "Point", "coordinates": [1, 1], "properties": {"name": "City"}}
                    ],
                },
            },
            "arcs": [],
        }

        result = converter.convert(topojson, object_name="cities")
        assert result.geojson["features"][0]["properties"]["name"] == "City"

    def test_convert_object_not_found(self) -> None:
        """Test error when object name not found."""
        converter = TopoJSONConverter()
        topojson = {
            "type": "Topology",
            "objects": {"test": {"type": "GeometryCollection", "geometries": []}},
            "arcs": [],
        }

        with pytest.raises(ValueError, match="not found"):
            converter.convert(topojson, object_name="nonexistent")

    def test_convert_multiple_objects_warning(self) -> None:
        """Test warning when multiple objects and none specified."""
        converter = TopoJSONConverter()
        topojson = {
            "type": "Topology",
            "objects": {
                "a": {"type": "GeometryCollection", "geometries": []},
                "b": {"type": "GeometryCollection", "geometries": []},
            },
            "arcs": [],
        }

        result = converter.convert(topojson)
        assert any("Multiple objects" in w for w in result.warnings)


class TestGeometryTypes:
    """Test various geometry types in TopoJSON."""

    def test_multipolygon(self) -> None:
        """Test MultiPolygon conversion."""
        converter = TopoJSONConverter()
        topojson = {
            "type": "Topology",
            "objects": {
                "test": {
                    "type": "GeometryCollection",
                    "geometries": [
                        {"type": "MultiPolygon", "arcs": [[[0]], [[1]]], "properties": {}}
                    ],
                }
            },
            "arcs": [
                [[0, 0], [1, 0], [0, 1], [-1, 0], [0, -1]],
                [[2, 0], [1, 0], [0, 1], [-1, 0], [0, -1]],
            ],
        }

        result = converter.convert(topojson)
        assert result.geojson["features"][0]["geometry"]["type"] == "MultiPolygon"
        assert len(result.geojson["features"][0]["geometry"]["coordinates"]) == 2

    def test_linestring(self) -> None:
        """Test LineString conversion."""
        converter = TopoJSONConverter()
        topojson = {
            "type": "Topology",
            "objects": {
                "test": {
                    "type": "GeometryCollection",
                    "geometries": [{"type": "LineString", "arcs": [0], "properties": {}}],
                }
            },
            "arcs": [[[0, 0], [1, 0], [1, 1]]],
        }

        result = converter.convert(topojson)
        assert result.geojson["features"][0]["geometry"]["type"] == "LineString"

    def test_multilinestring(self) -> None:
        """Test MultiLineString conversion."""
        converter = TopoJSONConverter()
        topojson = {
            "type": "Topology",
            "objects": {
                "test": {
                    "type": "GeometryCollection",
                    "geometries": [
                        {"type": "MultiLineString", "arcs": [[0], [1]], "properties": {}}
                    ],
                }
            },
            "arcs": [[[0, 0], [1, 0]], [[2, 0], [3, 0]]],
        }

        result = converter.convert(topojson)
        assert result.geojson["features"][0]["geometry"]["type"] == "MultiLineString"

    def test_point(self) -> None:
        """Test Point conversion."""
        converter = TopoJSONConverter()
        topojson = {
            "type": "Topology",
            "objects": {
                "test": {
                    "type": "GeometryCollection",
                    "geometries": [{"type": "Point", "coordinates": [10, 20], "properties": {}}],
                }
            },
            "arcs": [],
        }

        result = converter.convert(topojson)
        geom = result.geojson["features"][0]["geometry"]
        assert geom["type"] == "Point"
        assert geom["coordinates"] == [10.0, 20.0]

    def test_multipoint(self) -> None:
        """Test MultiPoint conversion."""
        converter = TopoJSONConverter()
        topojson = {
            "type": "Topology",
            "objects": {
                "test": {
                    "type": "GeometryCollection",
                    "geometries": [
                        {
                            "type": "MultiPoint",
                            "coordinates": [[0, 0], [1, 1]],
                            "properties": {},
                        }
                    ],
                }
            },
            "arcs": [],
        }

        result = converter.convert(topojson)
        geom = result.geojson["features"][0]["geometry"]
        assert geom["type"] == "MultiPoint"
        assert len(geom["coordinates"]) == 2


class TestJsonNormalization:
    """Test JSON-safe normalization for converter outputs."""

    def test_geojson_converter_normalizes_datetime_like_values(self) -> None:
        """Date/time values should be serialized as ISO strings."""
        converter = GeoJSONConverter()
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                    "properties": {
                        "created_on": date(2024, 5, 1),
                        "observed_at": datetime(2024, 5, 1, 12, 30, tzinfo=timezone.utc),
                    },
                }
            ],
        }

        result = converter.convert(geojson)
        props = result.geojson["features"][0]["properties"]
        assert props["created_on"] == "2024-05-01"
        assert props["observed_at"] == "2024-05-01T12:30:00+00:00"

    def test_normalize_geojson_for_json_handles_mixed_types(self) -> None:
        """Mixed non-JSON-native values should be converted with warnings."""
        converter = _DummyConverter()
        normalized, warnings = converter.normalize_geojson_for_json(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [1, 2]},
                        "properties": {
                            "decimal": Decimal("10.5"),
                            "tags": {"a", "b"},
                            "blob": b"abc",
                        },
                    }
                ],
            }
        )

        props = normalized["features"][0]["properties"]
        assert props["decimal"] == 10.5
        assert sorted(props["tags"]) == ["a", "b"]
        assert props["blob"] == "abc"
        assert any("Binary value" in warning for warning in warnings)
