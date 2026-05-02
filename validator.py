"""validator.py - Validate VTAP trip data before execution

Checks generated trip JSON objects for schema, semantic, and logical errors.
Provides detailed error messages for debugging.
"""

import json
import os
import math
from typing import List, Dict, Any, Tuple
from datetime import datetime, timedelta
import trip_engine


# Validation constants
VALID_VEHICLE_TYPES = {"TRUCK", "BUS", "CAR", "BIKE"}
VALID_FUEL_TYPES = {"DIESEL", "PETROL", "CNG", "ELECTRIC"}
VALID_ROAD_TYPES = {"CITY", "STATE_HIGHWAY", "HIGHWAY", "EXPRESSWAY"}
VALID_STATUSES = {"DRIVING", "STOPPED", "FUEL", "FOOD", "RESTROOM"}

SPEED_LIMITS = {
    "CITY": 50,
    "STATE_HIGHWAY": 80,
    "HIGHWAY": 100,
    "EXPRESSWAY": 120,
}

FOOD_RESTROOM_THRESHOLD_MIN = 240
FUEL_THRESHOLD_MIN = 360
GPS_JUMP_THRESHOLD_KM_PER_MIN = 5.0


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate haversine distance between two points in km."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO 8601 UTC timestamp."""
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


# Trip validation logic
class TripValidator:
    """Validates a single trip and collects errors/warnings."""
    
    def __init__(self, trip: dict, trip_id: str):
        self.trip = trip
        self.trip_id = trip_id
        self.errors = []
        self.warnings = []
    
    def validate(self) -> Tuple[bool, List[str], List[str]]:
        """Run validation. Returns (is_valid, errors, warnings)."""
        self._validate_schema()
        self._validate_coordinates()
        self._validate_timestamps()
        self._validate_speed_values()
        self._validate_semantic()
        return len(self.errors) == 0, self.errors, self.warnings
    
    def _validate_schema(self) -> None:
        """Check required fields and field types."""
        required_top = ["tripId", "startCity", "endCity", "startTimeUtc", "vehicle", "timeline"]
        for field in required_top:
            if field not in self.trip:
                self.errors.append(f"[SCHEMA] Missing required field: '{field}'")
        
        if "vehicle" in self.trip:
            vehicle = self.trip["vehicle"]
            for vfield in ["vehicleId", "vehicleType", "fuelType"]:
                if vfield not in vehicle:
                    self.errors.append(f"[SCHEMA] vehicle.{vfield} is missing")
            
            if "vehicleType" in vehicle and vehicle["vehicleType"] not in VALID_VEHICLE_TYPES:
                self.errors.append(f"[SCHEMA] vehicleType='{vehicle['vehicleType']}' not in {VALID_VEHICLE_TYPES}")
            
            if "fuelType" in vehicle and vehicle["fuelType"] not in VALID_FUEL_TYPES:
                self.errors.append(f"[SCHEMA] fuelType='{vehicle['fuelType']}' not in {VALID_FUEL_TYPES}")
        
        if "timeline" in self.trip:
            timeline = self.trip["timeline"]
            if not isinstance(timeline, list):
                self.errors.append(f"[SCHEMA] timeline is {type(timeline)}, expected list")
                return
            
            if len(timeline) == 0:
                self.errors.append(f"[SCHEMA] timeline is empty (must have >= 1 point)")
                return
            
            for i, point in enumerate(timeline):
                required_point = ["ts", "lat", "lng", "speedKmH", "roadType", "status"]
                for pfield in required_point:
                    if pfield not in point:
                        self.errors.append(f"[SCHEMA] timeline[{i}].{pfield} is missing")
                
                if "roadType" in point and point["roadType"] not in VALID_ROAD_TYPES:
                    self.errors.append(f"[SCHEMA] timeline[{i}].roadType='{point['roadType']}' not in {VALID_ROAD_TYPES}")
                
                if "status" in point and point["status"] not in VALID_STATUSES:
                    self.errors.append(f"[SCHEMA] timeline[{i}].status='{point['status']}' not in {VALID_STATUSES}")
    
    def _validate_coordinates(self) -> None:
        """Check latitude/longitude ranges and realism."""
        if "timeline" not in self.trip:
            return
        
        timeline = self.trip["timeline"]
        for i, point in enumerate(timeline):
            lat = point.get("lat")
            lng = point.get("lng")
            
            if lat is None or lng is None:
                continue
            
            try:
                lat_f = float(lat)
                lng_f = float(lng)
            except (TypeError, ValueError):
                self.errors.append(f"[COORD] timeline[{i}].(lat,lng)=({lat},{lng}) not numeric")
                continue
            
            if not (-90 <= lat_f <= 90):
                self.errors.append(f"[COORD] timeline[{i}].lat={lat_f} outside [-90, 90]")
            
            if not (-180 <= lng_f <= 180):
                self.errors.append(f"[COORD] timeline[{i}].lng={lng_f} outside [-180, 180]")
            
            # India bounds (rough): 8°N to 35°N, 68°E to 97°E
            if not (8 <= lat_f <= 35 and 68 <= lng_f <= 97):
                self.warnings.append(f"[COORD] timeline[{i}].(lat,lng)=({lat_f},{lng_f}) outside typical India bounds [8°N-35°N, 68°E-97°E]")
    
    def _validate_timestamps(self) -> None:
        """Check timestamp validity and ordering."""
        if "timeline" not in self.trip:
            return
        
        timeline = self.trip["timeline"]
        prev_ts = None
        seen_ts = set()
        
        for i, point in enumerate(timeline):
            ts_str = point.get("ts")
            if ts_str is None:
                continue
            
            try:
                ts = _parse_ts(ts_str)
            except (ValueError, TypeError) as e:
                self.errors.append(f"[TIME] timeline[{i}].ts='{ts_str}' cannot be parsed: {e}")
                continue
            
            # Check for duplicates
            if ts_str in seen_ts:
                self.errors.append(f"[TIME] timeline[{i}].ts='{ts_str}' is a duplicate (seen before)")
            seen_ts.add(ts_str)
            
            # Check monotonic increase
            if prev_ts is not None and ts <= prev_ts:
                self.errors.append(f"[TIME] timeline[{i}].ts={ts_str} not after previous timestamp {prev_ts}")
            
            prev_ts = ts
        
        # Check time gaps
        if len(timeline) > 1:
            try:
                first_ts = _parse_ts(timeline[0]["ts"])
                for i in range(1, len(timeline)):
                    prev_ts = _parse_ts(timeline[i - 1]["ts"])
                    curr_ts = _parse_ts(timeline[i]["ts"])
                    gap_min = (curr_ts - prev_ts).total_seconds() / 60.0
                    
                    if gap_min > 60:
                        # Large gap without explanation (acceptable with explanation)
                        status = timeline[i].get("status", "DRIVING").upper()
                        if status == "DRIVING" or status == "STOPPED":
                            self.warnings.append(f"[TIME] timeline[{i}]: {gap_min:.1f} min gap with status={status}")
            except Exception:
                pass
    
    def _validate_speed_values(self) -> None:
        """Check speed is non-negative and reasonable."""
        if "timeline" not in self.trip:
            return
        
        timeline = self.trip["timeline"]
        for i, point in enumerate(timeline):
            speed = point.get("speedKmH")
            if speed is None:
                continue
            
            try:
                speed_f = float(speed)
            except (TypeError, ValueError):
                self.errors.append(f"[SPEED] timeline[{i}].speedKmH='{speed}' not numeric")
                continue
            
            if speed_f < 0:
                self.errors.append(f"[SPEED] timeline[{i}].speedKmH={speed_f} is negative (invalid)")
            
            if speed_f > 200:
                self.warnings.append(f"[SPEED] timeline[{i}].speedKmH={speed_f} unusually high (>200 km/h)")
    
    def _validate_semantic(self) -> None:
        """Check logical consistency."""
        if "timeline" not in self.trip:
            return
        
        timeline = self.trip["timeline"]
        
        # Check DRIVING with zero speed for extended periods
        consecutive_zero_driving = 0
        for i, point in enumerate(timeline):
            status = point.get("status", "DRIVING").upper()
            speed = point.get("speedKmH", 0)
            
            if status == "DRIVING" and float(speed) == 0:
                consecutive_zero_driving += 1
                if consecutive_zero_driving > 10:
                    self.errors.append(f"[SEMANTIC] timeline[{i}]: DRIVING status with 0 speed for {consecutive_zero_driving} consecutive points (implies stationary while marked driving)")
            else:
                consecutive_zero_driving = 0
        
        # Check implausible speed jumps (GPS anomaly detector)
        for i in range(1, len(timeline)):
            try:
                prev = timeline[i - 1]
                curr = timeline[i]
                
                lat1, lng1 = float(prev["lat"]), float(prev["lng"])
                lat2, lng2 = float(curr["lat"]), float(curr["lng"])
                dist_km = _haversine_km(lat1, lng1, lat2, lng2)
                
                ts1 = _parse_ts(prev["ts"])
                ts2 = _parse_ts(curr["ts"])
                time_min = (ts2 - ts1).total_seconds() / 60.0
                
                if time_min > 0:
                    implied_speed_km_per_min = dist_km / time_min
                    if implied_speed_km_per_min > 20:
                        self.warnings.append(f"[GPS] timeline[{i}]: Implied speed {implied_speed_km_per_min:.1f} km/min ({implied_speed_km_per_min*60:.0f} km/h) — GPS glitch or unrealistic jump")
            except (ValueError, TypeError, KeyError):
                pass
        
        # Check stop/driving consistency
        for i, point in enumerate(timeline):
            status = point.get("status", "DRIVING").upper()
            speed = point.get("speedKmH", 0)
            
            if status in {"STOPPED", "FUEL", "FOOD", "RESTROOM"}:
                if float(speed) > 5:
                    self.warnings.append(f"[SEMANTIC] timeline[{i}]: status={status} but speedKmH={speed} (expected ~0)")


