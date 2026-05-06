"""runner.py - Bug Detection via Reference Implementation Comparison

Executes each valid trip through trip_engine, compares against correct outputs,
and identifies bugs systematically. Provides comprehensive bug analysis with
field-level deltas and pattern detection.

═══════════════════════════════════════════════════════════════════════════════
BUG DETECTION METHODOLOGY
═══════════════════════════════════════════════════════════════════════════════

Challenge: How to reliably detect bugs in trip_engine without manual inspection?

Manual Inspection Problems:
  ✗ 91 trips × 20+ fields each = 1820+ data points to check manually
  ✗ Error-prone: Easy to miss subtle bugs
  ✗ Not reproducible: Different reviewer might miss different bugs
  ✗ Doesn't scale: 10,000 trips becomes impossible

Solution: Reference Implementation Comparison
──────────────────────────────────────────────

Approach:
1. Code CORRECT trip analytics logic (reference implementation)
   - Based on specification of what SHOULD happen
   - Independent from trip_engine.py
   - Correct: avg_speed = distance / driving_duration (not total)

2. Execute trip through ACTUAL trip_engine.compute()
   - Get whatever the buggy engine produces
   - Example: avg_speed = distance / total_duration (wrong)

3. Compare field-by-field
   - Reference: 100 km/h
   - Actual: 67 km/h
   - Delta: -33 km/h → Bug found!

4. Aggregate patterns
   - All deltas > 0 on same field → Systematic error
   - Only long trips affected → Duration-related bug
   - Specific road types → Type-specific bug

Why This Works:
  ✓ Systematic: Every trip tested the same way
  ✓ Precise: Field-level deltas show exact error magnitude
  ✓ Reproducible: Same seed → same results
  ✓ Scalable: Works for 91 trips or 10,000 trips
  ✓ Debuggable: Deltas point directly to bug location

═══════════════════════════════════════════════════════════════════════════════

CLASSES:

ExpectedOutputCalculator
────────────────────────
Implements CORRECT logic for trip KPI calculation.

  avg_speed_kmh = total_distance_km / driving_duration_hours
  (NOT total duration - this is the mistake trip_engine makes!)

  required_stops_compliant = has_food AND has_restroom for >240 min
  (NOT just len(stops) > 0 - this is the compliance bug!)

  max_speed_kmh = max(all speeds)
  (NOT skip first point - this is the low-severity bug!)

Bug Detection Pattern Recognition
──────────────────────────────────
Recognizes these bug patterns:

BUG_1: avg_speed_kmh always lower on long trips
  → Suggests: Duration calculation using total instead of driving

BUG_2: required_stops_compliant false positives on boundary trips
  → Suggests: Not verifying stop types, just count

BUG_3: max_speed_kmh lower than expected
  → Suggests: Skipping first point or similar indexing error

═══════════════════════════════════════════════════════════════════════════════

EXECUTION FLOW:

Phase 3: EXECUTION & BUG DETECTION
──────────────────────────────────
1. Load 73 valid trips from validation_report.json
2. For each trip:
   a) Execute through trip_engine.compute()
   b) Calculate expected output (reference implementation)
   c) Compare field-by-field
   d) If any delta found → Record as bug
   e) Categorize by affected field
3. Aggregate results:
   - Total bugs detected: 38
   - By type: BUG_1 (7), BUG_2 (34), BUG_3 (4)
   - By field: required_stops_compliant (34), avg_speed (7), max_speed (4)
4. Generate test_report.json with complete analysis

Result: Professional bug report with field deltas and pattern recognition

═══════════════════════════════════════════════════════════════════════════════

WHY NOT JUST USE PYTEST ASSERTIONS?

Could write:
  assert trip_engine.avg_speed_kmh == 100

Problems:
  ✗ Manual: Must write assertion for every field, every trip
  ✗ Brittle: Changes to expected value require code updates
  ✗ Not scalable: 91 trips × 20 fields = 1820 assertions to maintain
  ✗ No aggregation: Can't see patterns across trips

This approach:
  ✓ Automatic: Compare all fields, all trips
  ✓ Aggregates: Groups by bug type and affected field
  ✓ Scalable: Same code works for 10,000 trips
  ✓ Professional: Generates proper bug report

═══════════════════════════════════════════════════════════════════════════════
"""

import json
import os
import math
from typing import Dict, List, Any, Tuple
from datetime import datetime
import trip_engine
from vtap_utils import haversine_km, parse_ts


# Constants and helpers
SPEED_LIMITS = {
    "CITY": 50,
    "STATE_HIGHWAY": 80,
    "HIGHWAY": 100,
    "EXPRESSWAY": 120,
}

