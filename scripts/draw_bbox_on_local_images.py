#!/usr/bin/env python3
"""
Draw viewpoint boundary bbox on local images.

Input:
  - exports/images/all_image (viewpoint_id.png/jpg/...)
Database:
  - viewpoint_commons_assets.viewpoint_boundary (preferred)
  - viewpoint_entity.geom (fallback)
Output:
  - exports/images/all_image_bbox
"""
import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def parse_viewpoint_id(filename: str) -> Optional[int]:
    try:
        return int(Path(filename).stem)
    except Exception:
        return None


def fetch_geometry(viewpoint_id: int) -> Optional[dict]:
    sql = """
        SELECT
            ST_AsGeoJSON(COALESCE(vca.viewpoint_boundary, v.geom)) AS geom_json
        FROM viewpoint_entity v
        LEFT JOIN LATERAL (
            SELECT viewpoint_boundary
            FROM viewpoint_commons_assets
            WHERE viewpoint_id = v.viewpoint_id
              AND viewpoint_boundary IS NOT NULL
            ORDER BY downloaded_at DESC NULLS LAST
            LIMIT 1
        ) vca ON true
        WHERE v.viewpoint_id = %s
    """
    with db.get_cursor() as cursor:
        cursor.execute(sql, (viewpoint_id,))
        row = cursor.fetchone()
    if not row or not row.get("geom_json"):
        return None
    try:
        return json.loads(row["geom_json"])
    except Exception:
        return None


def flatten_polygon_coords(geom: dict) -> List[List[float]]:
    if not geom:
        return []
    geom_type = geom.get("type")
    coords = geom.get("coordinates")
    if not coords:
        return []
    if geom_type == "Polygon":
        return coords[0]
    if geom_type == "MultiPolygon":
        return coords[0][0]
    return []


def bbox_from_coords(coords: List[List[float]]) -> Optional[Tuple[float, float, float, float]]:
    if not coords:
        return None
    lons = [c[0] for c in coords if isinstance(c, list) and len(c) >= 2]
    lats = [c[1] for c in coords if isinstance(c, list) and len(c) >= 2]
    if not lons or not lats:
        return None
    return min(lons), min(lats), max(lons), max(lats)


def lonlat_to_pixel(
    lon: float,
    lat: float,
    bbox: Tuple[float, float, float, float],
    size: Tuple[int, int]
) -> Tuple[int, int]:
    min_lon, min_lat, max_lon, max_lat = bbox
    width, height = size
    x_ratio = 0.0 if max_lon == min_lon else (lon - min_lon) / (max_lon - min_lon)
    y_ratio = 0.0 if max_lat == min_lat else (lat - min_lat) / (max_lat - min_lat)
    x = int(max(0, min(width - 1, x_ratio * width)))
    y = int(max(0, min(height - 1, (1 - y_ratio) * height)))
    return x, y


def draw_bbox_on_image(
    image: Image.Image,
    bbox: Tuple[float, float, float, float],
    image_bbox: Optional[Tuple[float, float, float, float]] = None,
    coords: Optional[List[List[float]]] = None,
    draw_polygon: bool = True,
    bbox_color: Tuple[int, int, int] = (255, 90, 0),
    polygon_color: Tuple[int, int, int] = (255, 165, 0),
    line_width: int = 3
) -> Image.Image:
    if image.mode != "RGB":
        image = image.convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    base_bbox = image_bbox or bbox

    # Draw target bbox relative to the image bbox
    min_lon, min_lat, max_lon, max_lat = bbox
    left, top = lonlat_to_pixel(min_lon, max_lat, base_bbox, (width, height))
    right, bottom = lonlat_to_pixel(max_lon, min_lat, base_bbox, (width, height))
    draw.rectangle([(left, top), (right, bottom)], outline=bbox_color, width=line_width)

    if draw_polygon and coords:
        pixel_coords = [
            lonlat_to_pixel(lon, lat, base_bbox, (width, height))
            for lon, lat in coords
        ]
        if len(pixel_coords) >= 3:
            draw.line(pixel_coords + [pixel_coords[0]], fill=polygon_color, width=line_width)

    return image


def main() -> None:
    parser = argparse.ArgumentParser(description="Draw DB bbox on local images")
    parser.add_argument(
        "--image-dir",
        default="exports/images/all_image",
        help="Input image directory"
    )
    parser.add_argument(
        "--output-dir",
        default="exports/images/all_image_bbox",
        help="Output image directory"
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit number of images")
    parser.add_argument("--skip-existing", action="store_true", help="Skip if output exists")
    parser.add_argument("--no-polygon", action="store_true", help="Do not draw polygon outline")
    parser.add_argument(
        "--fixed-bbox",
        type=float,
        nargs=4,
        default=None,
        metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
        help="Use a fixed bbox instead of DB geometry"
    )
    parser.add_argument(
        "--image-bbox",
        type=float,
        nargs=4,
        default=None,
        metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
        help="Use this bbox as the image extent for mapping"
    )
    args = parser.parse_args()

    image_dir = Path(args.image_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    images = [
        p for p in sorted(image_dir.iterdir())
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    ]
    if args.limit:
        images = images[:args.limit]

    processed = 0
    skipped = 0
    missing = 0

    for image_path in images:
        output_path = output_dir / image_path.name
        if args.skip_existing and output_path.exists():
            skipped += 1
            continue

        if args.fixed_bbox:
            bbox = tuple(args.fixed_bbox)
            image_bbox = tuple(args.image_bbox) if args.image_bbox else bbox
            coords = None
        else:
            viewpoint_id = parse_viewpoint_id(image_path.name)
            if viewpoint_id is None:
                skipped += 1
                continue
            geom = fetch_geometry(viewpoint_id)
            coords = flatten_polygon_coords(geom)
            bbox = bbox_from_coords(coords)
            if not bbox:
                missing += 1
                continue
            image_bbox = bbox

        image = Image.open(image_path)
        drawn = draw_bbox_on_image(
            image=image,
            bbox=bbox,
            image_bbox=image_bbox,
            coords=coords,
            draw_polygon=not args.no_polygon
        )
        drawn.save(output_path, "PNG")
        processed += 1

    print(f"Done. processed={processed}, skipped={skipped}, missing_bbox={missing}")


if __name__ == "__main__":
    main()
