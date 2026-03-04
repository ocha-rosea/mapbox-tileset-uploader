"""Tests for the CLI module."""

from click.testing import CliRunner

from mtu.cli import main


class TestCLI:
    """Test CLI commands."""

    def test_help(self) -> None:
        """Test main help."""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Mapbox Tileset Uploader" in result.output
        assert "upload" in result.output
        assert "convert" in result.output
        assert "ui" in result.output

    def test_version(self) -> None:
        """Test version command."""
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "mapbox-tileset-uploader" in result.output

    def test_formats_command(self) -> None:
        """Test formats command."""
        runner = CliRunner()
        result = runner.invoke(main, ["formats"])
        assert result.exit_code == 0
        assert "GeoJSON" in result.output
        assert "TopoJSON" in result.output
        assert ".geojson" in result.output

    def test_info_command(self) -> None:
        """Test info command."""
        runner = CliRunner()
        result = runner.invoke(main, ["info"])
        assert result.exit_code == 0
        assert "CONFIGURATION" in result.output
        assert "MAPBOX_ACCESS_TOKEN" in result.output
        assert "SUPPORTED FORMATS" in result.output
        assert "mtu ui" in result.output

    def test_upload_help(self) -> None:
        """Test upload command help."""
        runner = CliRunner()
        result = runner.invoke(main, ["upload", "--help"])
        assert result.exit_code == 0
        assert "--url" in result.output
        assert "--file" in result.output
        assert "--id" in result.output
        assert "--name" in result.output
        assert "--format" in result.output
        assert "--dry-run" in result.output

    def test_upload_missing_source(self) -> None:
        """Test upload without source."""
        runner = CliRunner()
        result = runner.invoke(main, ["upload", "--id", "test", "--name", "Test"])
        assert result.exit_code != 0
        assert "Either --url or --file must be provided" in result.output

    def test_upload_both_sources(self) -> None:
        """Test upload with both URL and file - file path checked first."""
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "upload",
                "--url",
                "http://test",
                "--file",
                "test.geojson",
                "--id",
                "test",
                "--name",
                "Test",
            ],
        )
        # Click validates file path exists before checking mutual exclusivity
        assert result.exit_code != 0

    def test_convert_help(self) -> None:
        """Test convert command help."""
        runner = CliRunner()
        result = runner.invoke(main, ["convert", "--help"])
        assert result.exit_code == 0
        assert "INPUT_FILE" in result.output
        assert "OUTPUT_FILE" in result.output
        assert "--pretty" in result.output

    def test_validate_help(self) -> None:
        """Test validate command help."""
        runner = CliRunner()
        result = runner.invoke(main, ["validate", "--help"])
        assert result.exit_code == 0
        assert "FILE_PATH" in result.output
        assert "--verbose" in result.output

    def test_list_sources_help(self) -> None:
        """Test list-sources command help."""
        runner = CliRunner()
        result = runner.invoke(main, ["list-sources", "--help"])
        assert result.exit_code == 0
        assert "--token" in result.output
        assert "--username" in result.output

    def test_list_tilesets_help(self) -> None:
        """Test list-tilesets command help."""
        runner = CliRunner()
        result = runner.invoke(main, ["list-tilesets", "--help"])
        assert result.exit_code == 0
        assert "--token" in result.output
        assert "--username" in result.output

    def test_delete_source_help(self) -> None:
        """Test delete-source command help."""
        runner = CliRunner()
        result = runner.invoke(main, ["delete-source", "--help"])
        assert result.exit_code == 0
        assert "SOURCE_ID" in result.output
        assert "--yes" in result.output

    def test_delete_tileset_help(self) -> None:
        """Test delete-tileset command help."""
        runner = CliRunner()
        result = runner.invoke(main, ["delete-tileset", "--help"])
        assert result.exit_code == 0
        assert "TILESET_ID" in result.output
        assert "--yes" in result.output