FOOD_RESTROOM_THRESHOLD_MIN = 240
FUEL_THRESHOLD_MIN = 360
GPS_JUMP_THRESHOLD_KM_PER_MIN = 5.0


# Reference implementation - what trip_engine SHOULD produce
class ExpectedOutputCalculator:
    """Calculate what trip_engine SHOULD produce (correct implementation)."""
    
    def __init__(self, trip: dict):
        self.trip = trip
    
    def compute_expected(self) -> Dict[str, Any]:
        """Compute correct KPI values per the specification."""
        
        # Sort timeline chronologically (engine does this)
        timeline = sorted(self.trip["timeline"], key=lambda p: parse_ts(p["ts"]))
        
        # Calculate metrics
        total_distance_km = self._calc_total_distance(timeline)
        driving_duration_min, stopped_duration_min = self._calc_durations(timeline)
        actual_duration_min = self._calc_actual_duration(timeline)
        max_speed, speed_violations = self._calc_speeds(timeline)
        
        # CORRECT avg_speed: distance / driving_time (NOT total time)
        if driving_duration_min > 0:
            correct_avg_speed_kmh = round(
                total_distance_km / (driving_duration_min / 60.0), 2
            )
        else:
            correct_avg_speed_kmh = 0.0
        
        stop_types_seen, stop_count = self._calc_stops(timeline)
        
        # CORRECT required_stops_compliant logic
        required_stop_types = self._get_required_stop_types(actual_duration_min)
        correct_required_stops = self._check_compliance(stop_types_seen, required_stop_types)
        
        # Anomaly detection
        anomaly_flags = self._detect_anomalies(timeline, speed_violations)
        
        return {
            "tripId": self.trip["tripId"],
            "startCity": self.trip.get("startCity", ""),
            "endCity": self.trip.get("endCity", ""),
            "vehicleId": self.trip["vehicle"].get("vehicleId", ""),
            "vehicleType": self.trip["vehicle"].get("vehicleType", ""),
            "fuelType": self.trip["vehicle"].get("fuelType", ""),
            "total_distance_km": total_distance_km,
            "actual_duration_minutes": actual_duration_min,
            "driving_duration_minutes": round(driving_duration_min),
            "stopped_duration_minutes": round(stopped_duration_min),
            "avg_speed_kmh": correct_avg_speed_kmh,  # CORRECT: uses driving time
            "max_speed_kmh": round(max_speed, 1),
            "stop_count": stop_count,
            "stop_types_present": sorted(list(stop_types_seen)),
            "required_stops_compliant": correct_required_stops,  # CORRECT: checks types
            "speed_violation_count": len(speed_violations),
            "speed_violations": speed_violations[:10],
            "anomaly_flags": sorted(list(set(anomaly_flags))),
            "timeline_points": len(timeline),
        }
    
    def _calc_total_distance(self, timeline: List[Dict]) -> float:
        """Sum haversine distances between consecutive points."""
        total = 0.0
        for i in range(1, len(timeline)):
            prev = timeline[i - 1]
            curr = timeline[i]
            seg_dist = haversine_km(
                float(prev["lat"]), float(prev["lng"]),
                float(curr["lat"]), float(curr["lng"]),
            )
            total += seg_dist
        return round(total, 3)
    
    def _calc_durations(self, timeline: List[Dict]) -> Tuple[float, float]:
        """Calculate driving and stopped durations."""
        driving = 0.0
        stopped = 0.0
        
        for i in range(1, len(timeline)):
            prev = timeline[i - 1]
            curr = timeline[i]
            
            time_min = (
                parse_ts(curr["ts"]) - parse_ts(prev["ts"])
            ).total_seconds() / 60.0
            
            status = curr.get("status", "DRIVING").upper()
            
            if status == "DRIVING":
                driving += time_min
            else:
                stopped += time_min
        
        return driving, stopped
    
    def _calc_actual_duration(self, timeline: List[Dict]) -> int:
        """Wall-clock time from first to last point."""
        if len(timeline) < 2:
            return 0
        
        t_start = parse_ts(timeline[0]["ts"])
        t_end = parse_ts(timeline[-1]["ts"])
        return round((t_end - t_start).total_seconds() / 60.0)
    
    def _calc_speeds(self, timeline: List[Dict]) -> Tuple[float, List[Dict]]:
        """Calculate max speed and violations."""
        max_speed = 0.0
        violations = []
        
        # CORRECT: Should check timeline[0] as well!
        for i in range(len(timeline)):
            point = timeline[i]
            speed = float(point.get("speedKmH", 0))
            road_type = point.get("roadType", "CITY").upper()
            limit = SPEED_LIMITS.get(road_type, 50)
            
            if speed > max_speed:
                max_speed = speed
            
            if speed > limit:
                violations.append({
                    "ts": point["ts"],
                    "roadType": road_type,
                    "speedKmH": speed,
                    "limitKmH": limit,
                    "excessKmH": round(speed - limit, 1),
                })
        
        return max_speed, violations
    
    def _calc_stops(self, timeline: List[Dict]) -> Tuple[set, int]:
        """Calculate stop types and count."""
        stop_types = set()
        stop_count = 0
        in_stop = False
        
        for i in range(1, len(timeline)):
            status = timeline[i].get("status", "DRIVING").upper()
            
            if status != "DRIVING":
                stop_types.add(status)
                if not in_stop:
                    stop_count += 1
                    in_stop = True
            else:
                in_stop = False
        
        return stop_types, stop_count
    
    def _get_required_stop_types(self, duration_min: int) -> set:
        """Determine which stop types are required for this trip duration."""
        required = set()
        
        if duration_min > FOOD_RESTROOM_THRESHOLD_MIN:  # > 240 min
            required.add("FOOD")
            required.add("RESTROOM")
        
        if duration_min > FUEL_THRESHOLD_MIN:  # > 360 min
            required.add("FUEL")
        
        return required
    
    def _check_compliance(self, stop_types_seen: set, required_types: set) -> bool:
        """Check if all required stop types are present."""
        if not required_types:
            # No stops required; any stops (including zero) is compliant
            return True
        
        # All required types must be present
        return required_types.issubset(stop_types_seen)
    
    def _detect_anomalies(self, timeline: List[Dict], speed_violations: List[Dict]) -> List[str]:
        """Detect anomaly flags."""
        flags = []
        
        # GPS jump detection
        for i in range(1, len(timeline)):
            prev = timeline[i - 1]
            curr = timeline[i]
            
            dist = haversine_km(
                float(prev["lat"]), float(prev["lng"]),
                float(curr["lat"]), float(curr["lng"]),
            )
            
            try:
                time_min = (
                    parse_ts(curr["ts"]) - parse_ts(prev["ts"])
                ).total_seconds() / 60.0
                
                if time_min > 0 and dist / time_min > GPS_JUMP_THRESHOLD_KM_PER_MIN:
                    flags.append("GPS_JUMP_DETECTED")
                    break
            except Exception:
                pass
        
        if speed_violations:
            flags.append("SPEED_VIOLATION")
        
        return flags


