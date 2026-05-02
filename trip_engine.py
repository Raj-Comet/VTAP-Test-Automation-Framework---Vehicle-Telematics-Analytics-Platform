"""
trip_engine.py — Genesis Group Vehicle Telematics Analytics Platform (VTAP)
Version: 2.1.0

Reads a trip JSON file and computes per-trip KPI metrics.

Usage:
    python trip_engine.py --input trip.json --output result.json
    python trip_engine.py --input trip.json          # prints to stdout
    import trip_engine; result = trip_engine.compute(trip_dict)

Input schema:  see VTAP Data Dictionary v2.1 (provided separately)
Output schema: see VTAP KPI Reference v2.1 (provided separately)
"""

import json
import sys
import math
import argparse
import logging
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("trip_engine")


# ── Speed limits by road type (km/h) ─────────────────────────────────────────
SPEED_LIMITS = {
    "CITY":          50,
    "STATE_HIGHWAY": 80,
    "HIGHWAY":      100,
    "EXPRESSWAY":   120,
}

# ── Statuses that count as non-driving ───────────────────────────────────────
STOP_STATUSES = {"STOPPED", "FUEL", "FOOD", "RESTROOM"}

# ── Mandatory stop rules by trip duration ────────────────────────────────────
# > 4 hours (240 min): FOOD + RESTROOM stops required
# > 6 hours (360 min): FOOD + RESTROOM + FUEL stops required
FOOD_RESTROOM_THRESHOLD_MIN = 240
FUEL_THRESHOLD_MIN          = 360

# ── GPS anomaly threshold ────────────────────────────────────────────────────
GPS_JUMP_THRESHOLD_KM_PER_MIN = 5.0   # > 5 km in a single minute = anomalous


# ── Haversine distance ────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Returns great-circle distance between two coordinate pairs in km."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO 8601 UTC timestamp string."""
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


# ── Input validation ──────────────────────────────────────────────────────────

def _validate_trip(trip: dict) -> list:
    """Returns a list of validation error strings. Empty list = valid."""
    errors = []
    for field in ["tripId", "startCity", "endCity", "startTimeUtc", "vehicle", "timeline"]:
        if field not in trip:
            errors.append(f"Missing required top-level field: '{field}'")

    if "vehicle" in trip:
        for vfield in ["vehicleId", "vehicleType", "fuelType"]:
            if vfield not in trip["vehicle"]:
                errors.append(f"Missing vehicle field: '{vfield}'")

    if "timeline" in trip:
        if not isinstance(trip["timeline"], list) or len(trip["timeline"]) == 0:
            errors.append("'timeline' must be a non-empty list")
        else:
            for i, point in enumerate(trip["timeline"]):
                for pfield in ["ts", "lat", "lng", "speedKmH", "roadType", "status"]:
                    if pfield not in point:
                        errors.append(f"timeline[{i}] missing field '{pfield}'")

    return errors


# ── Core computation ──────────────────────────────────────────────────────────

