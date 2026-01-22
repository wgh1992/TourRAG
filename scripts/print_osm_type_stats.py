#!/usr/bin/env python3
"""
Print osm_type distribution in viewpoint_entity.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db


def main() -> None:
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT osm_type, COUNT(*) AS count
            FROM viewpoint_entity
            GROUP BY osm_type
            ORDER BY count DESC
        """)
        rows = cursor.fetchall()

    total = sum(r["count"] for r in rows)
    print(f"Total: {total}")
    for row in rows:
        osm_type = row["osm_type"]
        count = row["count"]
        ratio = (count / total * 100) if total else 0.0
        print(f"{osm_type}: {count} ({ratio:.2f}%)")


if __name__ == "__main__":
    main()