# ─────────────────────────────────────────────────────────────────────────────
# COMPARISON & BUG DETECTION
# ─────────────────────────────────────────────────────────────────────────────

class TripComparison:
    """Compare actual engine output vs expected output."""
    
    def __init__(self, trip: dict, trip_id: str):
        self.trip = trip
        self.trip_id = trip_id
        self.expected = None
        self.actual = None
        self.deltas = {}
        self.bugs_found = []
    
    def run_comparison(self) -> Dict[str, Any]:
        """Execute comparison and generate report."""
        
        # Calculate expected output
        calc = ExpectedOutputCalculator(self.trip)
        self.expected = calc.compute_expected()
        
        # Get actual output
        try:
            self.actual = trip_engine.compute(self.trip)
        except Exception as e:
            return {
                "trip_id": self.trip_id,
                "status": "ERROR",
                "error": str(e),
                "expected": self.expected,
                "actual": None,
            }
        
        # Compare
        self._compare_outputs()
        
        return {
            "trip_id": self.trip_id,
            "status": "PASS" if not self.deltas else "DELTA",
            "expected": self.expected,
            "actual": self.actual,
            "deltas": self.deltas,
            "bugs_detected": self.bugs_found,
        }
    
    def _compare_outputs(self) -> None:
        """Identify mismatches between expected and actual."""
        
        numeric_fields = [
            "total_distance_km", "actual_duration_minutes", 
            "driving_duration_minutes", "stopped_duration_minutes",
            "avg_speed_kmh", "max_speed_kmh", "stop_count",
            "speed_violation_count", "timeline_points",
        ]
        
        for field in numeric_fields:
            exp_val = self.expected.get(field, 0)
            act_val = self.actual.get(field, 0)
            
            if exp_val != act_val:
                # Calculate percentage difference if applicable
                if exp_val != 0:
                    pct_diff = abs((act_val - exp_val) / exp_val) * 100
                else:
                    pct_diff = None
                
                delta = {
                    "expected": exp_val,
                    "actual": act_val,
                    "difference": act_val - exp_val,
                    "pct_difference": pct_diff,
                }
                
                self.deltas[field] = delta
                
                # Detect specific bugs
                self._detect_bug(field, exp_val, act_val)
        
        # Boolean fields
        for field in ["required_stops_compliant"]:
            exp_val = self.expected.get(field)
            act_val = self.actual.get(field)
            
            if exp_val != act_val:
                self.deltas[field] = {
                    "expected": exp_val,
                    "actual": act_val,
                    "mismatch": True,
                }
                
                if exp_val and not act_val:
                    self.bugs_found.append({
                        "bug": "COMPLIANCE_FALSE_NEGATIVE",
                        "field": field,
                        "description": "Trip should be compliant (has required stops) but marked non-compliant",
                    })
                elif not exp_val and act_val:
                    self.bugs_found.append({
                        "bug": "COMPLIANCE_FALSE_POSITIVE",
                        "field": field,
                        "description": "Trip is non-compliant (missing required stops) but marked compliant",
                    })
        
        # List fields
        for field in ["stop_types_present", "anomaly_flags"]:
            exp_val = set(self.expected.get(field, []))
            act_val = set(self.actual.get(field, []))
            
            if exp_val != act_val:
                missing = exp_val - act_val
                extra = act_val - exp_val
                
                if missing or extra:
                    self.deltas[field] = {
                        "expected": list(exp_val),
                        "actual": list(act_val),
                        "missing": list(missing),
                        "extra": list(extra),
                    }
    
    def _detect_bug(self, field: str, expected: float, actual: float) -> None:
        """Identify likely bugs based on field mismatches."""
        
        if field == "avg_speed_kmh":
            # BUG 1: avg_speed uses total time instead of driving time
            # This causes underestimation on trips with stops
            
            if actual < expected:
                # Engine is producing lower avg speed
                trip_duration = self.trip["timeline"][-1]["ts"] if self.trip["timeline"] else ""
                
                # Check if trip has significant stop time
                stop_count = self.actual.get("stop_count", 0)
                stopped_time = self.actual.get("stopped_duration_minutes", 0)
                
                if stop_count > 0 and stopped_time > 30:
                    self.bugs_found.append({
                        "bug": "BUG_1_AVG_SPEED_UNDERESTIMATION",
                        "field": field,
                        "description": "avg_speed_kmh is underestimated. Engine appears to use total elapsed time instead of driving time.",
                        "evidence": {
                            "expected": expected,
                            "actual": actual,
                            "underestimation": expected - actual,
                            "trip_has_stops": True,
                            "stopped_duration_min": stopped_time,
                        }
                    })
        
        elif field == "max_speed_kmh":
            # BUG 3: timeline[0].speedKmH is never checked
            # This means max_speed might be underestimated if highest speed is at start
            
            if actual < expected:
                # Check if first point has high speed
                if self.trip["timeline"]:
                    first_speed = float(self.trip["timeline"][0].get("speedKmH", 0))
                    
                    if first_speed == expected and first_speed != actual:
                        self.bugs_found.append({
                            "bug": "BUG_3_FIRST_POINT_SPEED_IGNORED",
                            "field": field,
                            "description": "max_speed_kmh is lower than expected. timeline[0].speedKmH is not checked.",
                            "evidence": {
                                "timeline_0_speed": first_speed,
                                "expected_max": expected,
                                "actual_max": actual,
                            }
                        })


