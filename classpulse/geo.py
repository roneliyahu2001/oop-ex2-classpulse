"""Optional location check for attendance (a circle around the classroom).

Phone GPS is weak indoors, so the check answers "is the student around the
building?" and not "is the student in the room?". The phone reports how
inaccurate its fix is, and we give it the benefit of the doubt up to a cap.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_000
MAX_ACCURACY_CREDIT_M = 100


def valid_coordinates(lat: float, lon: float) -> bool:
    return (math.isfinite(lat) and math.isfinite(lon)
            and -90 <= lat <= 90 and -180 <= lon <= 180)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class GeoFence:
    lat: float
    lon: float
    radius_m: int

    def distance_to(self, lat: float, lon: float) -> float:
        return haversine_m(self.lat, self.lon, lat, lon)

    def contains(self, lat: float, lon: float, accuracy_m: float = 0) -> bool:
        credit = min(max(accuracy_m, 0), MAX_ACCURACY_CREDIT_M)
        return self.distance_to(lat, lon) - credit <= self.radius_m
