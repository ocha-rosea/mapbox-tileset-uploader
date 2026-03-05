"""
Core uploader module for Mapbox Tileset operations.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from click.testing import CliRunner

from mtu.converters import get_converter, get_supported_formats
from mtu.converters.base import ConversionResult
from mtu.validators import GeometryValidator, ValidationResult

MAPBOX_MAX_SOURCE_FILE_BYTES = 20 * 1024 * 1024 * 1024
MAPBOX_MAX_SOURCE_FILE_SIZE_GB = 20
DEFAULT_UPLOAD_SOFT_CAP_BYTES = 1 * 1024 * 1024 * 1024
DEFAULT_UPLOAD_SOFT_CAP_GB = 1


@dataclass
class TilesetConfig:
    """Configuration for a tileset upload."""

    tileset_id: str = ""
    tileset_name: str = ""
    source_id: str | None = None
    layer_name: str = "data"
    min_zoom: int = 0
    max_zoom: int = 10
    description: str = ""
    attribution: str = ""
    recipe: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Set defaults after initialization."""
        if self.tileset_id and not self.source_id:
            self.source_id = self.tileset_id.replace(".", "-")


@dataclass
class UploadResult:
    """Result of a tileset upload operation."""

    success: bool
    tileset_id: str
    source_id: str | None
    steps: dict[str, bool] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    validation_result: ValidationResult | None = None
    conversion_result: ConversionResult | None = None
    job_id: str = ""
    job_status: str = ""
    error: str = ""
    dry_run: bool = False


