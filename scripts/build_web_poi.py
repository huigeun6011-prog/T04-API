"""Build the browser-facing POI JSON from the collected, deduplicated CSV.

Run from any working directory with:
    python scripts/build_web_poi.py

The raw files remain untouched. Rows without coordinates are retained so that
route-only trail metadata can still be shown outside the map.
"""

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POI_CSV = ROOT / "data" / "raw" / "poi" / "poi_all.csv"
TRAIL_CSV = ROOT / "data" / "raw" / "poi" / "trail" / "processed" / "trail.csv"
OUTPUT = ROOT / "web" / "data" / "pois.json"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def coordinate(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None


def load_trail_details() -> dict[str, dict[str, str]]:
    if not TRAIL_CSV.exists():
        return {}
    details = {}
    for row in read_rows(TRAIL_CSV):
        name = (row.get("name") or "").strip()
        if name:
            details[name.casefold()] = {
                field: (row.get(field) or "").strip()
                for field in ("section", "course", "distance", "time")
            }
    return details


def build() -> list[dict]:
    source_rows = read_rows(POI_CSV)
    trail_details = load_trail_details()
    per_type_index: dict[str, int] = {}
    result = []

    for row in source_rows:
        kind = (row.get("facility_type") or "").strip()
        if not kind:
            continue

        name = (row.get("name") or "").strip()
        lat = coordinate(row.get("latitude"))
        lng = coordinate(row.get("longitude"))
        has_coordinates = lat is not None and lng is not None
        # Do not expose a half-coordinate pair to map code.
        if not has_coordinates:
            lat = None
            lng = None

        per_type_index[kind] = per_type_index.get(kind, 0) + 1
        item = {
            "id": f"{kind}-{per_type_index[kind]:04d}",
            "facility_type": kind,
            "name": name,
            "address": (row.get("address") or "").strip(),
            "latitude": lat,
            "longitude": lng,
            "source": (row.get("source") or kind).strip(),
            "has_coordinates": has_coordinates,
        }

        if kind == "trail":
            item.update(trail_details.get(name.casefold(), {
                "section": "",
                "course": "",
                "distance": "",
                "time": "",
            }))

        result.append(item)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


if __name__ == "__main__":
    items = build()
    counts: dict[str, dict[str, int]] = {}
    for item in items:
        bucket = counts.setdefault(
            item["facility_type"], {"rows": 0, "mapped": 0, "without_coordinates": 0}
        )
        bucket["rows"] += 1
        bucket["mapped" if item["has_coordinates"] else "without_coordinates"] += 1

    print(json.dumps({"output": str(OUTPUT), "total": len(items), "by_type": counts}, ensure_ascii=False))
