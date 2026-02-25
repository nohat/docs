"""Fetch neighborhood boundary data from OpenStreetMap via Overpass API."""

import json
import os
import sys
import time
from pathlib import Path

import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DATA_DIR = Path(__file__).parent / "data"

# Overpass QL query to get neighborhood boundaries for a named city.
# Looks for:
#   - admin_level 9/10 boundaries (sub-city administrative divisions)
#   - place=neighbourhood / place=quarter tagged relations and ways
QUERY_TEMPLATE = """\
[out:json][timeout:120];
area["name"="{city}"]["boundary"="administrative"]->.city;
(
  relation["boundary"="administrative"]["admin_level"~"^(9|10|11)$"](area.city);
  relation["place"~"^(neighbourhood|quarter|suburb)$"](area.city);
  way["place"~"^(neighbourhood|quarter|suburb)$"](area.city);
  node["place"~"^(neighbourhood|quarter|suburb)$"](area.city);
);
out body;
>;
out skel qt;
"""

QUERY_AREA_ID_TEMPLATE = """\
[out:json][timeout:120];
area({area_id})->.city;
(
  relation["boundary"="administrative"]["admin_level"~"^(9|10|11)$"](area.city);
  relation["place"~"^(neighbourhood|quarter|suburb)$"](area.city);
  way["place"~"^(neighbourhood|quarter|suburb)$"](area.city);
  node["place"~"^(neighbourhood|quarter|suburb)$"](area.city);
);
out body;
>;
out skel qt;
"""

# Alternative query using a bounding box instead of a city name
QUERY_BBOX_TEMPLATE = """\
[out:json][timeout:120];
(
  relation["boundary"="administrative"]["admin_level"~"^(9|10|11)$"]({south},{west},{north},{east});
  relation["place"~"^(neighbourhood|quarter|suburb)$"]({south},{west},{north},{east});
  way["place"~"^(neighbourhood|quarter|suburb)$"]({south},{west},{north},{east});
  node["place"~"^(neighbourhood|quarter|suburb)$"]({south},{west},{north},{east});
);
out body;
>;
out skel qt;
"""


def _overpass_query(query: str) -> dict:
    """Execute an Overpass API query and return the JSON response."""
    print(f"Querying Overpass API (this may take a minute)...", file=sys.stderr)
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=180)
    resp.raise_for_status()
    return resp.json()


def _build_geometries(elements: list[dict]) -> list[dict]:
    """Convert raw Overpass elements into GeoJSON features.

    The Overpass response contains nodes, ways, and relations mixed together.
    We need to resolve node references in ways, and way references in relations
    to build actual polygon geometries.
    """
    nodes = {}
    ways = {}
    features = []

    # Index nodes and ways; collect tagged neighborhood nodes
    for el in elements:
        if el["type"] == "node":
            nodes[el["id"]] = (el["lon"], el["lat"])
            # Nodes with a place tag and name are neighborhood point markers
            if "tags" in el and el["tags"].get("name") and el["tags"].get("place"):
                tags = el["tags"]
                features.append({
                    "type": "Feature",
                    "properties": {
                        "name": tags["name"],
                        "place": tags.get("place", ""),
                        "admin_level": tags.get("admin_level", ""),
                        "boundary": tags.get("boundary", ""),
                        "source_type": "node",
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [el["lon"], el["lat"]],
                    },
                })
        elif el["type"] == "way":
            ways[el["id"]] = el.get("nodes", [])

    # Process ways that are standalone neighborhoods (closed polygons)
    for el in elements:
        if el["type"] == "way" and "tags" in el:
            tags = el["tags"]
            name = tags.get("name")
            if not name:
                continue
            nd_ids = el.get("nodes", [])
            coords = [nodes[n] for n in nd_ids if n in nodes]
            if len(coords) >= 4 and coords[0] == coords[-1]:
                features.append(_make_feature(name, tags, [coords]))

    # Process relations (multi-polygon boundaries)
    for el in elements:
        if el["type"] != "relation" or "tags" not in el:
            continue
        tags = el["tags"]
        name = tags.get("name")
        if not name:
            continue

        members = el.get("members", [])
        outer_rings = []
        inner_rings = []

        for member in members:
            if member["type"] != "way":
                continue
            role = member.get("role", "outer")
            way_nds = ways.get(member["ref"], [])
            coords = [nodes[n] for n in way_nds if n in nodes]
            if len(coords) < 2:
                continue
            if role == "inner":
                inner_rings.append(coords)
            else:
                outer_rings.append(coords)

        # Merge way segments into closed rings
        merged_outers = _merge_ways(outer_rings)
        merged_inners = _merge_ways(inner_rings)

        if not merged_outers:
            continue

        # Build polygon(s)
        polygons = []
        for ring in merged_outers:
            if len(ring) >= 4:
                poly = [ring]
                # Attach inner rings that might belong to this outer ring
                for inner in merged_inners:
                    if len(inner) >= 4:
                        poly.append(inner)
                polygons.append(poly)

        if len(polygons) == 1:
            features.append(_make_feature(name, tags, polygons[0]))
        elif len(polygons) > 1:
            features.append(_make_multi_feature(name, tags, polygons))

    return features