# ─────────────────────────────────────────────────────────────────────────────
# DATASET LEVEL VALIDATORS
# ─────────────────────────────────────────────────────────────────────────────

class DatasetValidator:
    """Validates entire dataset for scenario coverage and redundancy."""
    
    def __init__(self, scenario: int, trips: List[Dict]):
        self.scenario = scenario
        self.trips = trips
        self.findings = []
    
    def validate(self) -> List[str]:
        """Run dataset-level validation checks."""
        self._check_representativeness()
        self._check_boundary_presence()
        self._check_redundancy()
        self._check_coverage()
        return self.findings
    
    def _check_representativeness(self) -> None:
        """Verify scenarios exercise their intended rules."""
        if self.scenario == 1:
            # Should have trips with fuel + food stops
            has_fuel = sum(1 for trip in self.trips if any(
                p.get("status") == "FUEL" for p in trip.get("timeline", [])
            ))
            if has_fuel == 0:
                self.findings.append("[COVERAGE] Scenario 1: No FUEL stops found (expected for long-haul)")
            
            has_food = sum(1 for trip in self.trips if any(
                p.get("status") == "FOOD" for p in trip.get("timeline", [])
            ))
            if has_food == 0:
                self.findings.append("[COVERAGE] Scenario 1: No FOOD stops found (expected for long-haul)")
        
        elif self.scenario == 2:
            # Should have frequent STOPPED events, no fuel/food
            has_stops = sum(1 for trip in self.trips if any(
                p.get("status") == "STOPPED" for p in trip.get("timeline", [])
            ))
            if has_stops == 0:
                self.findings.append("[COVERAGE] Scenario 2: No STOPPED statuses found (expected for city bus)")
            
            has_fuel = sum(1 for trip in self.trips if any(
                p.get("status") == "FUEL" for p in trip.get("timeline", [])
            ))
            if has_fuel > 0:
                self.findings.append("[COVERAGE] Scenario 2: Found FUEL stops (not expected for city shuttle)")
        
        elif self.scenario == 3:
            # Should have at least one FOOD stop, mixed road types
            has_food = sum(1 for trip in self.trips if any(
                p.get("status") == "FOOD" for p in trip.get("timeline", [])
            ))
            if has_food == 0:
                self.findings.append("[COVERAGE] Scenario 3: No FOOD stops found")
    
    def _check_boundary_presence(self) -> None:
        """Check that boundary cases for key rules exist."""
        if self.scenario == 1:
            # Check for trips just under and over 240 min (food/restroom threshold)
            # and just under and over 360 min (fuel threshold)
            durations = []
            for trip in self.trips:
                try:
                    tl = trip.get("timeline", [])
                    if len(tl) >= 2:
                        t_start = _parse_ts(tl[0]["ts"])
                        t_end = _parse_ts(tl[-1]["ts"])
                        dur_min = (t_end - t_start).total_seconds() / 60.0
                        durations.append(dur_min)
                except Exception:
                    pass
            
            if durations:
                min_dur = min(durations)
                max_dur = max(durations)
                has_sub_240 = any(200 <= d < 240 for d in durations)
                has_over_240 = any(d >= 240 for d in durations)
                
                if not has_sub_240:
                    self.findings.append(f"[BOUNDARY] Scenario 1: No trips near 240-min threshold (below). Found durations: {min(d for d in durations if d < 240 if durations):.0f} to {max(d for d in durations if d < 240 if durations):.0f} min")
                if not has_over_240:
                    self.findings.append(f"[BOUNDARY] Scenario 1: No trips near 240-min threshold (above). Found durations: {min(d for d in durations if d >= 240 if [d for d in durations if d >= 240]):.0f} to {max(d for d in durations if d >= 240 if [d for d in durations if d >= 240]):.0f} min")
    
    def _check_redundancy(self) -> None:
        """Detect near-identical trips using simple similarity metric."""
        redundancy_pairs = []
        
        for i, trip_a in enumerate(self.trips):
            for j, trip_b in enumerate(self.trips):
                if i >= j:
                    continue
                
                # Simple similarity: same trip duration ± 5 min and same vehicle type
                try:
                    tl_a = trip_a.get("timeline", [])
                    tl_b = trip_b.get("timeline", [])
                    
                    if len(tl_a) < 2 or len(tl_b) < 2:
                        continue
                    
                    dur_a = (_parse_ts(tl_a[-1]["ts"]) - _parse_ts(tl_a[0]["ts"])).total_seconds() / 60.0
                    dur_b = (_parse_ts(tl_b[-1]["ts"]) - _parse_ts(tl_b[0]["ts"])).total_seconds() / 60.0
                    
                    vtype_a = trip_a.get("vehicle", {}).get("vehicleType", "")
                    vtype_b = trip_b.get("vehicle", {}).get("vehicleType", "")
                    
                    if abs(dur_a - dur_b) < 5 and vtype_a == vtype_b:
                        # Likely redundant
                        redundancy_pairs.append((i, j, dur_a, dur_b))
                except Exception:
                    pass
        
        if redundancy_pairs:
            for i, j, da, db in redundancy_pairs:
                self.findings.append(f"[REDUNDANCY] Trips {i} and {j}: Similar durations ({da:.0f} vs {db:.0f} min) — consider deduplication")
    
    def _check_coverage(self) -> None:
        """Check for coverage of road types, statuses, and speed scenarios."""
        all_road_types = set()
        all_statuses = set()
        speed_violations = 0
        gps_anomalies = 0
        
        for trip in self.trips:
            for point in trip.get("timeline", []):
                all_road_types.add(point.get("roadType"))
                all_statuses.add(point.get("status"))
                
                # Check for violations
                road = point.get("roadType", "CITY")
                speed = float(point.get("speedKmH", 0))
                limit = SPEED_LIMITS.get(road, 50)
                if speed > limit:
                    speed_violations += 1
            
            # Check for GPS anomalies
            try:
                tl = trip.get("timeline", [])
                for i in range(1, len(tl)):
                    prev = tl[i - 1]
                    curr = tl[i]
                    dist = _haversine_km(float(prev["lat"]), float(prev["lng"]), float(curr["lat"]), float(curr["lng"]))
                    time_min = (_parse_ts(curr["ts"]) - _parse_ts(prev["ts"])).total_seconds() / 60.0
                    if time_min > 0 and dist / time_min > GPS_JUMP_THRESHOLD_KM_PER_MIN:
                        gps_anomalies += 1
            except Exception:
                pass
        
        if all_road_types:
            uncovered = VALID_ROAD_TYPES - all_road_types
            if uncovered:
                self.findings.append(f"[COVERAGE] Road types not covered: {uncovered}")
        
        if speed_violations == 0:
            self.findings.append(f"[COVERAGE] No speed violations detected across dataset (may be expected for some scenarios)")
        
        if gps_anomalies == 0 and self.scenario == 3:
            self.findings.append(f"[COVERAGE] No GPS anomalies detected (expected in Scenario 3)")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN VALIDATION ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

