"""
Command-line interface for Mapbox Tileset Uploader.
"""

import json
import sys

import click

from mtu import __version__
from mtu.converters import get_converter, get_supported_formats
from mtu.uploader import TilesetConfig, TilesetUploader
from mtu.validators import validate_geojson


# Custom help class for better formatting
class CustomGroup(click.Group):
    """Custom group with better help formatting."""

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Write the help into the formatter with additional info."""
        self.format_usage(ctx, formatter)
        self.format_help_text(ctx, formatter)
        self.format_options(ctx, formatter)
        self.format_commands(ctx, formatter)

        # Add examples section
        formatter.write_paragraph()
        with formatter.section("Examples"):
            formatter.write_text('mtu upload -f data.geojson -i my-tileset -n "My Tileset"')
            formatter.write_text(
                'mtu upload -u https://example.com/data.shp.zip -i boundaries -n "Boundaries"'
            )
            formatter.write_text("mtu convert input.topojson output.geojson --pretty")
            formatter.write_text("mtu formats")
            formatter.write_text("mtu validate data.geojson")


@click.group(cls=CustomGroup)
@click.version_option(version=__version__, prog_name="mapbox-tileset-uploader")
def main() -> None:
    """
    Mapbox Tileset Uploader - Upload GIS data to Mapbox.

    A CLI tool to upload geographic data files to Mapbox as vector tilesets.
    Supports multiple formats including GeoJSON, TopoJSON, Shapefile, GeoPackage, and more.

    \b
    Required environment variables:
      MAPBOX_ACCESS_TOKEN  Your Mapbox access token with tilesets:write scope
      MAPBOX_USERNAME      Your Mapbox username

    \b
    Getting Started:
      1. Set your Mapbox credentials:
         export MAPBOX_ACCESS_TOKEN="your-token"
         export MAPBOX_USERNAME="your-username"

      2. Upload a file:
         mtu upload -f data.geojson -i my-tileset -n "My Tileset"

      3. Check supported formats:
         mtu formats

    \b
    For more help on a specific command:
      mtu COMMAND --help
    """
    pass


@main.command()
def formats() -> None:
    """
    List all supported input formats.

    Shows which formats are available and whether required dependencies are installed.

    \b
    Examples:
      mtu formats
    """
    formats_list = get_supported_formats()

    click.echo("\n📁 Supported Input Formats\n")
    click.echo("-" * 60)

    for fmt in formats_list:
        status = "✅" if fmt["available"] else "❌"
        extensions = ", ".join(fmt["file_extensions"])

        click.echo(f"\n{status} {fmt['format_name']}")
        click.echo(f"   Extensions: {extensions}")

        if fmt["requires_packages"]:
            packages = ", ".join(fmt["requires_packages"])
            click.echo(f"   Requires: {packages}")
            if not fmt["available"]:
                click.echo(f"   Install: pip install {' '.join(fmt['requires_packages'])}")
        else:
            click.echo("   Requires: (built-in)")

    click.echo("\n" + "-" * 60)
    click.echo("\nInstall all optional formats:")
    click.echo("  pip install mapbox-tileset-uploader[all]\n")


@main.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--format", "-f", "format_hint", help="Force a specific format")
@click.option("--verbose", "-v", is_flag=True, help="Show all warnings including info-level")
def validate(
    file_path: str,
    format_hint: str | None,
    verbose: bool,
) -> None:
    """
    Validate a GIS file without uploading.

    Checks for geometry issues, coordinate bounds, and format validity.

    \b
    Examples:
      mtu validate data.geojson
      mtu validate shapefile.shp --verbose
      mtu validate data.json --format geojson
    """
    click.echo(f"\n🔍 Validating: {file_path}\n")

    try:
        # Get converter and convert to GeoJSON
        converter = get_converter(format_name=format_hint, file_path=file_path)
        click.echo(f"   Format: {converter.format_name}")

        result = converter.convert(file_path)
        click.echo(f"   Features: {result.feature_count}")

        if result.warnings:
            click.echo(f"\n⚠️  Conversion warnings ({len(result.warnings)}):")
            for warning in result.warnings:
                click.echo(f"   - {warning}")

        # Validate geometry
        validation = validate_geojson(result.geojson)

        click.echo("\n📊 Geometry Validation:")
        valid_count = validation.valid_feature_count
        total_count = validation.feature_count
        click.echo(f"   Valid features: {valid_count}/{total_count}")
        click.echo(f"   Warnings: {validation.warning_count}")
        click.echo(f"   Errors: {validation.error_count}")

        if validation.warnings:
            # Group by type
            by_type: dict[str, list] = {}
            for w in validation.warnings:
                if not verbose and w.severity == "info":
                    continue
                if w.warning_type not in by_type:
                    by_type[w.warning_type] = []
                by_type[w.warning_type].append(w)

            if by_type:
                click.echo("\n⚠️  Issues found:")
                for wtype, warnings in sorted(by_type.items()):
                    click.echo(f"\n   [{wtype}] ({len(warnings)} occurrences)")
                    # Show first 3 examples
                    for w in warnings[:3]:
                        if w.feature_index is not None:
                            loc = f"feature {w.feature_index}"
                        else:
                            loc = "global"
                        click.echo(f"     • {loc}: {w.message}")
                    if len(warnings) > 3:
                        click.echo(f"     ... and {len(warnings) - 3} more")

        if validation.valid:
            click.echo("\n✅ File is valid for upload")
        else:
            click.echo("\n❌ File has errors that may cause issues")
            sys.exit(1)

    except Exception as e:
        click.echo(f"\n❌ Validation failed: {e}")
        sys.exit(1)


@main.command()
@click.option("--url", "-u", help="URL to download GIS data from")
@click.option("--file", "-f", "file_path", type=click.Path(exists=True), help="Local file path")
@click.option(
    "--id", "-i", "tileset_id", required=True, help="Tileset ID (without username prefix)"
)
@click.option("--name", "-n", "tileset_name", required=True, help="Human-readable tileset name")
@click.option("--format", "format_hint", help="Force a specific input format")
@click.option("--source-id", "-s", help="Source ID (defaults to tileset ID)")
@click.option("--layer", "-l", "layer_name", default="data", help="Layer name in the tileset")
@click.option("--min-zoom", default=0, type=int, help="Minimum zoom level (0-22)")
@click.option("--max-zoom", default=10, type=int, help="Maximum zoom level (0-22)")
@click.option("--description", "-d", default="", help="Tileset description")
@click.option("--attribution", "-a", default="", help="Tileset attribution")
@click.option("--recipe", "-r", type=click.Path(exists=True), help="Custom recipe JSON file")
@click.option("--work-dir", "-w", type=click.Path(), help="Working directory for temp files")
@click.option("--no-validate", is_flag=True, help="Skip geometry validation")
@click.option("--dry-run", is_flag=True, help="Validate without uploading")
@click.option("--token", envvar="MAPBOX_ACCESS_TOKEN", help="Mapbox access token")
@click.option("--username", envvar="MAPBOX_USERNAME", help="Mapbox username")
def upload(
    url: str | None,
    file_path: str | None,
    tileset_id: str,
    tileset_name: str,
    format_hint: str | None,
    source_id: str | None,
    layer_name: str,
    min_zoom: int,
    max_zoom: int,
    description: str,
    attribution: str,
    recipe: str | None,
    work_dir: str | None,
    no_validate: bool,
    dry_run: bool,
    token: str | None,
    username: str | None,
) -> None:
    """
    Upload GIS data to Mapbox as a vector tileset.

    Provide either --url to download from a remote source, or --file for a local file.
    Supports GeoJSON, TopoJSON, Shapefile, GeoPackage, KML, FlatGeobuf, GeoParquet, GPX.

    \b
    Examples:
      # From GeoJSON file
      mtu upload -f data.geojson -i my-tileset -n "My Tileset"

      # From Shapefile (zipped)
      mtu upload -f boundaries.shp.zip -i boundaries -n "Boundaries"

      # From URL with custom zoom
      mtu upload -u https://example.com/data.gpkg -i places -n "Places" --max-zoom 14

      # From GeoPackage with specific format
      mtu upload -f data.gpkg -i admin -n "Admin" --format geopackage

      # Dry run to validate
      mtu upload -f data.geojson -i test -n "Test" --dry-run
    """
    if not url and not file_path:
        raise click.UsageError("Either --url or --file must be provided")

    if url and file_path:
        raise click.UsageError("Cannot specify both --url and --file")

    # Load custom recipe if provided
    custom_recipe = {}
    if recipe:
        with open(recipe, encoding="utf-8") as f:
            custom_recipe = json.load(f)

    # Build configuration
    config = TilesetConfig(
        tileset_id=tileset_id,
        tileset_name=tileset_name,
        source_id=source_id,
        layer_name=layer_name,
        min_zoom=min_zoom,
        max_zoom=max_zoom,
        description=description,
        attribution=attribution,
        recipe=custom_recipe,
    )

    try:
        uploader = TilesetUploader(
            access_token=token,
            username=username,
            validate_geometry=not no_validate,
        )
    except ValueError as e:
        raise click.ClickException(str(e))

    click.echo(f"\n📦 Uploading tileset: {username}.{tileset_id}")
    click.echo(f"   Name: {tileset_name}")
    click.echo(f"   Zoom: {min_zoom}-{max_zoom}")

    if dry_run:
        click.echo("   Mode: DRY RUN (validation only)")

    try:
        if url:
            click.echo(f"   Source: {url}")
            result = uploader.upload_from_url(
                url, config, format_hint=format_hint, work_dir=work_dir, dry_run=dry_run
            )
        else:
            click.echo(f"   Source: {file_path}")
            result = uploader.upload_from_file(
                file_path,
                config,
                format_hint=format_hint,
                dry_run=dry_run,  # type: ignore
            )

        # Show conversion info
        if result.conversion_result:
            click.echo(f"   Format: {result.conversion_result.source_format}")
            click.echo(f"   Features: {result.conversion_result.feature_count}")

        # Show warnings
        if result.warnings:
            click.echo(f"\n⚠️  Warnings ({len(result.warnings)}):")
            for warning in result.warnings[:10]:  # Limit display
                click.echo(f"   - {warning}")
            if len(result.warnings) > 10:
                click.echo(f"   ... and {len(result.warnings) - 10} more")

        if result.success:
            click.echo("\n✅ Upload successful!")
            click.echo(f"   Tileset ID: {result.tileset_id}")
            if not dry_run:
                click.echo(f"   View at: https://studio.mapbox.com/tilesets/{result.tileset_id}/")
        else:
            click.echo("\n❌ Upload failed!")
            if result.error:
                click.echo(f"   Error: {result.error}")
            sys.exit(1)

    except Exception as e:
        raise click.ClickException(str(e))


@main.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.argument("output_file", type=click.Path())
@click.option("--format", "-f", "format_hint", help="Force a specific input format")
@click.option("--object", "-o", "object_name", help="TopoJSON object name to convert")
@click.option("--pretty", "-p", is_flag=True, help="Pretty-print output JSON")
def convert(
    input_file: str,
    output_file: str,
    format_hint: str | None,
    object_name: str | None,
    pretty: bool,
) -> None:
    """
    Convert a GIS file to GeoJSON.

    Supports TopoJSON, Shapefile, GeoPackage, KML, FlatGeobuf, GeoParquet, and GPX.

    \b
    Examples:
      mtu convert input.topojson output.geojson
      mtu convert boundaries.shp boundaries.geojson --pretty
      mtu convert data.gpkg data.geojson
      mtu convert track.gpx track.geojson
    """
    click.echo(f"\n🔄 Converting: {input_file}")

    try:
        # Get converter
        converter = get_converter(format_name=format_hint, file_path=input_file)
        click.echo(f"   Format: {converter.format_name}")

        # Convert (pass object_name for TopoJSON)
        if object_name and converter.format_name == "TopoJSON":
            result = converter.convert(input_file, object_name=object_name)
        else:
            result = converter.convert(input_file)

        # Show warnings
        if result.warnings:
            click.echo("\n⚠️  Warnings:")
            for warning in result.warnings:
                click.echo(f"   - {warning}")

        # Write output
        with open(output_file, "w", encoding="utf-8") as f:
            if pretty:
                json.dump(result.geojson, f, indent=2, ensure_ascii=False)
            else:
                json.dump(result.geojson, f, ensure_ascii=False)

        click.echo(f"\n✅ Converted {result.feature_count} features to {output_file}")

    except Exception as e:
        raise click.ClickException(str(e))


@main.command("list-sources")
@click.option("--token", envvar="MAPBOX_ACCESS_TOKEN", help="Mapbox access token")
@click.option("--username", envvar="MAPBOX_USERNAME", help="Mapbox username")
def list_sources(token: str | None, username: str | None) -> None:
    """
    List all tileset sources for your account.

    \b
    Examples:
      mtu list-sources
    """
    try:
        uploader = TilesetUploader(access_token=token, username=username)
        sources = uploader.list_sources()

        if not sources:
            click.echo("\n📂 No tileset sources found.\n")
            return

        click.echo(f"\n📂 Found {len(sources)} tileset source(s):\n")
        for source in sources:
            if isinstance(source, dict):
                source_id = source.get("id", source)
                size = source.get("size", "")
                size_str = f" ({size} bytes)" if size else ""
                click.echo(f"   • {source_id}{size_str}")
            else:
                click.echo(f"   • {source}")
        click.echo()

    except Exception as e:
        raise click.ClickException(str(e))


@main.command("list-tilesets")
@click.option("--token", envvar="MAPBOX_ACCESS_TOKEN", help="Mapbox access token")
@click.option("--username", envvar="MAPBOX_USERNAME", help="Mapbox username")
def list_tilesets(token: str | None, username: str | None) -> None:
    """
    List all tilesets for your account.

    \b
    Examples:
      mtu list-tilesets
    """
    try:
        uploader = TilesetUploader(access_token=token, username=username)
        tilesets = uploader.list_tilesets()

        if not tilesets:
            click.echo("\n🗺️  No tilesets found.\n")
            return

        click.echo(f"\n🗺️  Found {len(tilesets)} tileset(s):\n")
        for tileset in tilesets:
            if isinstance(tileset, dict):
                name = tileset.get("name", "Unnamed")
                tileset_id = tileset.get("id", "")
                status = tileset.get("status", "")
                status_icon = (
                    "✅" if status == "success" else "⏳" if status == "processing" else "❓"
                )
                click.echo(f"   {status_icon} {name}")
                click.echo(f"      ID: {tileset_id}")
            else:
                click.echo(f"   • {tileset}")
        click.echo()

    except Exception as e:
        raise click.ClickException(str(e))


@main.command("delete-source")
@click.argument("source_id")
@click.option("--token", envvar="MAPBOX_ACCESS_TOKEN", help="Mapbox access token")
@click.option("--username", envvar="MAPBOX_USERNAME", help="Mapbox username")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def delete_source(
    source_id: str,
    token: str | None,
    username: str | None,
    yes: bool,
) -> None:
    """
    Delete a tileset source.

    \b
    Examples:
      mtu delete-source my-source-id
      mtu delete-source my-source-id --yes
    """
    if not yes:
        click.confirm(f"Are you sure you want to delete source '{source_id}'?", abort=True)

    try:
        uploader = TilesetUploader(access_token=token, username=username)
        if uploader.delete_source(source_id):
            click.echo(f"\n✅ Deleted source: {source_id}\n")
        else:
            click.echo(f"\n❌ Failed to delete source: {source_id}\n")
            sys.exit(1)

    except Exception as e:
        raise click.ClickException(str(e))


@main.command("delete-tileset")
@click.argument("tileset_id")
@click.option("--token", envvar="MAPBOX_ACCESS_TOKEN", help="Mapbox access token")
@click.option("--username", envvar="MAPBOX_USERNAME", help="Mapbox username")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def delete_tileset(
    tileset_id: str,
    token: str | None,
    username: str | None,
    yes: bool,
) -> None:
    """
    Delete a tileset.

    \b
    Examples:
      mtu delete-tileset my-tileset-id
      mtu delete-tileset my-tileset-id --yes
    """
    if not yes:
        click.confirm(f"Are you sure you want to delete tileset '{tileset_id}'?", abort=True)

    try:
        uploader = TilesetUploader(access_token=token, username=username)
        if uploader.delete_tileset(tileset_id):
            click.echo(f"\n✅ Deleted tileset: {tileset_id}\n")
        else:
            click.echo(f"\n❌ Failed to delete tileset: {tileset_id}\n")
            sys.exit(1)

    except Exception as e:
        raise click.ClickException(str(e))


@main.command()
def info() -> None:
    """
    Show tool information and configuration help.

    \b
    Examples:
      mtu info
    """
    click.echo(f"""
