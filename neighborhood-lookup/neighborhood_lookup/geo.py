"""Point-in-polygon geometry operations for neighborhood lookup."""

import json
from pathlib import Path

from shapely.geometry import Point, shape

DATA_DIR = Path(__file__).parent / "data"


def _load_geojson(path: Path) -> dict:
    """Load a GeoJSON file."""
    with open(path) as f:
        return json.load(f)


def _list_datasets() -> list[Path]:
    """List all available GeoJSON datasets."""
    return sorted(DATA_DIR.glob("*.geojson"))


def lookup(lat: float, lon: float, dataset: str | None = None) -> list[dict]:
    """Find which neighborhood(s) contain the given point.

    Args:
        lat: Latitude
        lon: Longitude
        dataset: Optional specific dataset filename (without .geojson).
                 If None, searches all available datasets.

    Returns:
        List of matching neighborhood dicts with name and properties.
    """
    point = Point(lon, lat)  # Shapely uses (x, y) = (lon, lat)
    results = []

    if dataset:
        paths = [DATA_DIR / f"{dataset}.geojson"]
    else:
        paths = _list_datasets()

    if not paths:
        return results

    for path in paths:
        if not path.exists():
            continue
        geojson = _load_geojson(path)
        dataset_name = path.stem

        for feature in geojson.get("features", []):
            geom = feature.get("geometry")
            if not geom:
                continue
            try:
                polygon = shape(geom)
                if polygon.contains(point):
                    props = feature.get("properties", {})
                    results.append({
                        "name": props.get("name", "Unknown"),
                        "place": props.get("place", ""),
                        "admin_level": props.get("admin_level", ""),
                        "boundary": props.get("boundary", ""),
                        "dataset": dataset_name,
                    })
            except Exception:
                # Skip malformed geometries
                continue

    return results


def list_neighborhoods(dataset: str | None = None) -> list[str]:
    """List all neighborhood names in a dataset."""
    names = []

    if dataset:
        paths = [DATA_DIR / f"{dataset}.geojson"]
    else:
        paths = _list_datasets()

    for path in paths:
        if not path.exists():
            continue
        geojson = _load_geojson(path)
        for feature in geojson.get("features", []):
            name = feature.get("properties", {}).get("name")
            if name:
                names.append(name)

    return sorted(set(names))