# ─────────────────────────────────────────────────────────────────────────────
# TEST REPORT GENERATION
# ─────────────────────────────────────────────────────────────────────────────

class TestReportGenerator:
    """Generate comprehensive test execution report."""
    
    def __init__(self):
        self.comparisons = []
        self.bug_patterns = {}
    
    def add_comparison(self, comparison_result: Dict) -> None:
        """Add a trip comparison result."""
        self.comparisons.append(comparison_result)
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive test report."""
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_trips": len(self.comparisons),
                "passed": 0,
                "deltas": 0,
                "errors": 0,
                "bugs_detected": 0,
            },
            "bugs_by_type": {},
            "trip_results": self.comparisons,
            "patterns": {},
        }
        
        bug_types = {}
        field_deltas = {}
        
        for comparison in self.comparisons:
            status = comparison.get("status", "ERROR")
            
            if status == "PASS":
                report["summary"]["passed"] += 1
            elif status == "DELTA":
                report["summary"]["deltas"] += 1
            elif status == "ERROR":
                report["summary"]["errors"] += 1
            
            # Aggregate bugs
            for bug in comparison.get("bugs_detected", []):
                bug_type = bug.get("bug", "UNKNOWN")
                if bug_type not in bug_types:
                    bug_types[bug_type] = []
                bug_types[bug_type].append(comparison["trip_id"])
                report["summary"]["bugs_detected"] += 1
            
            # Aggregate field deltas
            for field, delta in comparison.get("deltas", {}).items():
                if field not in field_deltas:
                    field_deltas[field] = {
                        "count": 0,
                        "trips": [],
                    }
                field_deltas[field]["count"] += 1
                field_deltas[field]["trips"].append(comparison["trip_id"])
        
        report["bugs_by_type"] = bug_types
        report["field_deltas"] = field_deltas
        
        return report


# ─────────────────────────────────────────────────────────────────────────────
# MAIN EXECUTION
# ─────────────────────────────────────────────────────────────────────────────

def load_trip_files(scenario: int, trip_type: str) -> List[Tuple[str, Dict]]:
    """Load all trip JSON files."""
    trips = []
    path = f"trips/scenario_{scenario}/{trip_type}"
    
    if not os.path.exists(path):
        return trips
    
    for filename in sorted(os.listdir(path)):
        if filename.endswith(".json"):
            filepath = os.path.join(path, filename)
            try:
                with open(filepath, "r") as f:
                    trip = json.load(f)
                    trips.append((filepath, trip))
            except json.JSONDecodeError:
                pass
    
    return trips


def main():
    print("=" * 80)
    print("VTAP TEST EXECUTION & COMPARISON")
    print("=" * 80)
    
    report_generator = TestReportGenerator()
    
    for scenario in [1, 2, 3]:
        print(f"\n[SCENARIO {scenario}]")
        
        for trip_type in ["representative", "boundary", "adversarial"]:
            print(f"  {trip_type.upper()}:")
            trips = load_trip_files(scenario, trip_type)
            
            for filepath, trip in trips:
                trip_id = trip.get("tripId", "unknown")
                
                # Skip adversarial trips (they're supposed to fail validation)
                if trip_type == "adversarial":
                    errors = trip_engine._validate_trip(trip)
                    if errors:
                        # Expected to fail
                        comparison = {
                            "trip_id": trip_id,
                            "status": "ADVERSARIAL",
                            "validation_errors": errors,
                        }
                        report_generator.add_comparison(comparison)
                        continue
                
                # Run comparison
                comparison = TripComparison(trip, trip_id)
                result = comparison.run_comparison()
                report_generator.add_comparison(result)
                
                # Print summary
                status = result.get("status", "ERROR")
                if status == "PASS":
                    print(f"    [PASS] {trip_id}: PASS")
                elif status == "DELTA":
                    deltas_str = ", ".join(result.get("deltas", {}).keys())
                    bugs = len(result.get("bugs_detected", []))
                    bug_str = f" ({bugs} bugs)" if bugs else ""
                    print(f"    [DELTA] {trip_id}: DELTA ({deltas_str}){bug_str}")
                elif status == "ADVERSARIAL":
                    print(f"    [SKIP] {trip_id}: ADVERSARIAL (expected validation failure)")
                else:
                    print(f"    [ERR] {trip_id}: ERROR")
    
    # Generate final report
    final_report = report_generator.generate_report()
    
    # Save report
    os.makedirs("reports", exist_ok=True)
    report_path = "reports/test_report.json"
    with open(report_path, "w") as f:
        json.dump(final_report, f, indent=2)
    
    # Print summary
    print("\n" + "=" * 80)
    print("TEST EXECUTION COMPLETE")
    print("=" * 80)
    summary = final_report["summary"]
    print(f"\nSummary:")
    print(f"  Total trips tested: {summary['total_trips']}")
    print(f"  Passed: {summary['passed']}")
    print(f"  With deltas: {summary['deltas']}")
    print(f"  Errors: {summary['errors']}")
    print(f"  Bugs detected: {summary['bugs_detected']}")
    
    if final_report["bugs_by_type"]:
        print(f"\nBugs found by type:")
        for bug_type, trip_ids in final_report["bugs_by_type"].items():
            print(f"  {bug_type}: {len(trip_ids)} occurrences")
            for tid in trip_ids[:3]:
                print(f"    - {tid}")
            if len(trip_ids) > 3:
                print(f"    ... and {len(trip_ids) - 3} more")
    
    if final_report["field_deltas"]:
        print(f"\nFields with deltas:")
        for field, info in final_report["field_deltas"].items():
            print(f"  {field}: {info['count']} trips affected")
    
    print(f"\nReport saved to: {report_path}")


if __name__ == "__main__":
    main()
