"""Tests for the uploader module."""

import os
import subprocess
from unittest.mock import patch

import pytest

from mtu.uploader import TilesetConfig, TilesetUploader, UploadResult


class TestTilesetConfig:
    """Test TilesetConfig dataclass."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = TilesetConfig(
            tileset_id="test-tileset",
            tileset_name="Test Tileset",
        )

        assert config.tileset_id == "test-tileset"
        assert config.tileset_name == "Test Tileset"
        assert config.source_id == "test-tileset"
        assert config.layer_name == "data"
        assert config.min_zoom == 0
        assert config.max_zoom == 10

    def test_source_id_default(self) -> None:
        """Test that source_id defaults to tileset_id with dots replaced."""
        config = TilesetConfig(
            tileset_id="my.test.tileset",
            tileset_name="Test",
        )

        assert config.source_id == "my-test-tileset"

    def test_custom_source_id(self) -> None:
        """Test custom source_id."""
        config = TilesetConfig(
            tileset_id="test",
            tileset_name="Test",
            source_id="custom-source",
        )

        assert config.source_id == "custom-source"

    def test_all_options(self) -> None:
        """Test setting all options."""
        config = TilesetConfig(
            tileset_id="test",
            tileset_name="Test Tileset",
            source_id="my-source",
            layer_name="boundaries",
            min_zoom=2,
            max_zoom=14,
            description="Test description",
            attribution="© Test",
            recipe={"version": 1},
        )

        assert config.layer_name == "boundaries"
        assert config.min_zoom == 2
        assert config.max_zoom == 14
        assert config.description == "Test description"
        assert config.attribution == "© Test"
        assert config.recipe == {"version": 1}


class TestTilesetUploader:
    """Test TilesetUploader class."""

    def test_missing_token(self) -> None:
        """Test error when token is missing."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MAPBOX_ACCESS_TOKEN", None)
            os.environ.pop("MAPBOX_USERNAME", None)

            with pytest.raises(ValueError, match="access token required"):
                TilesetUploader()

    def test_missing_username(self) -> None:
        """Test error when username is missing."""
        with patch.dict(os.environ, {"MAPBOX_ACCESS_TOKEN": "test-token"}, clear=True):
            os.environ.pop("MAPBOX_USERNAME", None)

            with pytest.raises(ValueError, match="username required"):
                TilesetUploader(access_token="test-token")

    def test_credentials_from_env(self) -> None:
        """Test credentials from environment variables."""
        with patch.dict(
            os.environ,
            {"MAPBOX_ACCESS_TOKEN": "env-token", "MAPBOX_USERNAME": "env-user"},
        ):
            uploader = TilesetUploader()

            assert uploader.access_token == "env-token"
            assert uploader.username == "env-user"

    def test_credentials_from_params(self) -> None:
        """Test credentials from parameters override env."""
        with patch.dict(
            os.environ,
            {"MAPBOX_ACCESS_TOKEN": "env-token", "MAPBOX_USERNAME": "env-user"},
        ):
            uploader = TilesetUploader(
                access_token="param-token",
                username="param-user",
            )

            assert uploader.access_token == "param-token"
            assert uploader.username == "param-user"

    def test_build_recipe(self) -> None:
        """Test recipe building."""
        with patch.dict(
            os.environ,
            {"MAPBOX_ACCESS_TOKEN": "test", "MAPBOX_USERNAME": "testuser"},
        ):
            uploader = TilesetUploader()
            config = TilesetConfig(
                tileset_id="test",
                tileset_name="Test",
                source_id="test-source",
                layer_name="mylayer",
                min_zoom=2,
                max_zoom=14,
            )

            recipe = uploader._build_recipe(config)

            assert recipe["version"] == 1
            assert "mylayer" in recipe["layers"]
            assert recipe["layers"]["mylayer"]["minzoom"] == 2
            assert recipe["layers"]["mylayer"]["maxzoom"] == 14
            assert "testuser" in recipe["layers"]["mylayer"]["source"]

    def test_custom_recipe(self) -> None:
        """Test that custom recipe is used when provided."""
        with patch.dict(
            os.environ,
            {"MAPBOX_ACCESS_TOKEN": "test", "MAPBOX_USERNAME": "testuser"},
        ):
            uploader = TilesetUploader()
            custom = {"version": 1, "layers": {"custom": {"source": "test"}}}
            config = TilesetConfig(
                tileset_id="test",
                tileset_name="Test",
                recipe=custom,
            )

            recipe = uploader._build_recipe(config)

            assert recipe == custom

    def test_validate_geometry_option(self) -> None:
        """Test validate_geometry option."""
        with patch.dict(
            os.environ,
            {"MAPBOX_ACCESS_TOKEN": "test", "MAPBOX_USERNAME": "testuser"},
        ):
            uploader_with = TilesetUploader(validate_geometry=True)
            assert uploader_with._validator is not None

            uploader_without = TilesetUploader(validate_geometry=False)
            assert uploader_without._validator is None

    def test_get_supported_formats(self) -> None:
        """Test getting supported formats."""
        with patch.dict(
            os.environ,
            {"MAPBOX_ACCESS_TOKEN": "test", "MAPBOX_USERNAME": "testuser"},
        ):
            formats = TilesetUploader.get_supported_formats()

            assert len(formats) >= 2
            format_names = [f["format_name"] for f in formats]
            assert "GeoJSON" in format_names
            assert "TopoJSON" in format_names

    def test_extract_error_message_from_json(self) -> None:
        """Test extracting message from JSON CLI output."""
        raw = '{"message":"Forbidden"}'
        assert TilesetUploader._extract_error_message(raw) == "Forbidden"

    def test_extract_error_message_from_plain_text(self) -> None:
        """Test extracting message from plain text output."""
        raw = "some cli failure"
        assert TilesetUploader._extract_error_message(raw) == "some cli failure"

    def test_format_tilesets_command_error_forbidden(self) -> None:
        """Test that forbidden errors include actionable guidance."""
        uploader = TilesetUploader.__new__(TilesetUploader)
        uploader.username = "demo-user"

        result = subprocess.CompletedProcess(
            args=["tilesets", "upload-source"],
            returncode=1,
            stdout="",
            stderr='{"message":"Forbidden"}',
        )

        detail = uploader._format_tilesets_command_error(result)
        assert "Forbidden" in detail
        assert "MAPBOX_ACCESS_TOKEN" in detail
        assert "MAPBOX_USERNAME" in detail

    def test_run_tilesets_command_timeout(self) -> None:
        """Test timeout handling for external tilesets command."""
        uploader = TilesetUploader.__new__(TilesetUploader)
        uploader._tilesets_command = ["tilesets"]
        uploader._use_inprocess_tilesets = False

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="tilesets", timeout=1)):
            with pytest.raises(RuntimeError, match="timed out"):
                uploader._run_tilesets_command(["status", "user.test"], timeout=1)


class TestUploadResult:
    """Test UploadResult dataclass."""

    def test_defaults(self) -> None:
        """Test default values."""
        result = UploadResult(
            success=True,
            tileset_id="user.test",
            source_id="test-source",
        )

        assert result.success
        assert result.tileset_id == "user.test"
        assert result.source_id == "test-source"
        assert result.steps == {}
        assert result.warnings == []
        assert result.job_id == ""
        assert result.error == ""
        assert not result.dry_run

    def test_with_warnings(self) -> None:
        """Test with warnings."""
        result = UploadResult(
            success=True,
            tileset_id="user.test",
            source_id="test",
            warnings=["Warning 1", "Warning 2"],
        )

        assert len(result.warnings) == 2

    def test_with_steps(self) -> None:
        """Test with steps."""
        result = UploadResult(
            success=True,
            tileset_id="user.test",
            source_id="test",
            steps={
                "convert": True,
                "validate": True,
                "upload_source": True,
                "create_tileset": True,
                "publish": True,
                "job_complete": True,
            },
        )

        assert all(result.steps.values())
        assert len(result.steps) == 6
