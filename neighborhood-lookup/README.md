# neighborhood-lookup

A CLI tool that determines what neighborhood you're in from a latitude/longitude coordinate. Uses OpenStreetMap boundary data and runs entirely locally after an initial data fetch.

## How it works

1. **Fetch** neighborhood boundary polygons from OpenStreetMap's Overpass API for a city or bounding box
2. **Store** them locally as GeoJSON files
3. **Lookup** which polygon contains your lat/lon using point-in-polygon geometry

## Install

```bash
cd neighborhood-lookup
pip install -e .
```

## Usage

### 1. Download neighborhood data for a city

```bash
# By city name (must match OSM naming)
neighborhood-lookup fetch --city "San Francisco"

# By bounding box (south,west,north,east)
neighborhood-lookup fetch --bbox 37.7,-122.52,37.82,-122.35 --name sf
```

### 2. Look up your neighborhood

```bash
neighborhood-lookup lookup 37.7749 -122.4194
# => Mission  (neighbourhood)  — dataset: san_francisco

# JSON output
neighborhood-lookup lookup 37.7749 -122.4194 --json

# Search a specific dataset
neighborhood-lookup lookup 37.7749 -122.4194 --dataset san_francisco
```

### 3. List available data

```bash
# List downloaded datasets
neighborhood-lookup list --datasets

# List all neighborhood names
neighborhood-lookup list

# List neighborhoods in a specific dataset
neighborhood-lookup list --dataset san_francisco
```

## Run without installing

```bash
python -m neighborhood_lookup fetch --city "Portland"
python -m neighborhood_lookup lookup 45.5231 -122.6765
```

## Data storage

Downloaded boundary data is stored as GeoJSON files in `neighborhood_lookup/data/`. Each city or region gets its own file. These files are `.gitignore`d by default since they can be re-fetched at any time.

## How the OSM query works

The tool queries OpenStreetMap for:
- Administrative boundaries at levels 9, 10, 11 (sub-city divisions)
- Features tagged `place=neighbourhood`, `place=quarter`, or `place=suburb`

These are converted from raw OSM elements (nodes, ways, relations) into GeoJSON polygons. Multi-part boundaries are automatically merged from way segments into closed rings.

## Limitations

- Neighborhood boundaries in OSM vary in completeness by city. Some cities have thorough coverage, others are sparse.
- The Overpass API has rate limits. Avoid hammering it with rapid repeated fetches.
- City names must match what's in OSM. If `--city` returns no results, try browsing [openstreetmap.org](https://www.openstreetmap.org) to find the exact name, or use `--bbox` instead.