def _merge_ways(segments: list[list[tuple]]) -> list[list[tuple]]:
    """Merge way segments into closed rings.

    OSM relations often split boundaries into multiple ways.
    We need to join them end-to-end to form closed polygons.
    """
    if not segments:
        return []

    # Already-closed segments go directly to results
    closed = []
    open_segs = []
    for seg in segments:
        if len(seg) >= 4 and seg[0] == seg[-1]:
            closed.append(seg)
        elif len(seg) >= 2:
            open_segs.append(list(seg))

    # Try to merge open segments
    changed = True
    while changed and open_segs:
        changed = False
        merged = [open_segs.pop(0)]
        remaining = []
        for seg in open_segs:
            appended = False
            for i, m in enumerate(merged):
                if m[-1] == seg[0]:
                    merged[i] = m + seg[1:]
                    appended = True
                    changed = True
                    break
                elif m[-1] == seg[-1]:
                    merged[i] = m + list(reversed(seg))[1:]
                    appended = True
                    changed = True
                    break
                elif m[0] == seg[-1]:
                    merged[i] = seg + m[1:]
                    appended = True
                    changed = True
                    break
                elif m[0] == seg[0]:
                    merged[i] = list(reversed(seg)) + m[1:]
                    appended = True
                    changed = True
                    break
            if not appended:
                remaining.append(seg)
        open_segs = merged + remaining

    for seg in open_segs:
        if len(seg) >= 4 and seg[0] == seg[-1]:
            closed.append(seg)
        elif len(seg) >= 3:
            # Force-close the ring
            seg.append(seg[0])
            if len(seg) >= 4:
                closed.append(seg)

    return closed


def _make_feature(name: str, tags: dict, rings: list[list[tuple]]) -> dict:
    """Create a GeoJSON Polygon feature."""
    return {
        "type": "Feature",
        "properties": {
            "name": name,
            "place": tags.get("place", ""),
            "admin_level": tags.get("admin_level", ""),
            "boundary": tags.get("boundary", ""),
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": rings,
        },
    }


def _make_multi_feature(
    name: str, tags: dict, polygons: list[list[list[tuple]]]
) -> dict:
    """Create a GeoJSON MultiPolygon feature."""
    return {
        "type": "Feature",
        "properties": {
            "name": name,
            "place": tags.get("place", ""),
            "admin_level": tags.get("admin_level", ""),
            "boundary": tags.get("boundary", ""),
        },
        "geometry": {
            "type": "MultiPolygon",
            "coordinates": polygons,
        },
    }


def find_city_areas(city: str) -> list[dict]:
    """Query Overpass for all administrative areas matching a city name.

    Returns a list of dicts with area metadata (id, tags, etc.).
    """
    query = f"""\
[out:json][timeout:30];
area["name"="{city}"]["boundary"="administrative"];
out tags;
"""
    data = _overpass_query(query)
    return data.get("elements", [])