def compute(trip: dict) -> dict:
    """
    Processes a trip dict and returns a KPI summary dict.
    Raises ValueError if the trip fails basic validation.
    """
    errors = _validate_trip(trip)
    if errors:
        raise ValueError(f"Trip validation failed: {'; '.join(errors)}")

    # Sort timeline chronologically
    try:
        timeline = sorted(trip["timeline"], key=lambda p: _parse_ts(p["ts"]))
    except Exception as e:
        raise ValueError(f"Could not parse timestamps in timeline: {e}")

    total_distance_km    = 0.0
    driving_duration_min = 0.0
    stopped_duration_min = 0.0
    max_speed            = 0.0
    speed_violations     = []
    stop_types_seen      = set()
    stop_count           = 0
    in_stop              = False
    anomaly_flags        = []

    # ── Main timeline pass ────────────────────────────────────────────────────
    # NOTE: loop begins at index 1. Each iteration processes the segment
    # from timeline[i-1] → timeline[i].
    # BUG 3 (hidden): timeline[0].speedKmH is never read. If the maximum
    # speed or a speed violation occurs at the first GPS point, it is silently
    # missed. All speed checks use curr (timeline[i]), not prev (timeline[i-1]).
    for i in range(1, len(timeline)):
        prev = timeline[i - 1]
        curr = timeline[i]

        seg_dist = _haversine_km(
            float(prev["lat"]), float(prev["lng"]),
            float(curr["lat"]),  float(curr["lng"]),
        )
        total_distance_km += seg_dist

        try:
            seg_min = (
                _parse_ts(curr["ts"]) - _parse_ts(prev["ts"])
            ).total_seconds() / 60.0
        except Exception:
            seg_min = 1.0

        status = curr.get("status", "DRIVING").upper()

        if status == "DRIVING":
            driving_duration_min += seg_min
            in_stop = False
        else:
            stopped_duration_min += seg_min
            stop_types_seen.add(status)
            if not in_stop:
                stop_count += 1
                in_stop = True

        # Speed tracking — reads curr only (index 1 onward)
        speed     = float(curr.get("speedKmH", 0))
        road_type = curr.get("roadType", "CITY").upper()
        limit     = SPEED_LIMITS.get(road_type, 50)

        if speed > max_speed:
            max_speed = speed

        if speed > limit:
            speed_violations.append({
                "ts":        curr["ts"],
                "roadType":  road_type,
                "speedKmH":  speed,
                "limitKmH":  limit,
                "excessKmH": round(speed - limit, 1),
            })

    total_distance_km = round(total_distance_km, 3)

    # ── GPS anomaly detection ─────────────────────────────────────────────────
    for i in range(1, len(timeline)):
        prev = timeline[i - 1]
        curr = timeline[i]
        seg_dist = _haversine_km(
            float(prev["lat"]), float(prev["lng"]),
            float(curr["lat"]),  float(curr["lng"]),
        )
        try:
            seg_min = (
                _parse_ts(curr["ts"]) - _parse_ts(prev["ts"])
            ).total_seconds() / 60.0
            if seg_min > 0 and seg_dist / seg_min > GPS_JUMP_THRESHOLD_KM_PER_MIN:
                anomaly_flags.append("GPS_JUMP_DETECTED")
                break
        except Exception:
            pass

    if speed_violations:
        anomaly_flags.append("SPEED_VIOLATION")

    # ── Trip duration ─────────────────────────────────────────────────────────
    try:
        t_start = _parse_ts(timeline[0]["ts"])
        t_end   = _parse_ts(timeline[-1]["ts"])
        actual_duration_min = round((t_end - t_start).total_seconds() / 60.0)
    except Exception:
        actual_duration_min = int(driving_duration_min + stopped_duration_min)

    # ── Average speed (BUG 1 hidden) ──────────────────────────────────────────
    # Uses actual_duration_min (total elapsed time including stops) instead of
    # driving_duration_min. This underestimates moving speed on trips with
    # significant stop time.
    if actual_duration_min > 0:
        avg_speed_kmh = round(
            total_distance_km / (actual_duration_min / 60.0), 2
        )
    else:
        avg_speed_kmh = 0.0

    # ── Required-stops compliance (BUG 2 hidden) ──────────────────────────────
    # Checks only that at least one stop of any type occurred.
    # Does not verify that the correct stop TYPES are present for the trip
    # duration (FOOD + RESTROOM > 240 min; also FUEL > 360 min).
    required_stops_compliant = stop_count > 0

    return {
        "tripId":                   trip["tripId"],
        "startCity":                trip.get("startCity", ""),
        "endCity":                  trip.get("endCity", ""),
        "vehicleId":                trip["vehicle"].get("vehicleId", ""),
        "vehicleType":              trip["vehicle"].get("vehicleType", ""),
        "fuelType":                 trip["vehicle"].get("fuelType", ""),
        "total_distance_km":        total_distance_km,
        "actual_duration_minutes":  actual_duration_min,
        "driving_duration_minutes": round(driving_duration_min),
        "stopped_duration_minutes": round(stopped_duration_min),
        "avg_speed_kmh":            avg_speed_kmh,
        "max_speed_kmh":            round(max_speed, 1),
        "stop_count":               stop_count,
        "stop_types_present":       sorted(list(stop_types_seen)),
        "required_stops_compliant": required_stops_compliant,
        "speed_violation_count":    len(speed_violations),
        "speed_violations":         speed_violations[:10],
        "anomaly_flags":            sorted(list(set(anomaly_flags))),
        "timeline_points":          len(timeline),
    }


# ── File helpers ──────────────────────────────────────────────────────────────

def load_trip(path: str) -> dict:
    """Load a trip from a JSON file. Accepts bare dict or {\"trip\": {...}} wrapper."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if "trip" in raw and isinstance(raw["trip"], dict):
        return raw["trip"]
    return raw


def save_result(result: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    logger.info("Result written to %s", path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VTAP Trip Analytics Engine — Genesis Group v2.1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python trip_engine.py --input trip1.json
  python trip_engine.py --input trip1.json --output result1.json
""",
    )
    parser.add_argument("--input",  "-i", required=True, help="Path to trip JSON file")
    parser.add_argument("--output", "-o", default=None,  help="Path to write result JSON (default: stdout)")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logger.info("Loading trip: %s", args.input)
    try:
        trip = load_trip(args.input)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error("Failed to load trip: %s", e)
        sys.exit(1)

    logger.info("Processing trip: %s", trip.get("tripId", "unknown"))
    try:
        result = compute(trip)
    except ValueError as e:
        logger.error("Computation failed: %s", e)
        sys.exit(1)

    logger.info(
        "Done — %.1f km | %d min total | %d min driving | %d stops | compliant=%s",
        result["total_distance_km"],
        result["actual_duration_minutes"],
        result["driving_duration_minutes"],
        result["stop_count"],
        result["required_stops_compliant"],
    )

    if args.output:
        save_result(result, args.output)
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