def load_trip_files(scenario: int, trip_type: str) -> List[Dict]:
    """Load all trip JSON files from a directory."""
    trips = []
    path = f"trips/scenario_{scenario}/{trip_type}"
    
    if not os.path.exists(path):
        print(f"  WARNING: {path} not found")
        return trips
    
    for filename in sorted(os.listdir(path)):
        if filename.endswith(".json"):
            filepath = os.path.join(path, filename)
            try:
                with open(filepath, "r") as f:
                    trip = json.load(f)
                    trips.append(trip)
            except json.JSONDecodeError as e:
                print(f"    ERROR: {filepath} has invalid JSON: {e}")
    
    return trips


def main():
    print("=" * 80)
    print("VTAP TRIP DATA VALIDATION")
    print("=" * 80)
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total_trips": 0,
            "valid_trips": 0,
            "invalid_trips": 0,
            "trips_with_warnings": 0,
        },
        "scenarios": {},
    }
    
    for scenario in [1, 2, 3]:
        print(f"\n[SCENARIO {scenario}]")
        scenario_data = {"representative": {}, "boundary": {}, "adversarial": {}}
        scenario_stats = {"total": 0, "valid": 0, "invalid": 0, "warnings": 0}
        
        for trip_type in ["representative", "boundary", "adversarial"]:
            print(f"  {trip_type.upper()}:")
            trips = load_trip_files(scenario, trip_type)
            type_stats = {"total": len(trips), "valid": 0, "invalid": 0, "warning_count": 0, "errors": [], "warnings": []}
            
            trip_errors = []
            for trip in trips:
                trip_id = trip.get("tripId", "unknown")
                validator = TripValidator(trip, trip_id)
                is_valid, errors, warnings = validator.validate()
                
                if is_valid:
                    type_stats["valid"] += 1
                else:
                    type_stats["invalid"] += 1
                    trip_errors.append({
                        "trip_id": trip_id,
                        "errors": errors,
                    })
                
                if warnings:
                    type_stats["warning_count"] += len(warnings)
            
            scenario_data[trip_type] = type_stats
            scenario_stats["total"] += len(trips)
            scenario_stats["valid"] += type_stats["valid"]
            scenario_stats["invalid"] += type_stats["invalid"]
            scenario_stats["warnings"] += type_stats["warning_count"]
            
            print(f"    Total: {len(trips)}, Valid: {type_stats['valid']}, Invalid: {type_stats['invalid']}, Warnings: {type_stats['warning_count']}")
        
        # Dataset-level validation
        all_trips = []
        for trip_type in ["representative", "boundary", "adversarial"]:
            all_trips.extend(load_trip_files(scenario, trip_type))
        
        dataset_validator = DatasetValidator(scenario, all_trips)
        dataset_findings = dataset_validator.validate()
        
        if dataset_findings:
            print(f"\n  DATASET-LEVEL FINDINGS:")
            for finding in dataset_findings:
                print(f"    {finding}")
        
        scenario_data["dataset_findings"] = dataset_findings
        report["scenarios"][f"scenario_{scenario}"] = scenario_data
        report["summary"]["total_trips"] += scenario_stats["total"]
        report["summary"]["valid_trips"] += scenario_stats["valid"]
        report["summary"]["invalid_trips"] += scenario_stats["invalid"]
        report["summary"]["trips_with_warnings"] += scenario_stats["warnings"]
    
    # Write report
    os.makedirs("reports", exist_ok=True)
    report_path = "reports/validation_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    
    print("\n" + "=" * 80)
    print(f"VALIDATION COMPLETE")
    print("=" * 80)
    print(f"\nSummary:")
    print(f"  Total trips: {report['summary']['total_trips']}")
    print(f"  Valid: {report['summary']['valid_trips']}")
    print(f"  Invalid: {report['summary']['invalid_trips']}")
    print(f"  With warnings: {report['summary']['trips_with_warnings']}")
    print(f"\nReport saved to: {report_path}")


if __name__ == "__main__":
    main()