╔══════════════════════════════════════════════════════════════╗
║         Mapbox Tileset Uploader v{__version__}                      ║
╚══════════════════════════════════════════════════════════════╝

📦 A CLI tool to upload GIS data to Mapbox as vector tilesets.

🔧 CONFIGURATION
   Set these environment variables before use:

   export MAPBOX_ACCESS_TOKEN="your-token-here"
   export MAPBOX_USERNAME="your-username"

   Token scopes required:
   • tilesets:write
   • tilesets:read
   • tilesets:list

   Get a token at: https://account.mapbox.com/access-tokens/

📁 SUPPORTED FORMATS
   Run 'mtu formats' to see all supported formats

📚 COMMANDS
   mtu upload      Upload GIS file to Mapbox
    mtu ui          Launch desktop uploader UI
   mtu convert     Convert GIS file to GeoJSON
   mtu validate    Validate a GIS file
   mtu formats     List supported formats
   mtu list-*      List sources/tilesets
   mtu delete-*    Delete sources/tilesets

🔗 LINKS
    Documentation: https://github.com/ocha-rosea/mapbox-tileset-uploader
   Mapbox Studio: https://studio.mapbox.com/tilesets/
""")


@main.command()
def ui() -> None:
    """Launch desktop UI for uploading GIS files to Mapbox."""
    try:
        from mtu.ui import launch_ui
    except Exception as e:
        raise click.ClickException(f"Desktop UI is not available in this environment: {e}")

    launch_ui()


if __name__ == "__main__":
    main()
