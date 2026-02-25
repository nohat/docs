"""Point-in-polygon geometry operations for neighborhood lookup."""

import json
import math
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
    nearest_candidate = None  # (distance_deg, feature_props, dataset_name)

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
                geom_shape = shape(geom)
                if geom["type"] == "Point":
                    # Track nearest node for fallback
                    dist = point.distance(geom_shape)
                    if nearest_candidate is None or dist < nearest_candidate[0]:
                        nearest_candidate = (dist, feature.get("properties", {}), dataset_name)
                else:
                    if geom_shape.contains(point):
                        props = feature.get("properties", {})
                        results.append({
                            "name": props.get("name", "Unknown"),
                            "place": props.get("place", ""),
                            "admin_level": props.get("admin_level", ""),
                            "boundary": props.get("boundary", ""),
                            "dataset": dataset_name,
                            "match_type": "polygon",
                        })
            except Exception:
                # Skip malformed geometries
                continue

    # If polygon matches found, return them
    if results:
        return results

    # Fallback: return nearest node-based neighborhood if within threshold
    if nearest_candidate:
        dist_deg, props, ds_name = nearest_candidate
        # Approximate degrees to meters using lat for longitude correction
        dist_m = _degrees_to_meters(dist_deg, lat)
        max_distance_m = 2000  # 2 km threshold
        if dist_m <= max_distance_m:
            results.append({
                "name": props.get("name", "Unknown"),
                "place": props.get("place", ""),
                "admin_level": props.get("admin_level", ""),
                "boundary": props.get("boundary", ""),
                "dataset": ds_name,
                "match_type": "nearest",
                "distance_m": round(dist_m),
            })

    return results


def _degrees_to_meters(dist_deg: float, lat: float) -> float:
    """Convert a rough degree distance to meters at a given latitude."""
    # At the equator, 1 degree ≈ 111,320 m.
    # Longitude degrees shrink by cos(lat).
    # This is a rough approximation treating dist_deg as a Euclidean
    # distance in lon/lat space — good enough for small distances.
    meters_per_deg = 111_320 * math.cos(math.radians(lat))
    return dist_deg * meters_per_deg


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
