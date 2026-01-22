#!/usr/bin/env python3
"""
Update DB geometry bbox from annotation JSON files.

Reads high_res_images/annotations (or exports/high_res_images/annotations),
matches by osm_id, and updates:
  - viewpoint_entity.geom (bbox polygon)
  - viewpoint_commons_assets.viewpoint_boundary
  - viewpoint_commons_assets.viewpoint_area_sqm
"""
import argparse
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Tuple, List

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db


def get_annotations_dir() -> Optional[Path]:
    candidates = [
        Path(__file__).parent.parent / "high_res_images" / "annotations",
        Path(__file__).parent.parent / "exports" / "high_res_images" / "annotations"
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def parse_osm_id(file_path: Path, data: dict) -> Optional[int]:
    osm_id = None
    info = data.get("attraction_info", {})
    if isinstance(info, dict):
        osm_id = info.get("osm_id")
    if osm_id:
        return int(osm_id)
    stem = file_path.stem
    parts = stem.split("_")
    if parts and parts[0].isdigit():
        return int(parts[0])
    return None


def parse_bbox(data: dict) -> Optional[Tuple[float, float, float, float]]:
    geom = data.get("geometry", {})
    bbox_raw = geom.get("bbox_raw", {})
    if isinstance(bbox_raw, dict):
        min_lon = bbox_raw.get("min_lon")
        min_lat = bbox_raw.get("min_lat")
        max_lon = bbox_raw.get("max_lon")
        max_lat = bbox_raw.get("max_lat")
        if None not in (min_lon, min_lat, max_lon, max_lat):
            return float(min_lon), float(min_lat), float(max_lon), float(max_lat)
    return None


def create_bbox_from_point(lon: float, lat: float, buffer_km: float) -> Tuple[float, float, float, float]:
    km_per_deg_lat = 111.0
    km_per_deg_lon = 111.321 * math.cos(math.radians(lat))
    buffer_lat = buffer_km / km_per_deg_lat
    buffer_lon = buffer_km / km_per_deg_lon
    return (
        lon - buffer_lon,
        lat - buffer_lat,
        lon + buffer_lon,
        lat + buffer_lat
    )

def coords_equal(c1: List[float], c2: List[float], tolerance: float = 1e-9) -> bool:
    return abs(c1[0] - c2[0]) < tolerance and abs(c1[1] - c2[1]) < tolerance


def is_closed(coords: List[List[float]], tolerance: float = 1e-9) -> bool:
    if len(coords) < 4:
        return False
    return coords_equal(coords[0], coords[-1], tolerance=tolerance)


def close_ring(coords: List[List[float]]) -> List[List[float]]:
    if not coords:
        return coords
    if not is_closed(coords):
        return coords + [coords[0]]
    return coords


def point_in_polygon(point: List[float], polygon: List[List[float]]) -> bool:
    lon, lat = point
    n = len(polygon)
    inside = False
    if n > 0 and coords_equal(polygon[0], polygon[-1]):
        n -= 1
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def line_from_geometry(geometry: List[dict]) -> List[List[float]]:
    return [[pt["lon"], pt["lat"]] for pt in geometry if "lon" in pt and "lat" in pt]


def polygon_from_way_geometry(geometry: List[dict]) -> Optional[dict]:
    coords = close_ring(line_from_geometry(geometry))
    if len(coords) < 4:
        return None
    return {"type": "Polygon", "coordinates": [coords]}


def calculate_polygon_area_square_meters(coords: List[List[float]]) -> float:
    if len(coords) < 3:
        return 0.0
    if coords[0] != coords[-1]:
        coords = coords + [coords[0]]
    lats = [c[1] for c in coords]
    center_lat = sum(lats) / len(lats)
    meters_per_deg_lat = 111320.0
    meters_per_deg_lon = 111320.0 * math.cos(math.radians(center_lat))
    coords_m = []
    for lon, lat in coords:
        x = lon * meters_per_deg_lon
        y = lat * meters_per_deg_lat
        coords_m.append([x, y])
    area = 0.0
    for i in range(len(coords_m) - 1):
        area += coords_m[i][0] * coords_m[i + 1][1]
        area -= coords_m[i + 1][0] * coords_m[i][1]
    return abs(area) / 2.0


def calculate_feature_area_square_meters(geom: dict) -> float:
    geom_type = geom.get("type")
    if geom_type == "Polygon":
        coords = geom.get("coordinates", [])
        if coords:
            outer_area = calculate_polygon_area_square_meters(coords[0])
            inner_area = sum(calculate_polygon_area_square_meters(hole) for hole in coords[1:])
            return outer_area - inner_area
    if geom_type == "MultiPolygon":
        total_area = 0.0
        for polygon in geom.get("coordinates", []):
            if polygon:
                outer_area = calculate_polygon_area_square_meters(polygon[0])
                inner_area = sum(calculate_polygon_area_square_meters(hole) for hole in polygon[1:])
                total_area += (outer_area - inner_area)
        return total_area
    return 0.0


def assemble_relation_polygons(members: List[dict]) -> Tuple[List[List[List[float]]], dict]:
    outers = []
    inners = []
    for member in members:
        role = member.get("role", "")
        geometry = member.get("geometry") or []
        line = line_from_geometry(geometry)
        if len(line) < 2:
            continue
        if role == "outer":
            outers.append(line)
        elif role == "inner":
            inners.append(line)

    assembled_outers = []
    used = [False] * len(outers)
    for i in range(len(outers)):
        if used[i]:
            continue
        ring = list(outers[i])
        used[i] = True
        progress = True
        while progress and not is_closed(ring):
            progress = False
            for j in range(len(outers)):
                if used[j] or i == j:
                    continue
                a0, a1 = ring[0], ring[-1]
                b = outers[j]
                b0, b1 = b[0], b[-1]
                if coords_equal(a1, b0):
                    ring = ring + b[1:]
                    used[j] = True
                    progress = True
                    break
                if coords_equal(a1, b1):
                    ring = ring + list(reversed(b[:-1]))
                    used[j] = True
                    progress = True
                    break
                if coords_equal(a0, b1):
                    ring = b + ring[1:]
                    used[j] = True
                    progress = True
                    break
                if coords_equal(a0, b0):
                    ring = list(reversed(b)) + ring[1:]
                    used[j] = True
                    progress = True
                    break
        ring = close_ring(ring)
        if len(ring) >= 4:
            assembled_outers.append(ring)

    assembled_inners = []
    used_inner = [False] * len(inners)
    for inner_idx, inner in enumerate(inners):
        if used_inner[inner_idx]:
            continue
        inner_ring = list(inner)
        used_inner[inner_idx] = True
        progress = True
        while progress and not is_closed(inner_ring):
            progress = False
            for j in range(len(inners)):
                if used_inner[j] or inner_idx == j:
                    continue
                a0, a1 = inner_ring[0], inner_ring[-1]
                b = inners[j]
                b0, b1 = b[0], b[-1]
                if coords_equal(a1, b0):
                    inner_ring = inner_ring + b[1:]
                    used_inner[j] = True
                    progress = True
                    break
                if coords_equal(a1, b1):
                    inner_ring = inner_ring + list(reversed(b[:-1]))
                    used_inner[j] = True
                    progress = True
                    break
                if coords_equal(a0, b1):
                    inner_ring = b + inner_ring[1:]
                    used_inner[j] = True
                    progress = True
                    break
                if coords_equal(a0, b0):
                    inner_ring = list(reversed(b)) + inner_ring[1:]
                    used_inner[j] = True
                    progress = True
                    break
        inner_ring = close_ring(inner_ring)
        if len(inner_ring) >= 4:
            assembled_inners.append(inner_ring)

    inner_rings_by_outer = {}
    for inner_ring in assembled_inners:
        test_point = inner_ring[0] if inner_ring else None
        if not test_point:
            continue
        best_outer_idx = None
        for outer_idx, outer_ring in enumerate(assembled_outers):
            if point_in_polygon(test_point, outer_ring):
                inner_rings_by_outer.setdefault(outer_idx, []).append(inner_ring)
                best_outer_idx = outer_idx
                break
        if best_outer_idx is None and assembled_outers:
            inner_rings_by_outer.setdefault(0, []).append(inner_ring)

    return assembled_outers, inner_rings_by_outer


def polygon_from_relation_members(members: List[dict]) -> Optional[dict]:
    outer_rings, inner_rings_by_outer = assemble_relation_polygons(members)
    if not outer_rings:
        return None
    if len(outer_rings) == 1:
        outer_ring = outer_rings[0]
        inner_rings = inner_rings_by_outer.get(0, [])
        coords = [outer_ring] + inner_rings
        return {"type": "Polygon", "coordinates": coords}
    coordinates = []
    for outer_idx, outer_ring in enumerate(outer_rings):
        inner_rings = inner_rings_by_outer.get(outer_idx, [])
        coordinates.append([outer_ring] + inner_rings)
    return {"type": "MultiPolygon", "coordinates": coordinates}


def has_area_tags(tags: dict) -> bool:
    if not tags:
        return False
    for key in ("tourism", "leisure", "historic", "amenity", "building", "landuse", "boundary"):
        if key in tags:
            return True
    return False


def _escape_overpass_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def fetch_polygon_for_node(
    osm_id: int,
    name: Optional[str],
    lat: Optional[float],
    lon: Optional[float],
    wikidata_qid: Optional[str],
    overpass_url: str,
    around_meters: int
) -> Optional[dict]:
    base = "[out:json];"
    queries = [
        f"""
        {base}
        node({osm_id});
        way(bn:{osm_id});
        relation(bn:{osm_id});
        out geom;
        """
    ]

    if lat is not None and lon is not None:
        if wikidata_qid:
            qid = _escape_overpass_value(wikidata_qid)
            queries.append(f"""
            {base}
            (
              way(around:{around_meters},{lat},{lon})["wikidata"="{qid}"];
              relation(around:{around_meters},{lat},{lon})["wikidata"="{qid}"];
            );
            out geom;
            """)
        if name:
            safe_name = _escape_overpass_value(name)
            queries.append(f"""
            {base}
            (
              way(around:{around_meters},{lat},{lon})["name"="{safe_name}"];
              relation(around:{around_meters},{lat},{lon})["name"="{safe_name}"];
              way(around:{around_meters},{lat},{lon})["name:en"="{safe_name}"];
              relation(around:{around_meters},{lat},{lon})["name:en"="{safe_name}"];
            );
            out geom;
            """)

    for query in queries:
        resp = requests.post(overpass_url, data={"data": query}, timeout=180)
        resp.raise_for_status()
        payload = resp.json()
        elements = payload.get("elements", [])
        if not elements:
            continue

        candidates = []
        for el in elements:
            el_type = el.get("type")
            tags = el.get("tags", {})
            if el_type == "way" and el.get("geometry"):
                geom = polygon_from_way_geometry(el["geometry"])
                if geom and has_area_tags(tags):
                    candidates.append(geom)
            elif el_type == "relation" and el.get("members"):
                geom = polygon_from_relation_members(el["members"])
                if geom and has_area_tags(tags):
                    candidates.append(geom)

        if candidates:
            candidates.sort(key=calculate_feature_area_square_meters, reverse=True)
            return candidates[0]

    return None


def fetch_osm_geometry(
    osm_type: str,
    osm_id: int,
    buffer_km: float,
    overpass_url: str,
    name: Optional[str],
    lat: Optional[float],
    lon: Optional[float],
    wikidata_qid: Optional[str],
    around_meters: int
) -> Optional[dict]:
    type_map = {"node": "node", "way": "way", "relation": "relation"}
    elem_type = type_map.get(osm_type)
    if not elem_type:
        return None
    if elem_type == "node":
        return fetch_polygon_for_node(
            osm_id=osm_id,
            name=name,
            lat=lat,
            lon=lon,
            wikidata_qid=wikidata_qid,
            overpass_url=overpass_url,
            around_meters=around_meters
        )

    query = f"""
    [out:json];
    {elem_type}({osm_id});
    out geom;
    """
    resp = requests.post(overpass_url, data={"data": query}, timeout=180)
    resp.raise_for_status()
    payload = resp.json()
    elements = payload.get("elements", [])
    if not elements:
        return None
    element = elements[0]
    if element.get("type") == "way" and element.get("geometry"):
        return polygon_from_way_geometry(element["geometry"])
    if element.get("type") == "relation" and element.get("members"):
        return polygon_from_relation_members(element["members"])
    return None


def fetch_osm_targets(limit: Optional[int], include_nodes: bool) -> List[dict]:
    sql = """
        SELECT
            v.viewpoint_id,
            v.osm_type,
            v.osm_id,
            v.name_primary,
            ST_X(v.geom::geometry) AS lon,
            ST_Y(v.geom::geometry) AS lat,
            wd.wikidata_qid
        FROM viewpoint_entity v
        LEFT JOIN viewpoint_wikidata wd
            ON v.viewpoint_id = wd.viewpoint_id
        WHERE v.osm_id IS NOT NULL
          AND v.geom IS NOT NULL
    """
    if not include_nodes:
        sql += " AND osm_type IN ('way', 'relation')"
    sql += " ORDER BY viewpoint_id"
    if limit:
        sql += " LIMIT %s"
        params = (limit,)
    else:
        params = ()
    with db.get_cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    return rows


def fetch_osm_geometry_with_retries(
    osm_type: str,
    osm_id: int,
    buffer_km: float,
    retries: int,
    delay: float,
    overpass_url: str,
    name: Optional[str],
    lat: Optional[float],
    lon: Optional[float],
    wikidata_qid: Optional[str],
    around_meters: int
) -> Tuple[Optional[dict], Optional[str]]:
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            geom = fetch_osm_geometry(
                osm_type=osm_type,
                osm_id=osm_id,
                buffer_km=buffer_km,
                overpass_url=overpass_url,
                name=name,
                lat=lat,
                lon=lon,
                wikidata_qid=wikidata_qid,
                around_meters=around_meters
            )
            return geom, None
        except Exception as exc:
            last_error = str(exc)
            time.sleep(delay * attempt)
    return None, last_error


def main() -> None:
    parser = argparse.ArgumentParser(description="Update DB bbox geometry from annotations")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of annotations")
    parser.add_argument("--dry-run", action="store_true", help="Print updates without writing DB")
    parser.add_argument("--force", action="store_true", help="Overwrite existing geom/boundary")
    parser.add_argument("--source", choices=["annotations", "osm"], default="annotations", help="BBox source")
    parser.add_argument("--buffer-km", type=float, default=1.0, help="Buffer size for node bbox")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between OSM requests (seconds)")
    parser.add_argument("--workers", type=int, default=4, help="Worker threads for OSM requests")
    parser.add_argument("--retries", type=int, default=3, help="Retries per OSM request")
    parser.add_argument("--around-meters", type=int, default=1500, help="Search radius for node polygon match")
    parser.add_argument(
        "--overpass",
        action="append",
        default=["https://overpass-api.de/api/interpreter"],
        help="Overpass endpoint (can be set multiple times)"
    )
    parser.add_argument("--exclude-nodes", action="store_true", help="Exclude node types")
    args = parser.parse_args()

    updated = 0
    skipped = 0
    missing = 0
    total = 0

    def apply_geometry(osm_id: int, geom: Optional[dict]) -> None:
        if args.dry_run:
            geom_type = geom["type"] if geom else "none"
            print(f"[DRY] osm_id={osm_id} type={geom_type}")
            return
        with db.get_connection() as conn:
            with conn.cursor() as cursor:
                if args.force:
                    if not geom:
                        return
                    cursor.execute("""
                        UPDATE viewpoint_entity
                        SET geom = ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)
                        WHERE osm_id = %s
                    """, (json.dumps(geom), osm_id))
                else:
                    if not geom:
                        return
                    cursor.execute("""
                        UPDATE viewpoint_entity
                        SET geom = ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)
                        WHERE osm_id = %s
                          AND geom IS NULL
                    """, (json.dumps(geom), osm_id))

                if args.force:
                    if not geom:
                        return
                    cursor.execute("""
                        UPDATE viewpoint_commons_assets
                        SET viewpoint_boundary = ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
                            viewpoint_area_sqm = ST_Area(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)::geography)
                        WHERE viewpoint_id = (
                            SELECT viewpoint_id FROM viewpoint_entity WHERE osm_id = %s LIMIT 1
                        )
                    """, (json.dumps(geom), json.dumps(geom), osm_id))
                else:
                    if not geom:
                        return
                    cursor.execute("""
                        UPDATE viewpoint_commons_assets
                        SET viewpoint_boundary = ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
                            viewpoint_area_sqm = ST_Area(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)::geography)
                        WHERE viewpoint_id = (
                            SELECT viewpoint_id FROM viewpoint_entity WHERE osm_id = %s LIMIT 1
                        )
                          AND viewpoint_boundary IS NULL
                    """, (json.dumps(geom), json.dumps(geom), osm_id))

    if args.source == "annotations":
        annotations_dir = get_annotations_dir()
        if not annotations_dir:
            print("❌ annotations directory not found")
            return
        files = sorted(annotations_dir.glob("*.json"))
        if args.limit:
            files = files[:args.limit]
        total = len(files)
        for path in files:
            print(f"[{updated + skipped + missing + 1}/{total}] {path.name}")
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                print("  ✗ invalid json")
                skipped += 1
                continue
            osm_id = parse_osm_id(path, data)
            bbox = parse_bbox(data)
            if not osm_id or not bbox:
                print("  ⚠ missing osm_id or bbox")
                missing += 1
                continue
            apply_geometry(osm_id, None)
            print(f"  ✓ updated osm_id={osm_id} polygon=none")
            updated += 1
    else:
        targets = fetch_osm_targets(args.limit, include_nodes=not args.exclude_nodes)
        total = len(targets)
        endpoints = list(dict.fromkeys(args.overpass or [])) or ["https://overpass-api.de/api/interpreter"]

        def worker(row: dict) -> Tuple[int, Optional[dict], Optional[str]]:
            osm_id = row.get("osm_id")
            osm_type = row.get("osm_type")
            name_primary = row.get("name_primary")
            lon = row.get("lon")
            lat = row.get("lat")
            wikidata_qid = row.get("wikidata_qid")
            if not osm_id or not osm_type:
                return -1, None, "missing osm_id/osm_type"
            endpoint = endpoints[int(osm_id) % len(endpoints)]
            geom, error = fetch_osm_geometry_with_retries(
                osm_type=str(osm_type),
                osm_id=int(osm_id),
                buffer_km=args.buffer_km,
                retries=args.retries,
                delay=args.delay,
                overpass_url=endpoint,
                name=name_primary,
                lat=lat,
                lon=lon,
                wikidata_qid=wikidata_qid,
                around_meters=args.around_meters
            )
            return int(osm_id), geom, error

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            futures = {executor.submit(worker, row): row for row in targets}
            for idx, future in enumerate(as_completed(futures), start=1):
                row = futures[future]
                osm_id = row.get("osm_id")
                osm_type = row.get("osm_type")
                print(f"[{idx}/{total}] osm={osm_type}/{osm_id}")
                try:
                    resolved_osm_id, geom, error = future.result()
                except Exception as exc:
                    print(f"  ✗ request failed: {exc}")
                    skipped += 1
                    continue

                if error == "missing osm_id/osm_type":
                    print("  ⚠ missing osm_id/osm_type")
                    missing += 1
                    continue
                if error:
                    print(f"  ✗ request failed: {error}")
                    skipped += 1
                    continue
                if not geom:
                    print("  ⚠ polygon not found (likely node or missing geometry)")
                    missing += 1
                    continue
                apply_geometry(int(resolved_osm_id), geom)
                print(f"  ✓ updated geometry={geom.get('type')}")
                updated += 1

    print(f"Done. updated={updated}, skipped={skipped}, missing={missing}")


if __name__ == "__main__":
    main()
