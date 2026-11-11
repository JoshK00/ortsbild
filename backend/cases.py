"""Duplicates become one case. The same defect reported again counts as one more vote on the case.

Two reports belong to the same case when they have the same category, lie at most `DUPLICATE_RADIUS_M` meters apart and the
newer one came in within `CASE_OPEN_DAYS` days of the oldest one (the anchor). The oldest report is the anchor of the case.
Nothing is stored: the cases are worked out from the reports each time, so there is no new table and no migration.

TODO: A real `cases` table (with PostGIS) when the number of reports makes this too slow, or when an authority has to
      close a case. Until then one pass over at most `MAX_REPORTS` reports is enough.
"""

import hashlib
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt

from privacy.report_status import ReportRecord

DUPLICATE_RADIUS_M = 40  # a phone is off by 5 to 20 m, within 40 m it is the same defect, 100 m further it is another one
CASE_OPEN_DAYS = 30

Entry = tuple[ReportRecord, datetime]
EARTH_RADIUS_M = 6_371_000


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """The distance between two points on the earth in meters (haversine)."""
    d_lat, d_lon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))


def case_id_of(report_id: str) -> str:
    """The id the dashboard knows for a report (the anchor of a case). It is a hash, so the real report id (the key of the
    endpoints with login) does not leave the server."""
    return hashlib.sha256(report_id.encode()).hexdigest()[:16]


def _category(record: ReportRecord) -> str | None:
    return (record.classification or {}).get("category")


def _position(record: ReportRecord) -> tuple[float, float] | None:
    location = (record.sanitized or {}).get("location") or {}
    lat, lon = location.get("lat"), location.get("lon")
    return (lat, lon) if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) else None


def group_into_cases(
    entries: list[Entry], radius_m: float = DUPLICATE_RADIUS_M, open_days: int = CASE_OPEN_DAYS
) -> list[list[Entry]]:
    """Group reports into cases. Every case is a list of reports, the oldest first, the newest case first in the result.

    A report without a category or without a position cannot be a duplicate, it is a case of its own.
    """
    cases: list[list[Entry]] = []
    for entry in sorted(entries, key=lambda item: item[1]):
        record, created_at = entry
        category, position = _category(record), _position(record)
        best, best_distance = None, None
        if category is not None and position is not None:
            for case in cases:
                anchor_record, anchor_time = case[0]
                anchor_position = _position(anchor_record)
                if _category(anchor_record) != category or anchor_position is None:
                    continue
                if created_at - anchor_time > timedelta(days=open_days):
                    continue
                distance = distance_m(*position, *anchor_position)
                if distance <= radius_m and (best_distance is None or distance < best_distance):
                    best, best_distance = case, distance
        if best is not None:
            best.append(entry)
        else:
            cases.append([entry])
    return sorted(cases, key=lambda case: case[-1][1], reverse=True)


def votes_of(case: list[Entry]) -> int:
    """How many votes a case has: every report counts once.

    TODO: If one user pushes a case, count one vote per user and day (needs the user key of every report).
    """
    return len(case)


def case_for(entries: list[Entry], record: ReportRecord, radius_m: float = DUPLICATE_RADIUS_M, open_days: int = CASE_OPEN_DAYS) -> list[Entry]:
    """The case that one report belongs to, with all its reports."""
    for case in group_into_cases(entries, radius_m, open_days):
        if any(member.report_id == record.report_id for member, _ in case):
            return case
    return []
