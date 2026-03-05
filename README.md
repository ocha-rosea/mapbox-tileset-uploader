# Mapbox Tileset Uploader

Mapbox Tileset Uploader (`mtu`) is a Python package for preparing and publishing GIS data to Mapbox vector tilesets. It provides three interfaces: a CLI, a Python API, and a desktop UI. The project includes a modular converter pipeline that normalizes supported GIS formats to GeoJSON before validation, recipe creation, and tileset publishing.

[![PyPI version](https://img.shields.io/pypi/v/mtu.svg)](https://pypi.org/project/mtu/)
[![PyPI Downloads](https://img.shields.io/pypi/dm/mtu.svg)](https://pypi.org/project/mtu/)
[![Python 3.10+](https://img.shields.io/pypi/pyversions/mtu.svg)](https://pypi.org/project/mtu/)
[![CI](https://github.com/ocha-rosea/mapbox-tileset-uploader/actions/workflows/ci.yml/badge.svg)](https://github.com/ocha-rosea/mapbox-tileset-uploader/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

## Features


- **Upload**: GIS files to Mapbox Tiling Service (MTS)
- **Multi-format support**: GeoJSON, TopoJSON, Shapefile, GeoPackage, KML/KMZ, FlatGeobuf, GeoParquet, GPX
- **Geometry validation**: warns about invalid geometries without modifying data
- **Remote sources**: download and upload from URLs
- **Conversion pipeline**: automatic format detection and conversion to GeoJSON
- **Configurable output**: zoom levels, layer names, and recipes
- **Interfaces**: CLI, Python API, and desktop UI
- **Architecture**: modular converter system with optional dependencies

## Installation

### Basic Installation (GeoJSON & TopoJSON only)

```bash
pip install mtu
```

### With Optional Format Support

```bash
# Shapefile support
pip install mtu[shapefile]

# GeoPackage, KML, FlatGeobuf support (via fiona)
pip install mtu[fiona]

# GeoParquet support
pip install mtu[geoparquet]

# GPX support
pip install mtu[gpx]

# Geometry validation (via shapely)
pip install mtu[validation]

# All formats and validation
pip install mtu[all-formats]

# All features including dev tools
pip install mtu[all]
```

### Install from Source

```bash
git clone https://github.com/ocha-rosea/mapbox-tileset-uploader.git
cd mapbox-tileset-uploader
pip install -e ".[all]"
```

## Supported Formats

| Format | Extensions | Dependencies | Notes |
| ------ | ---------- | ------------ | ----- |
| GeoJSON | `.geojson`, `.json` | None | Native support |
| TopoJSON | `.topojson` | None | Full decoder with transform support |
| Shapefile | `.shp`, `.zip` | `pyshp` | Supports zipped shapefiles |
| GeoPackage | `.gpkg` | `fiona` | Supports layer selection |
| KML/KMZ | `.kml`, `.kmz` | `fiona` | Handles zipped KMZ |
| FlatGeobuf | `.fgb` | `fiona` | Cloud-optimized format |
| GeoParquet | `.parquet`, `.geoparquet` | `geopandas`, `pyarrow` | Columnar format |
| GPX | `.gpx` | `gpxpy` | Tracks, routes, waypoints |

Check available formats with:

```bash
mtu formats
```

## Architecture

```mermaid
flowchart LR
  subgraph Interfaces["Entry Points"]
    CLI[CLI: mtu]
    UI[Desktop UI: mtu ui]
    API[Python API]
  end

  subgraph Core["Core Upload Engine src/mtu/uploader.py"]
    Input["Input handler file or URL"]
    Detect["Format detection"]
    Registry["Converter registry"]
    Convert["Format converter to GeoJSON"]
    Validate["Geometry validator optional"]
    Recipe["Recipe and tileset config builder"]
    Upload["Upload and publish orchestration"]
  end

  subgraph Integrations["External Services"]
    Files["Local or remote GIS data"]
    MbxCLI["Mapbox Tilesets CLI"]
    MTS["Mapbox Tiling Service"]
    Studio["Mapbox Studio tileset"]
  end

  CLI --> Input
  UI --> Input
  API --> Input

  Files --> Input
  Input --> Detect --> Registry --> Convert --> Validate --> Recipe --> Upload
  Upload --> MbxCLI --> MTS --> Studio
```

## Data Flow Diagram

```mermaid
flowchart TD
  A["User starts upload from CLI, Desktop UI, or API"] --> B{Input source}
  B -->|Local file| C[Read from disk]
  B -->|Remote URL| D[Download to temp file]

  C --> E[Detect extension / format]
  D --> E

  E --> F[Resolve converter from registry]
  F --> G["Convert input to GeoJSON FeatureCollection"]
  G --> H{Validation enabled?}

  H -->|Yes| I[Run geometry validator]
  I --> J[Collect warnings]
  H -->|No| K[Skip validator]

  J --> L["Build source and recipe payload"]
  K --> L

  L --> M[Create/replace tileset source]
  M --> N[Create/update recipe]
  N --> O[Publish tileset]
  O --> P[Poll publish job status]
  P --> Q{Completed?}

  Q -->|Success| R["Return UploadResult and Studio link"]
  Q -->|Failed| S[Return parsed actionable error]
```

## Prerequisites

1. **Mapbox Account**: Sign up at [mapbox.com](https://www.mapbox.com/)
2. **Access Token**: Create a token with the following scopes:
   - `tilesets:write`
   - `tilesets:read`
   - `tilesets:list`

Set your credentials as environment variables:

```bash
export MAPBOX_ACCESS_TOKEN="your-token-here"
export MAPBOX_USERNAME="your-username"
```

## CLI Usage

The CLI command is `mtu`.

### Upload from URL

```bash
mtu upload \
  --url https://example.com/data.geojson \
  --id my-tileset \
  --name "My Tileset"
```

### Upload from Local File

```bash
mtu upload \
  --file data.geojson \
  --id my-tileset \
  --name "My Tileset"
```

### Desktop UI (Windows/macOS/Linux)

Launch the desktop uploader interface:

```bash
mtu ui
```

Or use the dedicated script:

```bash
mtu-ui
```

The desktop app provides:

- Intro/welcome page (first screen) with workflow, zoom defaults, and Mapbox cost/limit notes
- GIS file picker (including `.geojson` and zipped shapefile `.zip`)
- Mapbox credentials config panel (saved to `~/.mtu/desktop_config.json`)
- Tileset controls for final tileset name, zoom range, description, and attribution
- Mapbox capacity guard (user-configured MB capacity/usage) to block uploads when projected usage exceeds limit
- Optional description, attribution, validation toggle, and dry-run mode
- Auto-generated tileset ID (reported in the status log), warnings, and Mapbox Studio link on success

### Upload with Custom Options

```bash
mtu upload \
  --file data.topojson \
  --id boundaries-adm1 \
  --name "Administrative Boundaries Level 1" \
  --layer boundaries \
  --min-zoom 2 \
  --max-zoom 12 \
  --description "Admin level 1 boundaries" \
  --attribution "© OpenStreetMap contributors"
```

### Convert TopoJSON to GeoJSON

```bash
mtu convert input.topojson output.geojson --pretty
```

### Convert Any Supported Format

```bash
# Shapefile to GeoJSON
mtu convert boundaries.shp boundaries.geojson

# GeoPackage to GeoJSON
mtu convert data.gpkg output.geojson

# Zipped shapefile
mtu convert archive.zip output.geojson
```

### Validate GIS Files

Validate geometry without uploading:

```bash
mtu validate data.geojson
mtu validate boundaries.shp --verbose
```

### Show Available Formats

```bash
mtu formats
```

### Show Configuration Help

```bash
mtu info
```

### List Resources

```bash
# List all tileset sources
mtu list-sources

# List all tilesets
mtu list-tilesets
```

### Delete Resources

```bash
# Delete a tileset source
mtu delete-source my-source-id

# Delete a tileset
mtu delete-tileset my-tileset-id
```

### Dry Run Mode

Validate your file without uploading:

```bash
mtu upload --file data.geojson --id test --name "Test" --dry-run
```

## Python API Usage

```python
from mtu import TilesetUploader
from mtu.uploader import TilesetConfig

# Initialize uploader (uses environment variables by default)
uploader = TilesetUploader()

# Or provide credentials explicitly
uploader = TilesetUploader(
    access_token="your-token",
    username="your-username"
)

# Configure the tileset
config = TilesetConfig(
    tileset_id="my-tileset",
    tileset_name="My Tileset",
    layer_name="data",
    min_zoom=0,
    max_zoom=10,
    description="My geographic data"
)

# Upload from URL
results = uploader.upload_from_url(
    url="https://example.com/data.geojson",
    config=config
)

# Upload from local file
results = uploader.upload_from_file(
    file_path="data.geojson",
    config=config
)

if results.success:
    print(f"Tileset uploaded: {results.tileset_id}")
    if results.warnings:
        print(f"Warnings: {results.warnings}")
else:
    print(f"Error: {results.error}")
```

### Upload with Validation

```python
# Enable geometry validation (warns but doesn't modify data)
uploader = TilesetUploader(validate_geometry=True)

results = uploader.upload_from_file("data.geojson", config)

# Check validation results
if results.validation_result:
    for warning in results.validation_result.warnings:
        print(f"  [{warning.severity}] {warning.message}")
```

### Using Format Converters

```python
from mtu.converters import get_converter, get_supported_formats

# List available formats
formats = get_supported_formats()
for fmt in formats:
    status = "✓" if fmt["available"] else "✗ (missing deps)"
    print(f"{fmt['format_name']}: {status}")

# Convert any supported format
converter = get_converter(file_path="data.shp")  # Auto-detect by extension
result = converter.convert("data.shp")

print(f"Converted {result.feature_count} features from {result.source_format}")
print(f"Warnings: {result.warnings}")

# Or specify format explicitly
converter = get_converter(format_name="geopackage")
result = converter.convert("data.gpkg", layer_name="boundaries")
```

### Geometry Validation

```python
from mtu import validate_geojson, GeometryValidator

# Quick validation
result = validate_geojson(geojson_data)
print(f"Valid: {result.valid}, Features: {result.feature_count}")

# Custom validation options
validator = GeometryValidator(
    check_coordinates=True,   # Check coordinate bounds
    check_winding=True,       # Check polygon winding order  
    check_duplicates=True,    # Check duplicate vertices
    check_closure=True,       # Check ring closure
    check_intersections=True, # Check self-intersections (requires shapely)
    max_warnings=100          # Limit warnings
)

result = validator.validate(geojson_data)
for warning in result.warnings:
    print(f"Feature {warning.feature_index}: {warning.message}")
```

### TopoJSON Conversion

```python
from mtu.converters import get_converter

# Convert TopoJSON to GeoJSON
converter = get_converter(format_name="topojson")
result = converter.convert(topojson_data)
geojson = result.geojson

# From file
result = converter.convert("data.topojson")

# Select specific object in TopoJSON
result = converter.convert(topojson_data, object_name="countries")
```

## Custom Recipes

For advanced configurations, provide a custom MTS recipe:

```bash
mtu upload \
  --file data.geojson \
  --id my-tileset \
  --name "My Tileset" \
  --recipe custom-recipe.json
```

Recipe file example (`custom-recipe.json`):

```json
{
  "version": 1,
  "layers": {
    "boundaries": {
      "source": "mapbox://tileset-source/{username}/{source-id}",
      "minzoom": 0,
      "maxzoom": 14,
      "features": {
        "simplify": {
          "outward_only": true,
          "distance": 1
        }
      }
    }
  }
}
```

## GitHub Actions Integration

Use in your CI/CD pipeline:

```yaml
name: Upload Tilesets

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  upload:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install mtu

      - name: Upload tileset
        env:
          MAPBOX_ACCESS_TOKEN: ${{ secrets.MAPBOX_ACCESS_TOKEN }}
          MAPBOX_USERNAME: ${{ secrets.MAPBOX_USERNAME }}
        run: |
          mtu upload \
            --file data.geojson \
            --id my-tileset \
            --name "My Tileset"
```

## Development

### Build Windows Executable (Self-Contained)

You can package the desktop UI as a self-contained Windows executable using PyInstaller.

Use a non-conda CPython interpreter (python.org build). Conda-based interpreters can produce
`_tkinter` DLL load failures in packaged apps.

Suggested setup:

```powershell
winget install -e --id Python.Python.3.11
py -3.11 -m venv C:\Users\<you>\mtu-winbuild
C:\Users\<you>\mtu-winbuild\Scripts\python.exe -m pip install --upgrade pip
```

From the project root:

```powershell
./scripts/build_windows_exe.ps1 -PythonPath C:\Users\<you>\mtu-winbuild\Scripts\python.exe
```

PyInstaller may generate `.spec` files during local packaging. These are optional build recipes;
the project build script above does not require committing them.

This creates a self-contained app in `dist/mtu-desktop/` (recommended, onedir mode).

To create a portable ZIP (shareable folder build):

```powershell
Compress-Archive -Path .\dist\mtu-desktop\* -DestinationPath .\dist\mtu-desktop-portable.zip -Force
```

Run it by extracting the ZIP, then launching:

```powershell
./mtu-desktop.exe
```

If you build with an alternate output name (for example `mtu-desktop-si`), use the matching folder/exe name.

For a single-file executable:

```powershell
./scripts/build_windows_exe.ps1 -PythonPath C:\Users\<you>\mtu-winbuild\Scripts\python.exe -OneFile
```

Notes:

- The generated executable includes Python runtime and dependencies.
- If your system `tilesets.exe` launcher is broken, MTU automatically falls back to the in-process `mapbox-tilesets` module.
- For best reliability and startup speed, prefer onedir mode.
- UI startup window state (maximized/full-size on launch) is controlled in `src/mtu/ui.py` and applies to both source and packaged builds.

### GitHub Release Automation (Semantic + Portable ZIP)

This repository includes a manual release workflow with semantic version bumping.

In GitHub Actions, run the `Release` workflow manually and choose:

- `bump_type`: `patch`, `minor`, or `major`
- `prerelease`: `true/false`
- `dry_run`: `true/false`

When `dry_run` is `false`, the workflow will:

1. Bump version in `pyproject.toml` and push commit
2. Build Python distributions (`.whl`, `.tar.gz`)
3. Build Linux and Windows desktop portable artifacts
4. Create a GitHub Release and attach all artifacts
5. Publish the Python package to PyPI (if PyPI environment is configured)

Release assets include:

- Wheel: `*.whl`
- Source dist: `*.tar.gz`
- Linux portable archive: `ROSEA-MTU-v<version>-linux-portable.tar.gz`
- Windows portable app: `ROSEA-MTU-v<version>-portable.zip`

The Windows portable ZIP is versioned on releases as:
`ROSEA-MTU-v<version>-portable.zip`

The Linux portable archive is versioned on releases as:
`ROSEA-MTU-v<version>-linux-portable.tar.gz`

### Setup

```bash
git clone https://github.com/ocha-rosea/mapbox-tileset-uploader.git
cd mapbox-tileset-uploader
pip install -e ".[all]"
```

### Run Tests

```bash
pytest
```

### Code Formatting

```bash
black src tests
ruff check src tests
```

### Type Checking

```bash
mypy src
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Related Projects

- [mapbox-tilesets](https://github.com/mapbox/tilesets-cli) - Official Mapbox Tilesets CLI
- [geoBoundaries](https://www.geoboundaries.org/) - Open political boundary data