class TilesetUploader:
    """
    Upload GeoJSON and other GIS formats to Mapbox as vector tilesets.

    This class wraps the mapbox-tilesets CLI to provide a Python interface
    for uploading geographic data to Mapbox Tiling Service (MTS).

    Supports multiple input formats through the modular converter system:
    - GeoJSON (.geojson, .json)
    - TopoJSON (.topojson)
    - Shapefile (.shp, .zip)
    - GeoPackage (.gpkg)
    - KML/KMZ (.kml, .kmz)
    - FlatGeobuf (.fgb)
    - GeoParquet (.parquet, .geoparquet)
    - GPX (.gpx)
    """

    def __init__(
        self,
        access_token: str | None = None,
        username: str | None = None,
        validate_geometry: bool = True,
        use_mapbox_full_upload_cap: bool = False,
    ) -> None:
        """
        Initialize the uploader.

        Args:
            access_token: Mapbox access token. If not provided, uses MAPBOX_ACCESS_TOKEN env var.
            username: Mapbox username. If not provided, uses MAPBOX_USERNAME env var.
            validate_geometry: Whether to validate geometries and warn about issues.
            use_mapbox_full_upload_cap: If True, use the Mapbox per-file limit (20 GB).
                If False, apply MTU's default upload cap (1 GB).
        """
        self.access_token = access_token or os.environ.get("MAPBOX_ACCESS_TOKEN")
        self.username = username or os.environ.get("MAPBOX_USERNAME")
        self.validate_geometry = validate_geometry
        self.use_mapbox_full_upload_cap = use_mapbox_full_upload_cap
        self._soft_upload_cap_bytes = (
            MAPBOX_MAX_SOURCE_FILE_BYTES
            if use_mapbox_full_upload_cap
            else DEFAULT_UPLOAD_SOFT_CAP_BYTES
        )
        self._soft_upload_cap_gb = (
            MAPBOX_MAX_SOURCE_FILE_SIZE_GB
            if use_mapbox_full_upload_cap
            else DEFAULT_UPLOAD_SOFT_CAP_GB
        )

        if not self.access_token:
            raise ValueError(
                "Mapbox access token required. "
                "Set MAPBOX_ACCESS_TOKEN environment variable or pass access_token parameter."
            )
        if not self.username:
            raise ValueError(
                "Mapbox username required. "
                "Set MAPBOX_USERNAME environment variable or pass username parameter."
            )

        # Set environment variable for tilesets CLI
        os.environ["MAPBOX_ACCESS_TOKEN"] = self.access_token

        # Initialize validator
        self._validator = GeometryValidator() if validate_geometry else None
        self._tilesets_command = self.find_tilesets_command()
        self._use_inprocess_tilesets = False

        if not self._tilesets_command:
            self._use_inprocess_tilesets = self.can_use_inprocess_tilesets()

        if not self._tilesets_command and not self._use_inprocess_tilesets:
            raise ValueError(
                "Mapbox tilesets CLI is required. Install mapbox-tilesets and ensure either "
                "a working 'tilesets' command or Python module import is available."
            )

    @staticmethod
    def find_tilesets_command() -> list[str] | None:
        """Find a runnable tilesets CLI command in PATH or current Python environment."""
        candidates = ["tilesets", "tilesets.exe", "mapbox-tilesets", "mapbox-tilesets.exe"]
        command_candidates: list[list[str]] = []
        is_frozen = bool(getattr(sys, "frozen", False))

        for candidate in candidates:
            found = shutil.which(candidate)
            if found:
                command_candidates.append([found])

        scripts_dir = Path(sys.executable).parent
        for candidate in candidates:
            script_path = scripts_dir / candidate
            if script_path.exists():
                command_candidates.append([str(script_path)])

        if not is_frozen:
            command_candidates.append([sys.executable, "-m", "mapbox_tilesets.scripts.cli"])

        for command in command_candidates:
            if TilesetUploader._is_working_tilesets_command(command):
                return command

        return None

    @staticmethod
    def can_use_inprocess_tilesets() -> bool:
        """Check if mapbox-tilesets CLI module can be invoked in-process."""
        try:
            from mapbox_tilesets.scripts.cli import cli as _cli  # noqa: F401
        except Exception:
            return False
        return True

    @staticmethod
    def _subprocess_no_window_kwargs() -> dict[str, Any]:
        if os.name != "nt":
            return {}

        startupinfo_factory = getattr(subprocess, "STARTUPINFO", None)
        if startupinfo_factory is None:
            return {}

        startupinfo = startupinfo_factory()
        startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
        startupinfo.wShowWindow = 0
        return {
            "creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            "startupinfo": startupinfo,
        }

    @staticmethod
    def _is_working_tilesets_command(command: list[str]) -> bool:
        """Check if a tilesets command can execute."""
        if bool(getattr(sys, "frozen", False)) and command:
            cmd_path = Path(command[0]).resolve()
            current_exe = Path(sys.executable).resolve()
            if cmd_path == current_exe:
                return False

        try:
            result = subprocess.run(
                command + ["--help"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
                **TilesetUploader._subprocess_no_window_kwargs(),
            )
        except Exception:
            return False

        stderr = (result.stderr or "").lower()
        if "fatal error in launcher" in stderr:
            return False

        return result.returncode == 0

    def upload_from_url(
        self,
        url: str,
        config: TilesetConfig,
        format_hint: str | None = None,
        work_dir: str | None = None,
        dry_run: bool = False,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> UploadResult:
        """
        Download data from URL and upload to Mapbox.

        Args:
            url: URL to download GeoJSON or other GIS format from.
            config: Tileset configuration.
            format_hint: Explicit format name (auto-detected if not provided).
            work_dir: Working directory for temporary files.
            dry_run: If True, validate but don't upload.

        Returns:
            UploadResult with upload details.
        """
        work_path = Path(work_dir) if work_dir else Path(tempfile.mkdtemp())
        work_path.mkdir(parents=True, exist_ok=True)

        # Determine file type from URL
        url_lower = url.lower()
        ext = ".geojson"
        for fmt_ext in [".topojson", ".shp", ".gpkg", ".kml", ".kmz", ".fgb", ".parquet", ".gpx"]:
            if fmt_ext in url_lower:
                ext = fmt_ext
                break

        download_path = work_path / f"source{ext}"

        try:
            # Download the file
            self._download_file(url, download_path)
            self._emit_progress(
                progress_callback,
                stage="download_complete",
                message="Download complete",
                percent=10,
            )

            # Upload from the downloaded file
            return self.upload_from_file(
                download_path,
                config,
                format_hint=format_hint,
                dry_run=dry_run,
                progress_callback=progress_callback,
            )

        finally:
            # Clean up if using temp directory
            if not work_dir:
                import shutil

                shutil.rmtree(work_path, ignore_errors=True)

    def upload_from_file(
        self,
        file_path: str | Path,
        config: TilesetConfig,
        format_hint: str | None = None,
        dry_run: bool = False,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> UploadResult:
        """
        Upload a GIS file to Mapbox.

        Args:
            file_path: Path to the file to upload.
            config: Tileset configuration.
            format_hint: Explicit format name (auto-detected if not provided).
            dry_run: If True, validate but don't upload.

        Returns:
            UploadResult with upload details.
        """
        file_path = Path(file_path)
        self._validate_source_file_size(file_path, label="Input file")
        self._ensure_config_ids(config)

        if not config.tileset_id:
            raise ValueError("tileset_id could not be determined")

        result = UploadResult(
            success=False,
            tileset_id=f"{self.username}.{config.tileset_id}",
            source_id=config.source_id,
            dry_run=dry_run,
        )

        try:
            self._emit_progress(
                progress_callback,
                stage="starting",
                message="Starting upload pipeline",
                percent=5,
            )

            # Get converter for the file format
            converter = get_converter(format_name=format_hint, file_path=file_path)
            self._emit_progress(
                progress_callback,
                stage="converting",
                message=f"Converting from {converter.format_name}",
                percent=15,
            )

            # Convert to GeoJSON
            conversion = converter.convert(file_path)
            result.conversion_result = conversion
            result.warnings.extend(conversion.warnings)
            result.steps["convert"] = True
            self._emit_progress(
                progress_callback,
                stage="converted",
                message=f"Converted {conversion.feature_count} features",
                percent=30,
            )

            geojson = conversion.geojson

            # Validate geometry
            if self._validator:
                self._emit_progress(
                    progress_callback,
                    stage="validating",
                    message="Validating geometry",
                    percent=40,
                )
                validation = self._validator.validate(geojson)
                result.validation_result = validation
                result.steps["validate"] = True

                # Add validation warnings to result
                for warning in validation.warnings:
                    if warning.severity in ("warning", "error"):
                        result.warnings.append(f"[{warning.warning_type}] {warning.message}")

                self._emit_progress(
                    progress_callback,
                    stage="validated",
                    message=(
                        f"Validation complete ({validation.valid_feature_count}/"
                        f"{validation.feature_count} valid)"
                    ),
                    percent=50,
                )

            if dry_run:
                result.success = True
                self._emit_progress(
                    progress_callback,
                    stage="dry_run_complete",
                    message="Dry run complete",
                    percent=100,
                )
                return result

            # Write GeoJSON to temp file for upload
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".geojson",
                delete=False,
                encoding="utf-8",
            ) as f:
                json.dump(geojson, f)
                geojson_path = Path(f.name)

            try:
                self._validate_source_file_size(
                    geojson_path,
                    label="Converted GeoJSON payload",
                )

                # Upload source
                self._emit_progress(
                    progress_callback,
                    stage="uploading_source",
                    message="Uploading source to Mapbox",
                    percent=60,
                )
                self._upload_source(geojson_path, config.source_id)
                result.steps["upload_source"] = True

                # Create or update tileset
                full_tileset_id = f"{self.username}.{config.tileset_id}"
                recipe = self._build_recipe(config)
                self._emit_progress(
                    progress_callback,
                    stage="configuring_tileset",
                    message="Configuring tileset recipe",
                    percent=70,
                )

                if self._tileset_exists(full_tileset_id):
                    self._update_recipe(full_tileset_id, recipe)
                    result.steps["update_recipe"] = True
                    self._emit_progress(
                        progress_callback,
                        stage="recipe_updated",
                        message="Existing tileset recipe updated",
                        percent=78,
                    )
                else:
                    self._create_tileset(full_tileset_id, recipe, config)
                    result.steps["create_tileset"] = True
                    self._emit_progress(
                        progress_callback,
                        stage="tileset_created",
                        message="Tileset created",
                        percent=78,
                    )

                # Publish tileset
                self._emit_progress(
                    progress_callback,
                    stage="publishing",
                    message="Publishing tileset job",
                    percent=85,
                )
                job_id = self._publish_tileset(full_tileset_id)
                result.steps["publish"] = True
                result.job_id = job_id

                # Wait for completion
                status = self._wait_for_job(
                    full_tileset_id,
                    job_id,
                    progress_callback=progress_callback,
                )
                result.steps["job_complete"] = True
                result.job_status = status

                result.success = status == "success"
                self._emit_progress(
                    progress_callback,
                    stage="complete" if result.success else "failed",
                    message="Upload complete" if result.success else f"Upload failed: {status}",
                    percent=100,
                )

            finally:
                geojson_path.unlink(missing_ok=True)

        except Exception as e:
            result.error = str(e)

        return result

    @staticmethod
    def _emit_progress(
        callback: Callable[[dict[str, Any]], None] | None,
        stage: str,
        message: str,
        percent: int,
        **extra: Any,
    ) -> None:
        if callback is None:
            return
        payload: dict[str, Any] = {
            "stage": stage,
            "message": message,
            "percent": percent,
        }
        payload.update(extra)
        callback(payload)

    def _ensure_config_ids(self, config: TilesetConfig) -> None:
        """Ensure tileset and source identifiers are populated."""
        if not config.tileset_id:
            config.tileset_id = self._generate_tileset_id(config.tileset_name)

        if not config.source_id:
            config.source_id = config.tileset_id.replace(".", "-")

    @staticmethod
    def _generate_tileset_id(tileset_name: str) -> str:
        """Generate a safe tileset ID from tileset name and timestamp."""
        base = (tileset_name or "tileset").strip().lower()
        base = re.sub(r"[^a-z0-9_-]+", "-", base)
        base = re.sub(r"-+", "-", base).strip("-")
        if not base:
            base = "tileset"

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"{base[:20]}-{timestamp}"

    def _download_file(self, url: str, dest_path: Path) -> None:
        """Download a file from URL."""
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()

        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

    def _validate_source_file_size(self, file_path: Path, label: str = "File") -> None:
        """Validate that a file can be uploaded as a Mapbox source file."""
        file_size_bytes = file_path.stat().st_size
        file_size_gb = file_size_bytes / (1024**3)

        if file_size_bytes > MAPBOX_MAX_SOURCE_FILE_BYTES:
            raise ValueError(
                f"{label} is {file_size_gb:.2f} GB, which exceeds Mapbox's "
                f"{MAPBOX_MAX_SOURCE_FILE_SIZE_GB} GB per-file source upload limit. "
                "Reduce/split the dataset and try again."
            )

        if file_size_bytes <= self._soft_upload_cap_bytes:
            return

        raise ValueError(
            f"{label} is {file_size_gb:.2f} GB, above MTU's current upload cap "
            f"of {self._soft_upload_cap_gb} GB. "
            "Enable Mapbox full upload cap mode to allow larger files (up to 20 GB)."
        )

    def _run_tilesets_command(
        self,
        args: list[str],
        check: bool = True,
        timeout: int = 300,
    ) -> subprocess.CompletedProcess[str]:
        """Run a tilesets CLI command."""
        if self._tilesets_command:
            cmd = self._tilesets_command + args
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=timeout,
                    **self._subprocess_no_window_kwargs(),
                )
            except subprocess.TimeoutExpired as exc:
                cmd_preview = " ".join(cmd)
                raise RuntimeError(
                    f"Tilesets command timed out after {timeout}s: {cmd_preview}"
                ) from exc
        elif self._use_inprocess_tilesets:
            result = self._run_tilesets_inprocess(args)
        else:
            raise RuntimeError("tilesets CLI command is not configured")

        if check and result.returncode != 0:
            detail = self._format_tilesets_command_error(result)
            raise RuntimeError(f"Tilesets command failed: {detail}")
        return result

    @staticmethod
    def _extract_error_message(raw_text: str) -> str:
        """Extract the most useful error message from tilesets CLI output."""
        text = (raw_text or "").strip()
        if not text:
            return ""

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return text

        for line in reversed(lines):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(payload, dict):
                for key in ("message", "error", "detail"):
                    value = payload.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()

            if isinstance(payload, str) and payload.strip():
                return payload.strip()

        return lines[-1]

    def _format_tilesets_command_error(self, result: subprocess.CompletedProcess[str]) -> str:
        """Build a readable tilesets CLI failure message with likely remediation."""
        stderr_message = self._extract_error_message(result.stderr or "")
        stdout_message = self._extract_error_message(result.stdout or "")

        message = (
            stderr_message
            or stdout_message
            or f"Command exited with code {result.returncode}"
        )
        lowered = message.lower()

        if "forbidden" in lowered:
            return (
                f"{message}. Check MAPBOX_ACCESS_TOKEN, verify it can manage tilesets, "
                f"and confirm MAPBOX_USERNAME ('{self.username}') matches the token owner."
            )

        if "unauthorized" in lowered:
            return (
                f"{message}. Your MAPBOX_ACCESS_TOKEN appears invalid or "
                "expired; generate a new token "
                "and retry."
            )

        return message

    def _run_tilesets_inprocess(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Run mapbox-tilesets via Click in-process."""
        import click
        from mapbox_tilesets.scripts.cli import cli as tilesets_cli

        runner = CliRunner()
        env = {"MAPBOX_ACCESS_TOKEN": self.access_token or ""}

        try:
            result = runner.invoke(tilesets_cli, args, env=env, catch_exceptions=True)

            if (
                result.exit_code != 0
                and isinstance(result.exception, AttributeError)
                and "exit" in str(result.exception).lower()
            ):

                def _click_exit_compat(code: object = 0) -> None:
                    if isinstance(code, str):
                        click.echo(code)
                        raise click.exceptions.Exit(0)
                    if isinstance(code, int):
                        raise click.exceptions.Exit(code)
                    raise click.exceptions.Exit(1)

                had_click_exit = hasattr(click, "exit")
                setattr(click, "exit", _click_exit_compat)
                try:
                    result = runner.invoke(tilesets_cli, args, env=env, catch_exceptions=True)
                finally:
                    if not had_click_exit:
                        delattr(click, "exit")

            stdout = getattr(result, "stdout", "") or result.output
            stderr = getattr(result, "stderr", "")
            if result.exit_code != 0 and not stderr and result.exception is not None:
                stderr = str(result.exception)
            return subprocess.CompletedProcess(
                args=["tilesets"] + args,
                returncode=result.exit_code,
                stdout=stdout,
                stderr=stderr,
            )
        except Exception as exc:
            return subprocess.CompletedProcess(
                args=["tilesets"] + args,
                returncode=1,
                stdout="",
                stderr=str(exc),
            )

    def _upload_source(self, file_path: Path, source_id: str | None) -> None:
        """Upload file to tileset source."""
        if source_id is None:
            raise ValueError("source_id is required for uploading")
        self._run_tilesets_command(
            ["upload-source", "--replace", self.username, source_id, str(file_path)]
        )

    def _tileset_exists(self, tileset_id: str) -> bool:
        """Check if tileset already exists."""
        result = self._run_tilesets_command(["status", tileset_id], check=False)
        return result.returncode == 0

    def _build_recipe(self, config: TilesetConfig) -> dict[str, Any]:
        """Build tileset recipe."""
        if config.recipe:
            return config.recipe

        return {
            "version": 1,
            "layers": {
                config.layer_name: {
                    "source": f"mapbox://tileset-source/{self.username}/{config.source_id}",
                    "minzoom": config.min_zoom,
                    "maxzoom": config.max_zoom,
                }
            },
        }

    def _create_tileset(
        self,
        tileset_id: str,
        recipe: dict[str, Any],
        config: TilesetConfig,
    ) -> None:
        """Create a new tileset."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(recipe, f)
            recipe_path = f.name

        try:
            args = [
                "create",
                tileset_id,
                "--recipe",
                recipe_path,
                "--name",
                config.tileset_name,
            ]
            if config.description:
                args.extend(["--description", config.description])
            if config.attribution:
                args.extend(["--attribution", config.attribution])

            self._run_tilesets_command(args)
        finally:
            os.unlink(recipe_path)

    def _update_recipe(self, tileset_id: str, recipe: dict[str, Any]) -> None:
        """Update tileset recipe."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(recipe, f)
            recipe_path = f.name

        try:
            self._run_tilesets_command(["update-recipe", tileset_id, recipe_path])
        finally:
            os.unlink(recipe_path)

    def _publish_tileset(self, tileset_id: str) -> str:
        """Publish tileset and return job ID."""
        result = self._run_tilesets_command(["publish", tileset_id])
        try:
            output = json.loads(result.stdout)
            return output.get("jobId", "")
        except json.JSONDecodeError:
            return ""

    def _wait_for_job(
        self,
        tileset_id: str,
        job_id: str,
        timeout: int = 600,
        poll_interval: int = 10,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
        """Wait for tileset job to complete."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            result = self._run_tilesets_command(["status", tileset_id], check=False)

            elapsed = int(time.time() - start_time)
            self._emit_progress(
                progress_callback,
                stage="publishing_wait",
                message=f"Waiting for Mapbox publish job ({elapsed}s elapsed)",
                percent=90,
                elapsed_seconds=elapsed,
                job_id=job_id,
            )

            if result.returncode == 0:
                try:
                    status_data = json.loads(result.stdout)
                    status = status_data.get("status", "unknown")

                    self._emit_progress(
                        progress_callback,
                        stage="job_status",
                        message=f"Mapbox job status: {status}",
                        percent=95,
                        job_id=job_id,
                        mapbox_status=status,
                    )

                    if status == "success":
                        return "success"
                    elif status in ("failed", "errored"):
                        return f"failed: {status_data.get('message', 'Unknown error')}"
                except json.JSONDecodeError:
                    pass

            time.sleep(poll_interval)

        return "timeout"

    def list_sources(self) -> list[dict[str, Any]]:
        """List all tileset sources for the user."""
        result = self._run_tilesets_command(["list-sources", self.username])
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

    def list_tilesets(self) -> list[dict[str, Any]]:
        """List all tilesets for the user."""
        result = self._run_tilesets_command(["list", self.username])
        try:
            lines = result.stdout.strip().split("\n")
            return [json.loads(line) for line in lines if line]
        except json.JSONDecodeError:
            return []

    def delete_source(self, source_id: str) -> bool:
        """Delete a tileset source."""
        result = self._run_tilesets_command(
            ["delete-source", "--force", self.username, source_id], check=False
        )
        return result.returncode == 0

    def delete_tileset(self, tileset_id: str) -> bool:
        """Delete a tileset."""
        full_id = f"{self.username}.{tileset_id}"
        result = self._run_tilesets_command(["delete", "--force", full_id], check=False)
        return result.returncode == 0

    @staticmethod
    def get_supported_formats() -> list[dict[str, Any]]:
        """Get list of supported input formats."""
        return get_supported_formats()
