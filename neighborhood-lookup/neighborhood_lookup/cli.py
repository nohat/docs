"""CLI interface for neighborhood lookup tool."""

import argparse
import json
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def cmd_fetch(args):
    """Handle the 'fetch' subcommand."""
    from neighborhood_lookup.fetch import fetch_area, fetch_bbox, fetch_city

    if args.area_id:
        name = args.name or f"area_{args.area_id}"
        path = fetch_area(args.area_id, name)
    elif args.bbox:
        parts = [float(x.strip()) for x in args.bbox.split(",")]
        if len(parts) != 4:
            print("Error: --bbox requires exactly 4 values: south,west,north,east", file=sys.stderr)
            sys.exit(1)
        south, west, north, east = parts
        name = args.name or "bbox_region"
        path = fetch_bbox(south, west, north, east, name)
    else:
        if not args.city:
            print("Error: provide --city, --bbox, or --area-id", file=sys.stderr)
            sys.exit(1)
        path = fetch_city(args.city)

    print(f"Data saved to: {path}")


def cmd_lookup(args):
    """Handle the 'lookup' subcommand."""
    from neighborhood_lookup.geo import lookup

    dataset = args.dataset
    city_name = None

    if not dataset:
        from neighborhood_lookup.fetch import reverse_geocode, fetch_area

        geo = reverse_geocode(args.lat, args.lon)
        city_name = geo["city_name"]
        slug = geo["slug"]
        geojson_path = DATA_DIR / f"{slug}.geojson"
        if not geojson_path.exists():
            print(
                f"Auto-fetching neighborhood data for {city_name}...",
                file=sys.stderr,
            )
            fetch_area(geo["area_id"], slug)
        dataset = slug

    results = lookup(args.lat, args.lon, dataset=dataset)

    if args.json:
        if not results and city_name:
            print(json.dumps({"city": city_name, "neighborhoods": []}, indent=2))
        else:
            print(json.dumps(results, indent=2))
        return

    if not results:
        if city_name:
            # We know the city from reverse geocoding — give a useful explanation
            geojson_path = DATA_DIR / f"{dataset}.geojson"
            n_features = 0
            if geojson_path.exists():
                with open(geojson_path) as f:
                    n_features = len(json.load(f).get("features", []))
            if n_features == 0:
                print(f"Location is in {city_name}, but OpenStreetMap has no neighborhood boundary data for this city.")
            else:
                print(
                    f"Location is in {city_name} ({n_features} neighborhoods loaded), "
                    f"but this point doesn't fall inside any neighborhood polygon."
                )
                print(
                    "This often means OSM's neighborhood boundaries don't fully cover the city.",
                    file=sys.stderr,
                )
        else:
            print(f"No neighborhood found for ({args.lat}, {args.lon})")
            datasets = list(DATA_DIR.glob("*.geojson"))
            if not datasets:
                print("No datasets downloaded yet. Run 'neighborhood-lookup fetch' first.", file=sys.stderr)
            else:
                print(f"Searched {len(datasets)} dataset(s): {', '.join(d.stem for d in datasets)}", file=sys.stderr)
        sys.exit(1)

    for r in results:
        parts = [r["name"]]
        if r["place"]:
            parts.append(f"({r['place']})")
        if r["admin_level"]:
            parts.append(f"[admin_level={r['admin_level']}]")
        parts.append(f"— dataset: {r['dataset']}")
        if r.get("match_type") == "nearest":
            parts.append(f"[nearest, ~{r.get('distance_m', '?')}m]")
        print("  ".join(parts))


def cmd_list(args):
    """Handle the 'list' subcommand."""
    from neighborhood_lookup.geo import list_neighborhoods

    if args.datasets:
        paths = sorted(DATA_DIR.glob("*.geojson"))
        if not paths:
            print("No datasets found. Run 'neighborhood-lookup fetch' first.")
            return
        for p in paths:
            import json as _json
            with open(p) as f:
                data = _json.load(f)
            count = len(data.get("features", []))
            print(f"  {p.stem}  ({count} neighborhoods)")
        return

    names = list_neighborhoods(dataset=args.dataset)
    if not names:
        print("No neighborhoods found.")
        return
    for name in names:
        print(f"  {name}")


def main():
    parser = argparse.ArgumentParser(
        prog="neighborhood-lookup",
        description="Look up your neighborhood from lat/lon using OpenStreetMap data.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- fetch ---
    p_fetch = subparsers.add_parser(
        "fetch",
        help="Download neighborhood boundary data from OpenStreetMap",
    )
    p_fetch.add_argument(
        "--city",
        help='City name as it appears in OSM (e.g. "San Francisco")',
    )
    p_fetch.add_argument(
        "--bbox",
        help="Bounding box as south,west,north,east (e.g. 37.7,-122.5,37.8,-122.4)",
    )
    p_fetch.add_argument(
        "--area-id",
        type=int,
        help="Overpass area ID to fetch directly (bypasses city name disambiguation)",
    )
    p_fetch.add_argument(
        "--name",
        help="Name for the dataset when using --bbox or --area-id",
    )
    p_fetch.set_defaults(func=cmd_fetch)

    # --- lookup ---
    p_lookup = subparsers.add_parser(
        "lookup",
        help="Find which neighborhood contains a lat/lon point",
    )
    p_lookup.add_argument("lat", type=float, help="Latitude")
    p_lookup.add_argument("lon", type=float, help="Longitude")
    p_lookup.add_argument(
        "--dataset",
        help="Search only this dataset (filename without .geojson)",
    )
    p_lookup.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    p_lookup.set_defaults(func=cmd_lookup)

    # --- list ---
    p_list = subparsers.add_parser(
        "list",
        help="List available datasets or neighborhoods",
    )
    p_list.add_argument(
        "--datasets",
        action="store_true",
        help="List downloaded datasets instead of neighborhoods",
    )
    p_list.add_argument(
        "--dataset",
        help="List neighborhoods from this specific dataset",
    )
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