def fetch_city(city: str) -> Path:
    """Fetch neighborhood boundaries for a city and save as GeoJSON.

    If the city name matches multiple OSM areas, prints disambiguation
    info and exits so the user can re-run with --area-id.
    """
    # Disambiguation: check how many areas match
    areas = find_city_areas(city)
    if len(areas) == 0:
        print(f"Error: no OSM area found for '{city}'.", file=sys.stderr)
        print("Try a different spelling, or use --bbox or --area-id.", file=sys.stderr)
        sys.exit(1)
    elif len(areas) > 1:
        print(f"Multiple areas match '{city}':\n", file=sys.stderr)
        for i, area in enumerate(areas, 1):
            tags = area.get("tags", {})
            aid = area["id"]
            name = tags.get("name", "?")
            admin = tags.get("admin_level", "?")
            wikidata = tags.get("wikidata", "")
            is_in = tags.get("is_in", tags.get("is_in:state", ""))
            line = f"  {i}. area_id={aid}  name={name}  admin_level={admin}"
            if wikidata:
                line += f"  wikidata={wikidata}"
            if is_in:
                line += f"  is_in={is_in}"
            print(line, file=sys.stderr)
        print(
            f"\nRe-run with:  neighborhood-lookup fetch --area-id <ID> --name <slug>",
            file=sys.stderr,
        )
        sys.exit(1)

    # Exactly one match — proceed
    query = QUERY_TEMPLATE.format(city=city)
    data = _overpass_query(query)
    elements = data.get("elements", [])
    print(f"Received {len(elements)} raw OSM elements", file=sys.stderr)

    features = _build_geometries(elements)
    print(f"Built {len(features)} neighborhood features", file=sys.stderr)

    if not features:
        print(
            "Warning: no neighborhood features found. Try a different city "
            "name or use --bbox instead.",
            file=sys.stderr,
        )

    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    slug = city.lower().replace(" ", "_").replace(",", "")
    out_path = DATA_DIR / f"{slug}.geojson"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(geojson, f)

    print(f"Saved {len(features)} neighborhoods to {out_path}", file=sys.stderr)
    return out_path


def fetch_area(area_id: int, name: str) -> Path:
    """Fetch neighborhood boundaries using a specific Overpass area ID."""
    query = QUERY_AREA_ID_TEMPLATE.format(area_id=area_id)
    data = _overpass_query(query)
    elements = data.get("elements", [])
    print(f"Received {len(elements)} raw OSM elements", file=sys.stderr)

    features = _build_geometries(elements)
    print(f"Built {len(features)} neighborhood features", file=sys.stderr)

    if not features:
        print(
            "Warning: no neighborhood features found for area_id "
            f"{area_id}.",
            file=sys.stderr,
        )

    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    slug = name.lower().replace(" ", "_").replace(",", "")
    out_path = DATA_DIR / f"{slug}.geojson"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(geojson, f)

    print(f"Saved {len(features)} neighborhoods to {out_path}", file=sys.stderr)
    return out_path


def fetch_bbox(south: float, west: float, north: float, east: float, name: str) -> Path:
    """Fetch neighborhood boundaries within a bounding box."""
    query = QUERY_BBOX_TEMPLATE.format(
        south=south, west=west, north=north, east=east
    )
    data = _overpass_query(query)
    elements = data.get("elements", [])
    print(f"Received {len(elements)} raw OSM elements", file=sys.stderr)

    features = _build_geometries(elements)
    print(f"Built {len(features)} neighborhood polygons", file=sys.stderr)

    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    slug = name.lower().replace(" ", "_").replace(",", "")
    out_path = DATA_DIR / f"{slug}.geojson"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(geojson, f)

    print(f"Saved {len(features)} neighborhoods to {out_path}", file=sys.stderr)
    return out_path
