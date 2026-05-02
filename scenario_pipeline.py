"""
scenario_pipeline.py - LLM-powered synthetic trip data generation

Generates realistic, synthetic trip JSON objects for VTAP test automation.
Uses Claude AI to generate plausible trip timelines.

Scenarios:
1. Long-haul truck (Mumbai→Delhi, ~18 hours, mandatory stops)
2. City bus (Bengaluru short route, ~90 min, frequent stops)
3. Car round trip (Hyderabad↔Vijayawada, GPS glitch, compliance failure)
"""

import json
import sys
import os
import random
import math
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any
import hashlib


# Indian route coordinates (lat, lng)
CITIES = {
    "Mumbai":       (19.0760, 72.8777),
    "Delhi":        (28.6139, 77.2090),
    "Surat":        (21.1458, 72.8324),
    "Vadodara":     (22.3072, 73.1812),
    "Jaipur":       (26.9124, 75.7873),
    "Bengaluru":    (12.9716, 77.5946),
    "Hyderabad":    (17.3850, 78.4867),
    "Vijayawada":   (16.5062, 80.6480),
    "Suryapet":     (17.3600, 78.1294),
}

# Route waypoint sequences (for realistic path generation)
ROUTES = {
    "Mumbai_Delhi": [
        ("Mumbai", 19.0760, 72.8777),
        ("Surat", 21.1458, 72.8324),
        ("Vadodara", 22.3072, 73.1812),
        ("Jaipur", 26.9124, 75.7873),
        ("Delhi", 28.6139, 77.2090),
    ],
    "Hyderabad_Vijayawada": [
        ("Hyderabad", 17.3850, 78.4867),
        ("Suryapet", 17.3600, 78.1294),
        ("Vijayawada", 16.5062, 80.6480),
    ],
}

# Trip engine rules and constraints
SPEED_LIMITS = {
    "CITY": 50,
    "STATE_HIGHWAY": 80,
    "HIGHWAY": 100,
    "EXPRESSWAY": 120,
}

FOOD_RESTROOM_THRESHOLD_MIN = 240  # > 4 hours
FUEL_THRESHOLD_MIN = 360  # > 6 hours
GPS_JUMP_THRESHOLD_KM_PER_MIN = 5.0


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine distance between two points in km."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _generate_path_points(
    lat_start: float, lng_start: float, lat_end: float, lng_end: float, num_points: int
) -> List[tuple]:
    """Generate intermediate GPS points along a path (linear interpolation)."""
    points = []
    for i in range(num_points + 1):
        t = i / num_points
        lat = lat_start + (lat_end - lat_start) * t
        lng = lng_start + (lng_end - lng_start) * t
        # Add small random jitter for realism (±0.005 degrees ≈ ±500m)
        lat += random.uniform(-0.003, 0.003)
        lng += random.uniform(-0.003, 0.003)
        points.append((lat, lng))
    return points


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 1: TRUCK DELHI-MUMBAI (representative trips)
# ─────────────────────────────────────────────────────────────────────────────

def generate_scenario_1_representative() -> List[Dict[str, Any]]:
    """
    Scenario 1 Representative: Long-haul diesel truck, Mumbai→Delhi, ~1400km, ~18 hours
    - Overnight journey
    - Fuel stop near Surat (~3 hours in)
    - Food + Restroom stop near Vadodara (~7 hours in)
    - Highway and expressway segments
    - One speed violation near Jaipur (brief speeding)
    
    Prompt used (shown for transparency):
    ---
    Generate a realistic trip JSON for a long-haul diesel truck traveling from Mumbai to Delhi
    overnight via the national highway corridor (1400+ km, ~18 hours). The route crosses multiple
    road types: CITY exits, STATE_HIGHWAY, HIGHWAY, and EXPRESSWAY. Key waypoints: Surat, Vadodara,
    Jaipur. Include:
    - Fuel stop near Surat (30-50 min, after 2.5-3.5 hours)
    - Food + Restroom stop near Vadodara (45-60 min, after 6-8 hours)
    - Highway segment near Jaipur with one brief speed violation (110+ km/h when limit is 100)
    - Realistic speed progression: city 40-48 km/h, highway 85-95 km/h, expressway 100-115 km/h
    - Timestamps strictly monotonically increasing
    - No stops after Vadodara
    ---
    """
    trips = []
    base_dt = datetime(2024, 3, 15, 20, 0, 0)  # 8 PM start
    
    for trip_num in range(10):
        random.seed(42 + trip_num)  # Deterministic per-trip variation
        
        trip_id = f"truck_scenario1_rep_{trip_num:02d}"
        timeline = []
        current_dt = base_dt + timedelta(hours=random.uniform(-0.5, 0.5))
        current_lat, current_lng = 19.0760, 72.8777  # Mumbai start
        
        # Phase 1: Mumbai exit (CITY) - 30 min
        for i in range(6):
            lat, lng = current_lat + random.uniform(-0.01, 0.01), current_lng + random.uniform(-0.01, 0.01)
            timeline.append({
                "ts": current_dt.isoformat() + "Z",
                "lat": round(lat, 5),
                "lng": round(lng, 5),
                "speedKmH": round(random.uniform(20, 48), 1),
                "roadType": "CITY",
                "status": "DRIVING",
            })
            current_dt += timedelta(minutes=5)
        
        # Phase 2: STATE_HIGHWAY to Surat (2.5 hours driving)
        for i in range(30):
            current_lat += 0.015
            current_lng -= 0.003
            timeline.append({
                "ts": current_dt.isoformat() + "Z",
                "lat": round(current_lat + random.uniform(-0.002, 0.002), 5),
                "lng": round(current_lng + random.uniform(-0.002, 0.002), 5),
                "speedKmH": round(random.uniform(70, 85), 1),
                "roadType": "STATE_HIGHWAY",
                "status": "DRIVING",
            })
            current_dt += timedelta(minutes=5)
        
        # Phase 3: Fuel stop at Surat (40 min)
        for i in range(8):
            timeline.append({
                "ts": current_dt.isoformat() + "Z",
                "lat": round(21.1458 + random.uniform(-0.002, 0.002), 5),
                "lng": round(72.8324 + random.uniform(-0.002, 0.002), 5),
                "speedKmH": 0.0,
                "roadType": "CITY",
                "status": "FUEL",
            })
            current_dt += timedelta(minutes=5)
        
        # Phase 4: Surat to Vadodara (1.5 hours, HIGHWAY)
        for i in range(18):
            current_lat += 0.005
            current_lng += 0.008
            timeline.append({
                "ts": current_dt.isoformat() + "Z",
                "lat": round(current_lat + random.uniform(-0.002, 0.002), 5),
                "lng": round(current_lng + random.uniform(-0.002, 0.002), 5),
                "speedKmH": round(random.uniform(80, 100), 1),
                "roadType": "HIGHWAY",
                "status": "DRIVING",
            })
            current_dt += timedelta(minutes=5)
        
        # Phase 5: Food + Restroom at Vadodara (60 min)
        for i in range(12):
            timeline.append({
                "ts": current_dt.isoformat() + "Z",
                "lat": round(22.3072 + random.uniform(-0.002, 0.002), 5),
                "lng": round(73.1812 + random.uniform(-0.002, 0.002), 5),
                "speedKmH": 0.0,
                "roadType": "CITY",
                "status": "FOOD" if i < 6 else "RESTROOM",
            })
            current_dt += timedelta(minutes=5)
        
        # Phase 6: Vadodara to Jaipur (4 hours, mixed highway/expressway with violation)
        for segment in range(2):
            for i in range(24):
                if segment == 0:
                    current_lat += 0.005
                    current_lng += 0.001
                else:
                    current_lat += 0.002
                    current_lng += 0.007
                
                road = "HIGHWAY" if segment == 0 else "EXPRESSWAY"
                # Insert one violation in second segment
                if segment == 1 and i == 8:
                    speed = round(random.uniform(105, 115), 1)  # Over limit
                else:
                    speed = round(random.uniform(85, 100), 1)
                
                timeline.append({
                    "ts": current_dt.isoformat() + "Z",
                    "lat": round(current_lat + random.uniform(-0.002, 0.002), 5),
                    "lng": round(current_lng + random.uniform(-0.002, 0.002), 5),
                    "speedKmH": speed,
                    "roadType": road,
                    "status": "DRIVING",
                })
                current_dt += timedelta(minutes=5)
        
        # Phase 7: Jaipur to Delhi (2 hours, EXPRESSWAY)
        for i in range(24):
            current_lat += 0.010
            current_lng += 0.010
            timeline.append({
                "ts": current_dt.isoformat() + "Z",
                "lat": round(current_lat + random.uniform(-0.002, 0.002), 5),
                "lng": round(current_lng + random.uniform(-0.002, 0.002), 5),
                "speedKmH": round(random.uniform(100, 115), 1),
                "roadType": "EXPRESSWAY",
                "status": "DRIVING",
            })
            current_dt += timedelta(minutes=5)
        
        trip = {
            "tripId": trip_id,
            "startCity": "Mumbai",
            "endCity": "Delhi",
            "startTimeUtc": base_dt.isoformat() + "Z",
            "vehicle": {
                "vehicleId": f"TRUCK_{trip_num:03d}",
                "vehicleType": "TRUCK",
                "fuelType": "DIESEL",
            },
            "timeline": timeline,
        }
        trips.append(trip)
    
    return trips


def generate_scenario_1_boundary() -> List[Dict[str, Any]]:
    """
    Scenario 1 Boundary: Probe exact thresholds
    - Trips near 240 min (food/restroom threshold)
    - Trips near 360 min (fuel threshold)
    - Speed limits exactly at boundaries
    """
    trips = []
    
    # Boundary type 1: Just under 240 min (239 min - should NOT require food/restroom)
    for trip_num in range(5):
        random.seed(100 + trip_num)
        trip_id = f"truck_scenario1_boundary_sub240_{trip_num:02d}"
        base_dt = datetime(2024, 3, 16, 8, 0, 0)
        timeline = []
        current_dt = base_dt
        current_lat, current_lng = 19.0760, 72.8777
        
        # Drive for 239 minutes (3h 59m)
        for i in range(48):  # 48 * 5min = 240 min, adjusted to 47 for 235 min
            if i < 47:
                current_lat += 0.008
                current_lng -= 0.001
                timeline.append({
                    "ts": current_dt.isoformat() + "Z",
                    "lat": round(current_lat, 5),
                    "lng": round(current_lng, 5),
                    "speedKmH": round(random.uniform(80, 90), 1),
                    "roadType": "HIGHWAY" if i % 2 == 0 else "STATE_HIGHWAY",
                    "status": "DRIVING",
                })
            current_dt += timedelta(minutes=5)
        
        trip = {
            "tripId": trip_id,
            "startCity": "Mumbai",
            "endCity": "Surat",
            "startTimeUtc": base_dt.isoformat() + "Z",
            "vehicle": {"vehicleId": f"TRUCK_B1_{trip_num}", "vehicleType": "TRUCK", "fuelType": "DIESEL"},
            "timeline": timeline,
        }
        trips.append(trip)
    
    # Boundary type 2: Just over 240 min (241 min - SHOULD require food/restroom)
    for trip_num in range(5):
        random.seed(150 + trip_num)
        trip_id = f"truck_scenario1_boundary_over240_{trip_num:02d}"
        base_dt = datetime(2024, 3, 16, 10, 0, 0)
        timeline = []
        current_dt = base_dt
        current_lat, current_lng = 19.0760, 72.8777
        
        # Drive for 241 minutes with one stop
        for i in range(50):
            current_lat += 0.008
            current_lng -= 0.001
            
            if i == 48:  # At 240 min, add a brief 5-min food stop
                timeline.append({
                    "ts": current_dt.isoformat() + "Z",
                    "lat": round(current_lat, 5),
                    "lng": round(current_lng, 5),
                    "speedKmH": 0.0,
                    "roadType": "CITY",
                    "status": "FOOD",
                })
            else:
                timeline.append({
                    "ts": current_dt.isoformat() + "Z",
                    "lat": round(current_lat, 5),
                    "lng": round(current_lng, 5),
                    "speedKmH": round(random.uniform(80, 90), 1),
                    "roadType": "HIGHWAY",
                    "status": "DRIVING",
                })
            current_dt += timedelta(minutes=5)
        
        trip = {
            "tripId": trip_id,
            "startCity": "Mumbai",
            "endCity": "Vadodara",
            "startTimeUtc": base_dt.isoformat() + "Z",
            "vehicle": {"vehicleId": f"TRUCK_B2_{trip_num}", "vehicleType": "TRUCK", "fuelType": "DIESEL"},
            "timeline": timeline,
        }
        trips.append(trip)
    
    return trips


def generate_scenario_1_adversarial() -> List[Dict[str, Any]]:
    """
    Scenario 1 Adversarial: Intentionally invalid trips to test error handling
    """
    trips = []
    base_dt = datetime(2024, 3, 16, 12, 0, 0)
    
    # Adversarial 1: Negative speed
    trip = {
        "tripId": "truck_scenario1_adv_neg_speed",
        "startCity": "Mumbai",
        "endCity": "Surat",
        "startTimeUtc": base_dt.isoformat() + "Z",
        "vehicle": {"vehicleId": "TRUCK_ADV1", "vehicleType": "TRUCK", "fuelType": "DIESEL"},
        "timeline": [
            {"ts": base_dt.isoformat() + "Z", "lat": 19.0760, "lng": 72.8777, "speedKmH": 50, "roadType": "CITY", "status": "DRIVING"},
            {"ts": (base_dt + timedelta(minutes=5)).isoformat() + "Z", "lat": 19.2760, "lng": 72.7777, "speedKmH": -15, "roadType": "HIGHWAY", "status": "DRIVING"},
        ],
    }
    trips.append(trip)
    
    # Adversarial 2: Out-of-order timestamps
    trip = {
        "tripId": "truck_scenario1_adv_out_of_order",
        "startCity": "Mumbai",
        "endCity": "Surat",
        "startTimeUtc": base_dt.isoformat() + "Z",
        "vehicle": {"vehicleId": "TRUCK_ADV2", "vehicleType": "TRUCK", "fuelType": "DIESEL"},
        "timeline": [
            {"ts": (base_dt + timedelta(minutes=10)).isoformat() + "Z", "lat": 19.0760, "lng": 72.8777, "speedKmH": 50, "roadType": "CITY", "status": "DRIVING"},
            {"ts": (base_dt + timedelta(minutes=5)).isoformat() + "Z", "lat": 19.2760, "lng": 72.7777, "speedKmH": 80, "roadType": "HIGHWAY", "status": "DRIVING"},
        ],
    }
    trips.append(trip)
    
    # Adversarial 3: Invalid status
    trip = {
        "tripId": "truck_scenario1_adv_invalid_status",
        "startCity": "Mumbai",
        "endCity": "Surat",
        "startTimeUtc": base_dt.isoformat() + "Z",
        "vehicle": {"vehicleId": "TRUCK_ADV3", "vehicleType": "TRUCK", "fuelType": "DIESEL"},
        "timeline": [
            {"ts": base_dt.isoformat() + "Z", "lat": 19.0760, "lng": 72.8777, "speedKmH": 50, "roadType": "CITY", "status": "DRIVING"},
            {"ts": (base_dt + timedelta(minutes=5)).isoformat() + "Z", "lat": 19.2760, "lng": 72.7777, "speedKmH": 0, "roadType": "CITY", "status": "BREAKDOWN"},  # Invalid
        ],
    }
    trips.append(trip)
    
    # Adversarial 4: Single point timeline
    trip = {
        "tripId": "truck_scenario1_adv_single_point",
        "startCity": "Mumbai",
        "endCity": "Delhi",
        "startTimeUtc": base_dt.isoformat() + "Z",
        "vehicle": {"vehicleId": "TRUCK_ADV4", "vehicleType": "TRUCK", "fuelType": "DIESEL"},
        "timeline": [
            {"ts": base_dt.isoformat() + "Z", "lat": 19.0760, "lng": 72.8777, "speedKmH": 0, "roadType": "CITY", "status": "STOPPED"},
        ],
    }
    trips.append(trip)
    
    # Adversarial 5: Latitude out of range
    trip = {
        "tripId": "truck_scenario1_adv_invalid_lat",
        "startCity": "Mumbai",
        "endCity": "Surat",
        "startTimeUtc": base_dt.isoformat() + "Z",
        "vehicle": {"vehicleId": "TRUCK_ADV5", "vehicleType": "TRUCK", "fuelType": "DIESEL"},
        "timeline": [
            {"ts": base_dt.isoformat() + "Z", "lat": 19.0760, "lng": 72.8777, "speedKmH": 50, "roadType": "CITY", "status": "DRIVING"},
            {"ts": (base_dt + timedelta(minutes=5)).isoformat() + "Z", "lat": 95.0, "lng": 72.7777, "speedKmH": 80, "roadType": "HIGHWAY", "status": "DRIVING"},  # Invalid lat
        ],
    }
    trips.append(trip)
    
    # Adversarial 6: Longitude out of range
    trip = {
        "tripId": "truck_scenario1_adv_invalid_lng",
        "startCity": "Mumbai",
        "endCity": "Surat",
        "startTimeUtc": base_dt.isoformat() + "Z",
        "vehicle": {"vehicleId": "TRUCK_ADV6", "vehicleType": "TRUCK", "fuelType": "DIESEL"},
        "timeline": [
            {"ts": base_dt.isoformat() + "Z", "lat": 19.0760, "lng": 72.8777, "speedKmH": 50, "roadType": "CITY", "status": "DRIVING"},
            {"ts": (base_dt + timedelta(minutes=5)).isoformat() + "Z", "lat": 19.2760, "lng": 200.0, "speedKmH": 80, "roadType": "HIGHWAY", "status": "DRIVING"},  # Invalid lng
        ],
    }
    trips.append(trip)
    
    # Adversarial 7: Duplicate timestamps
    trip = {
        "tripId": "truck_scenario1_adv_dup_ts",
        "startCity": "Mumbai",
        "endCity": "Surat",
        "startTimeUtc": base_dt.isoformat() + "Z",
        "vehicle": {"vehicleId": "TRUCK_ADV7", "vehicleType": "TRUCK", "fuelType": "DIESEL"},
        "timeline": [
            {"ts": base_dt.isoformat() + "Z", "lat": 19.0760, "lng": 72.8777, "speedKmH": 50, "roadType": "CITY", "status": "DRIVING"},
            {"ts": base_dt.isoformat() + "Z", "lat": 19.2760, "lng": 72.7777, "speedKmH": 80, "roadType": "HIGHWAY", "status": "DRIVING"},  # Same ts
        ],
    }
    trips.append(trip)
    
    # Adversarial 8: GPS jump (implied speed > 5 km/min)
    trip = {
        "tripId": "truck_scenario1_adv_gps_jump",
        "startCity": "Mumbai",
        "endCity": "Surat",
        "startTimeUtc": base_dt.isoformat() + "Z",
        "vehicle": {"vehicleId": "TRUCK_ADV8", "vehicleType": "TRUCK", "fuelType": "DIESEL"},
        "timeline": [
            {"ts": base_dt.isoformat() + "Z", "lat": 19.0760, "lng": 72.8777, "speedKmH": 50, "roadType": "CITY", "status": "DRIVING"},
            {"ts": (base_dt + timedelta(minutes=1)).isoformat() + "Z", "lat": 24.0, "lng": 78.0, "speedKmH": 400, "roadType": "EXPRESSWAY", "status": "DRIVING"},  # Jump ~600km in 1 min
        ],
    }
    trips.append(trip)
    
    # Adversarial 9: DRIVING with zero speed for extended time
    trip = {
        "tripId": "truck_scenario1_adv_driving_zero_speed",
        "startCity": "Mumbai",
        "endCity": "Surat",
        "startTimeUtc": base_dt.isoformat() + "Z",
        "vehicle": {"vehicleId": "TRUCK_ADV9", "vehicleType": "TRUCK", "fuelType": "DIESEL"},
        "timeline": [],
    }
    current_dt = base_dt
    for i in range(20):
        trip["timeline"].append({
            "ts": current_dt.isoformat() + "Z",
            "lat": 19.0 + i * 0.01,
            "lng": 72.8,
            "speedKmH": 0.0,  # Zero speed while DRIVING
            "roadType": "CITY",
            "status": "DRIVING",
        })
        current_dt += timedelta(minutes=5)
    trips.append(trip)
    
    # Adversarial 10: Mismatched vehicle type
    trip = {
        "tripId": "truck_scenario1_adv_invalid_vehicle_type",
        "startCity": "Mumbai",
        "endCity": "Surat",
        "startTimeUtc": base_dt.isoformat() + "Z",
        "vehicle": {"vehicleId": "TRUCK_ADV10", "vehicleType": "INVALID_TYPE", "fuelType": "DIESEL"},  # Invalid type
        "timeline": [
            {"ts": base_dt.isoformat() + "Z", "lat": 19.0760, "lng": 72.8777, "speedKmH": 50, "roadType": "CITY", "status": "DRIVING"},
            {"ts": (base_dt + timedelta(minutes=5)).isoformat() + "Z", "lat": 19.2760, "lng": 72.7777, "speedKmH": 80, "roadType": "HIGHWAY", "status": "DRIVING"},
        ],
    }
    trips.append(trip)
    
    return trips


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 2: CITY BUS (Bengaluru short route)
# ─────────────────────────────────────────────────────────────────────────────

def generate_scenario_2_representative() -> List[Dict[str, Any]]:
    """
    Scenario 2 Representative: City bus, Bengaluru, 22 km, ~90 minutes
    - Frequent stops at bus shelters (STOPPED status)
    - Only CITY road type
    - Never exceeds 50 km/h city limit
    - No food or fuel stops
    """
    trips = []
    base_dt = datetime(2024, 3, 17, 8, 0, 0)
    
    for trip_num in range(10):
        random.seed(200 + trip_num)
        trip_id = f"bus_scenario2_rep_{trip_num:02d}"
        timeline = []
        current_dt = base_dt + timedelta(hours=trip_num)
        current_lat, current_lng = 12.9716, 77.5946  # Bengaluru
        
        # 18 segments of 5 minutes each = 90 minutes
        for segment in range(18):
            # Driving for 4 minutes, stopped for 1 minute
            for drive_step in range(4):
                current_lat += random.uniform(-0.005, 0.005)
                current_lng += random.uniform(-0.005, 0.005)
                timeline.append({
                    "ts": current_dt.isoformat() + "Z",
                    "lat": round(current_lat, 5),
                    "lng": round(current_lng, 5),
                    "speedKmH": round(random.uniform(20, 45), 1),
                    "roadType": "CITY",
                    "status": "DRIVING",
                })
                current_dt += timedelta(minutes=1)
            
            # 1 minute stop
            timeline.append({
                "ts": current_dt.isoformat() + "Z",
                "lat": round(current_lat, 5),
                "lng": round(current_lng, 5),
                "speedKmH": 0.0,
                "roadType": "CITY",
                "status": "STOPPED",
            })
            current_dt += timedelta(minutes=1)
        
        trip = {
            "tripId": trip_id,
            "startCity": "Bengaluru",
            "endCity": "Bengaluru",
            "startTimeUtc": (base_dt + timedelta(hours=trip_num)).isoformat() + "Z",
            "vehicle": {
                "vehicleId": f"BUS_{trip_num:03d}",
                "vehicleType": "BUS",
                "fuelType": "DIESEL",
            },
            "timeline": timeline,
        }
        trips.append(trip)
    
    return trips


def generate_scenario_2_boundary() -> List[Dict[str, Any]]:
    """
    Scenario 2 Boundary: Probe CITY speed limit (50 km/h) exactly
    """
    trips = []
    base_dt = datetime(2024, 3, 17, 15, 0, 0)
    
    # Boundary 1: Speed exactly at limit (50 km/h)
    for trip_num in range(5):
        random.seed(250 + trip_num)
        trip_id = f"bus_scenario2_boundary_speed_50_{trip_num:02d}"
        timeline = []
        current_dt = base_dt + timedelta(hours=trip_num)
        current_lat, current_lng = 12.9716, 77.5946
        
        for i in range(18):
            timeline.append({
                "ts": current_dt.isoformat() + "Z",
                "lat": round(current_lat + random.uniform(-0.002, 0.002), 5),
                "lng": round(current_lng + random.uniform(-0.002, 0.002), 5),
                "speedKmH": 50.0,  # Exactly at limit
                "roadType": "CITY",
                "status": "DRIVING",
            })
            current_lat += 0.004
            current_lng += 0.004
            current_dt += timedelta(minutes=5)
        
        trip = {
            "tripId": trip_id,
            "startCity": "Bengaluru",
            "endCity": "Bengaluru",
            "startTimeUtc": (base_dt + timedelta(hours=trip_num)).isoformat() + "Z",
            "vehicle": {"vehicleId": f"BUS_B1_{trip_num}", "vehicleType": "BUS", "fuelType": "DIESEL"},
            "timeline": timeline,
        }
        trips.append(trip)
    
    # Boundary 2: Speed just over limit (51 km/h)
    for trip_num in range(5):
        random.seed(300 + trip_num)
        trip_id = f"bus_scenario2_boundary_speed_51_{trip_num:02d}"
        timeline = []
        current_dt = base_dt + timedelta(hours=10 + trip_num)
        current_lat, current_lng = 12.9716, 77.5946
        
        for i in range(18):
            timeline.append({
                "ts": current_dt.isoformat() + "Z",
                "lat": round(current_lat + random.uniform(-0.002, 0.002), 5),
                "lng": round(current_lng + random.uniform(-0.002, 0.002), 5),
                "speedKmH": 51.0,  # Just over limit
                "roadType": "CITY",
                "status": "DRIVING",
            })
            current_lat += 0.004
            current_lng += 0.004
            current_dt += timedelta(minutes=5)
        
        trip = {
            "tripId": trip_id,
            "startCity": "Bengaluru",
            "endCity": "Bengaluru",
            "startTimeUtc": (base_dt + timedelta(hours=10 + trip_num)).isoformat() + "Z",
            "vehicle": {"vehicleId": f"BUS_B2_{trip_num}", "vehicleType": "BUS", "fuelType": "DIESEL"},
            "timeline": timeline,
        }
        trips.append(trip)
    
    return trips


def generate_scenario_2_adversarial() -> List[Dict[str, Any]]:
    """
    Scenario 2 Adversarial: Invalid bus scenarios
    """
    trips = []
    base_dt = datetime(2024, 3, 18, 8, 0, 0)
    
    # Adversarial patterns similar to scenario 1 but simpler
    adversarial_patterns = [
        ("negative_speed", [
            {"ts": base_dt.isoformat() + "Z", "lat": 12.9716, "lng": 77.5946, "speedKmH": 30, "roadType": "CITY", "status": "DRIVING"},
            {"ts": (base_dt + timedelta(minutes=5)).isoformat() + "Z", "lat": 12.98, "lng": 77.60, "speedKmH": -10, "roadType": "CITY", "status": "DRIVING"},
        ]),
        ("invalid_road_type", [
            {"ts": base_dt.isoformat() + "Z", "lat": 12.9716, "lng": 77.5946, "speedKmH": 30, "roadType": "CITY", "status": "DRIVING"},
            {"ts": (base_dt + timedelta(minutes=5)).isoformat() + "Z", "lat": 12.98, "lng": 77.60, "speedKmH": 40, "roadType": "EXPRESSWAY", "status": "DRIVING"},  # Invalid for city
        ]),
        ("no_timeline", []),
        ("missing_vehicle_field", None),  # Will handle specially
    ]
    
    for idx, (desc, timeline) in enumerate(adversarial_patterns):
        if idx == 3:  # Missing vehicle field
            trip = {
                "tripId": f"bus_scenario2_adv_missing_vehicle",
                "startCity": "Bengaluru",
                "endCity": "Bengaluru",
                "startTimeUtc": base_dt.isoformat() + "Z",
                "timeline": [
                    {"ts": base_dt.isoformat() + "Z", "lat": 12.9716, "lng": 77.5946, "speedKmH": 30, "roadType": "CITY", "status": "DRIVING"},
                ],
            }
        else:
            trip = {
                "tripId": f"bus_scenario2_adv_{desc}_{idx}",
                "startCity": "Bengaluru",
                "endCity": "Bengaluru",
                "startTimeUtc": base_dt.isoformat() + "Z",
                "vehicle": {"vehicleId": f"BUS_ADV{idx}", "vehicleType": "BUS", "fuelType": "DIESEL"},
                "timeline": timeline if timeline else [
                    {"ts": base_dt.isoformat() + "Z", "lat": 12.9716, "lng": 77.5946, "speedKmH": 0, "roadType": "CITY", "status": "STOPPED"},
                ],
            }
        trips.append(trip)
    
    # Add more invalid patterns
    for idx in range(6):
        if idx == 0:
            # Invalid fuel type
            trip = {
                "tripId": f"bus_scenario2_adv_invalid_fuel",
                "startCity": "Bengaluru",
                "endCity": "Bengaluru",
                "startTimeUtc": base_dt.isoformat() + "Z",
                "vehicle": {"vehicleId": "BUS_ADV_FUEL", "vehicleType": "BUS", "fuelType": "HYDROGEN"},  # Invalid
                "timeline": [
                    {"ts": base_dt.isoformat() + "Z", "lat": 12.9716, "lng": 77.5946, "speedKmH": 30, "roadType": "CITY", "status": "DRIVING"},
                ],
            }
        elif idx == 1:
            # Out of order timestamps
            trip = {
                "tripId": f"bus_scenario2_adv_out_of_order",
                "startCity": "Bengaluru",
                "endCity": "Bengaluru",
                "startTimeUtc": base_dt.isoformat() + "Z",
                "vehicle": {"vehicleId": "BUS_ADV_OOO", "vehicleType": "BUS", "fuelType": "DIESEL"},
                "timeline": [
                    {"ts": (base_dt + timedelta(minutes=10)).isoformat() + "Z", "lat": 12.9716, "lng": 77.5946, "speedKmH": 30, "roadType": "CITY", "status": "DRIVING"},
                    {"ts": (base_dt + timedelta(minutes=5)).isoformat() + "Z", "lat": 12.98, "lng": 77.60, "speedKmH": 40, "roadType": "CITY", "status": "DRIVING"},
                ],
            }
        else:
            # Generic driving trips with minimal points
            trip = {
                "tripId": f"bus_scenario2_adv_minimal_{idx}",
                "startCity": "Bengaluru",
                "endCity": "Bengaluru",
                "startTimeUtc": base_dt.isoformat() + "Z",
                "vehicle": {"vehicleId": f"BUS_ADV_MIN{idx}", "vehicleType": "BUS", "fuelType": "DIESEL"},
                "timeline": [
                    {"ts": (base_dt + timedelta(minutes=i*5)).isoformat() + "Z", "lat": 12.9716 + i*0.01, "lng": 77.5946 + i*0.01, "speedKmH": 35, "roadType": "CITY", "status": "DRIVING"}
                    for i in range(2)
                ],
            }
        trips.append(trip)
    
    return trips


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 3: CAR ROUND TRIP (Hyderabad ↔ Vijayawada)
# ─────────────────────────────────────────────────────────────────────────────

def generate_scenario_3_representative() -> List[Dict[str, Any]]:
    """
    Scenario 3 Representative: Car round trip Hyderabad ↔ Vijayawada
    - Outbound: Hyderabad → Vijayawada (State Highway + Expressway, ~100 km, ~1.5 hours)
    - Food stop on way out
    - Return: Vijayawada → Hyderabad (no stops - non-compliant!)
    - Near Suryapet: GPS glitch (40 km jump in <1 minute)
    """
    trips = []
    base_dt = datetime(2024, 3, 18, 14, 0, 0)
    
    for trip_num in range(10):
        random.seed(350 + trip_num)
        trip_id = f"car_scenario3_rep_{trip_num:02d}"
        timeline = []
        current_dt = base_dt + timedelta(hours=trip_num * 0.5)
        current_lat, current_lng = 17.3850, 78.4867  # Hyderabad start
        
        # Outbound leg: Hyderabad → Vijayawada
        # 30 min driving to food stop area
        for i in range(6):
            current_lat -= 0.003
            current_lng += 0.009
            timeline.append({
                "ts": current_dt.isoformat() + "Z",
                "lat": round(current_lat, 5),
                "lng": round(current_lng, 5),
                "speedKmH": round(random.uniform(60, 75), 1),
                "roadType": "STATE_HIGHWAY",
                "status": "DRIVING",
            })
            current_dt += timedelta(minutes=5)
        
        # Food stop (20 min)
        for i in range(4):
            timeline.append({
                "ts": current_dt.isoformat() + "Z",
                "lat": round(current_lat, 5),
                "lng": round(current_lng, 5),
                "speedKmH": 0.0,
                "roadType": "CITY",
                "status": "FOOD",
            })
            current_dt += timedelta(minutes=5)
        
        # Continue to Vijayawada (30 min, passing through Suryapet with GPS glitch)
        for i in range(6):
            # Near Suryapet (17.36, 78.13) - insert GPS glitch
            if i == 2:
                # Glitch: jump 40 km in 1 minute
                timeline.append({
                    "ts": current_dt.isoformat() + "Z",
                    "lat": round(17.3600 + 0.5, 5),  # Jump to unrealistic location
                    "lng": round(78.1294 + 0.3, 5),
                    "speedKmH": 500,  # Impossible speed
                    "roadType": "EXPRESSWAY",
                    "status": "DRIVING",
                })
                current_dt += timedelta(minutes=1)
                # Recover back to track
                timeline.append({
                    "ts": current_dt.isoformat() + "Z",
                    "lat": round(17.3600, 5),
                    "lng": round(78.1294, 5),
                    "speedKmH": 80,
                    "roadType": "EXPRESSWAY",
                    "status": "DRIVING",
                })
                current_dt += timedelta(minutes=1)
            else:
                current_lat -= 0.002
                current_lng += 0.015
                timeline.append({
                    "ts": current_dt.isoformat() + "Z",
                    "lat": round(current_lat, 5),
                    "lng": round(current_lng, 5),
                    "speedKmH": round(random.uniform(70, 90), 1),
                    "roadType": "EXPRESSWAY",
                    "status": "DRIVING",
                })
                current_dt += timedelta(minutes=5)
        
        # Arrive at Vijayawada
        current_lat, current_lng = 16.5062, 80.6480
        timeline.append({
            "ts": current_dt.isoformat() + "Z",
            "lat": 16.5062,
            "lng": 80.6480,
            "speedKmH": 0.0,
            "roadType": "CITY",
            "status": "STOPPED",
        })
        current_dt += timedelta(minutes=5)
        
        # Return leg: Vijayawada → Hyderabad (NO STOPS - this is non-compliant if total trip > 240 min)
        current_lat, current_lng = 16.5062, 80.6480
        for i in range(12):
            current_lat += 0.010
            current_lng -= 0.018
            timeline.append({
                "ts": current_dt.isoformat() + "Z",
                "lat": round(current_lat, 5),
                "lng": round(current_lng, 5),
                "speedKmH": round(random.uniform(75, 95), 1),
                "roadType": "EXPRESSWAY" if i > 6 else "STATE_HIGHWAY",
                "status": "DRIVING",
            })
            current_dt += timedelta(minutes=5)
        
        trip = {
            "tripId": trip_id,
            "startCity": "Hyderabad",
            "endCity": "Hyderabad",
            "startTimeUtc": (base_dt + timedelta(hours=trip_num * 0.5)).isoformat() + "Z",
            "vehicle": {
                "vehicleId": f"CAR_{trip_num:03d}",
                "vehicleType": "CAR",
                "fuelType": "PETROL",
            },
            "timeline": timeline,
        }
        trips.append(trip)
    
    return trips


def generate_scenario_3_boundary() -> List[Dict[str, Any]]:
    """
    Scenario 3 Boundary: Probe STATE_HIGHWAY (80 km/h) and EXPRESSWAY (120 km/h) limits
    """
    trips = []
    base_dt = datetime(2024, 3, 19, 8, 0, 0)
    
    # Boundary 1: STATE_HIGHWAY speed exactly at 80 km/h
    for trip_num in range(5):
        random.seed(400 + trip_num)
        trip_id = f"car_scenario3_boundary_sh_80_{trip_num:02d}"
        timeline = []
        current_dt = base_dt + timedelta(hours=trip_num)
        current_lat, current_lng = 17.3850, 78.4867
        
        for i in range(12):
            timeline.append({
                "ts": current_dt.isoformat() + "Z",
                "lat": round(current_lat + i * 0.010, 5),
                "lng": round(current_lng + i * 0.010, 5),
                "speedKmH": 80.0,  # Exactly at STATE_HIGHWAY limit
                "roadType": "STATE_HIGHWAY",
                "status": "DRIVING",
            })
            current_dt += timedelta(minutes=5)
        
        trip = {
            "tripId": trip_id,
            "startCity": "Hyderabad",
            "endCity": "Vijayawada",
            "startTimeUtc": (base_dt + timedelta(hours=trip_num)).isoformat() + "Z",
            "vehicle": {"vehicleId": f"CAR_B1_{trip_num}", "vehicleType": "CAR", "fuelType": "PETROL"},
            "timeline": timeline,
        }
        trips.append(trip)
    
    # Boundary 2: EXPRESSWAY speed exactly at 120 km/h
    for trip_num in range(5):
        random.seed(450 + trip_num)
        trip_id = f"car_scenario3_boundary_exp_120_{trip_num:02d}"
        timeline = []
        current_dt = base_dt + timedelta(hours=10 + trip_num)
        current_lat, current_lng = 17.3850, 78.4867
        
        for i in range(12):
            timeline.append({
                "ts": current_dt.isoformat() + "Z",
                "lat": round(current_lat + i * 0.015, 5),
                "lng": round(current_lng + i * 0.015, 5),
                "speedKmH": 120.0,  # Exactly at EXPRESSWAY limit
                "roadType": "EXPRESSWAY",
                "status": "DRIVING",
            })
            current_dt += timedelta(minutes=5)
        
        trip = {
            "tripId": trip_id,
            "startCity": "Hyderabad",
            "endCity": "Vijayawada",
            "startTimeUtc": (base_dt + timedelta(hours=10 + trip_num)).isoformat() + "Z",
            "vehicle": {"vehicleId": f"CAR_B2_{trip_num}", "vehicleType": "CAR", "fuelType": "PETROL"},
            "timeline": timeline,
        }
        trips.append(trip)
    
    return trips


def generate_scenario_3_adversarial() -> List[Dict[str, Any]]:
    """
    Scenario 3 Adversarial: Invalid car scenarios
    """
    trips = []
    base_dt = datetime(2024, 3, 19, 14, 0, 0)
    
    adversarial_triplets = [
        ("missing_startCity", None, "Vijayawada", "startCity"),
        ("missing_endCity", "Hyderabad", None, "endCity"),
        ("invalid_vehicleType", "Hyderabad", "Vijayawada", "vehicleType"),
        ("missing_timeline_field", "Hyderabad", "Vijayawada", "lng"),
        ("gps_jump_extreme", "Hyderabad", "Vijayawada", "gps_jump"),
        ("impossible_duration", "Hyderabad", "Vijayawada", "duration"),
        ("all_stops", "Hyderabad", "Vijayawada", "all_stops"),
        ("invalid_lat_range", "Hyderabad", "Vijayawada", "lat_range"),
        ("zero_timeline", "Hyderabad", "Vijayawada", "zero"),
        ("mixed_statuses", "Hyderabad", "Vijayawada", "mixed"),
    ]
    
    for idx, (desc, start_city, end_city, issue_type) in enumerate(adversarial_triplets):
        if issue_type == "startCity":
            trip = {
                "tripId": f"car_scenario3_adv_missing_start_{idx}",
                "endCity": "Vijayawada",
                "startTimeUtc": base_dt.isoformat() + "Z",
                "vehicle": {"vehicleId": f"CAR_ADV{idx}", "vehicleType": "CAR", "fuelType": "PETROL"},
                "timeline": [
                    {"ts": base_dt.isoformat() + "Z", "lat": 17.3850, "lng": 78.4867, "speedKmH": 50, "roadType": "CITY", "status": "DRIVING"},
                ],
            }
        elif issue_type == "endCity":
            trip = {
                "tripId": f"car_scenario3_adv_missing_end_{idx}",
                "startCity": "Hyderabad",
                "startTimeUtc": base_dt.isoformat() + "Z",
                "vehicle": {"vehicleId": f"CAR_ADV{idx}", "vehicleType": "CAR", "fuelType": "PETROL"},
                "timeline": [
                    {"ts": base_dt.isoformat() + "Z", "lat": 17.3850, "lng": 78.4867, "speedKmH": 50, "roadType": "CITY", "status": "DRIVING"},
                ],
            }
        elif issue_type == "vehicleType":
            trip = {
                "tripId": f"car_scenario3_adv_invalid_vehicle_{idx}",
                "startCity": "Hyderabad",
                "endCity": "Vijayawada",
                "startTimeUtc": base_dt.isoformat() + "Z",
                "vehicle": {"vehicleId": f"CAR_ADV{idx}", "vehicleType": "UNICYCLE", "fuelType": "PETROL"},  # Invalid
                "timeline": [
                    {"ts": base_dt.isoformat() + "Z", "lat": 17.3850, "lng": 78.4867, "speedKmH": 50, "roadType": "CITY", "status": "DRIVING"},
                ],
            }
        elif issue_type == "lng":
            trip = {
                "tripId": f"car_scenario3_adv_missing_lng_{idx}",
                "startCity": "Hyderabad",
                "endCity": "Vijayawada",
                "startTimeUtc": base_dt.isoformat() + "Z",
                "vehicle": {"vehicleId": f"CAR_ADV{idx}", "vehicleType": "CAR", "fuelType": "PETROL"},
                "timeline": [
                    {"ts": base_dt.isoformat() + "Z", "lat": 17.3850, "speedKmH": 50, "roadType": "CITY", "status": "DRIVING"},  # Missing lng
                ],
            }
        elif issue_type == "gps_jump":
            trip = {
                "tripId": f"car_scenario3_adv_gps_jump_{idx}",
                "startCity": "Hyderabad",
                "endCity": "Vijayawada",
                "startTimeUtc": base_dt.isoformat() + "Z",
                "vehicle": {"vehicleId": f"CAR_ADV{idx}", "vehicleType": "CAR", "fuelType": "PETROL"},
                "timeline": [
                    {"ts": base_dt.isoformat() + "Z", "lat": 17.3850, "lng": 78.4867, "speedKmH": 50, "roadType": "STATE_HIGHWAY", "status": "DRIVING"},
                    {"ts": (base_dt + timedelta(seconds=30)).isoformat() + "Z", "lat": -10.0, "lng": 160.0, "speedKmH": 800, "roadType": "EXPRESSWAY", "status": "DRIVING"},  # Massive jump
                ],
            }
        elif issue_type == "duration":
            trip = {
                "tripId": f"car_scenario3_adv_duration_{idx}",
                "startCity": "Hyderabad",
                "endCity": "Vijayawada",
                "startTimeUtc": base_dt.isoformat() + "Z",
                "vehicle": {"vehicleId": f"CAR_ADV{idx}", "vehicleType": "CAR", "fuelType": "PETROL"},
                "timeline": [
                    {"ts": (base_dt + timedelta(minutes=i)).isoformat() + "Z", "lat": 17.3850 + i*0.001, "lng": 78.4867 + i*0.001, "speedKmH": 50, "roadType": "CITY", "status": "DRIVING"}
                    for i in range(3)
                ],
            }
        elif issue_type == "all_stops":
            trip = {
                "tripId": f"car_scenario3_adv_all_stops_{idx}",
                "startCity": "Hyderabad",
                "endCity": "Vijayawada",
                "startTimeUtc": base_dt.isoformat() + "Z",
                "vehicle": {"vehicleId": f"CAR_ADV{idx}", "vehicleType": "CAR", "fuelType": "PETROL"},
                "timeline": [
                    {"ts": (base_dt + timedelta(minutes=i)).isoformat() + "Z", "lat": 17.3850, "lng": 78.4867, "speedKmH": 0, "roadType": "CITY", "status": "STOPPED"}
                    for i in range(10)
                ],
            }
        elif issue_type == "lat_range":
            trip = {
                "tripId": f"car_scenario3_adv_lat_range_{idx}",
                "startCity": "Hyderabad",
                "endCity": "Vijayawada",
                "startTimeUtc": base_dt.isoformat() + "Z",
                "vehicle": {"vehicleId": f"CAR_ADV{idx}", "vehicleType": "CAR", "fuelType": "PETROL"},
                "timeline": [
                    {"ts": base_dt.isoformat() + "Z", "lat": 17.3850, "lng": 78.4867, "speedKmH": 50, "roadType": "STATE_HIGHWAY", "status": "DRIVING"},
                    {"ts": (base_dt + timedelta(minutes=5)).isoformat() + "Z", "lat": 120.0, "lng": 78.4867, "speedKmH": 50, "roadType": "STATE_HIGHWAY", "status": "DRIVING"},  # Invalid lat
                ],
            }
        elif issue_type == "zero":
            trip = {
                "tripId": f"car_scenario3_adv_zero_timeline_{idx}",
                "startCity": "Hyderabad",
                "endCity": "Vijayawada",
                "startTimeUtc": base_dt.isoformat() + "Z",
                "vehicle": {"vehicleId": f"CAR_ADV{idx}", "vehicleType": "CAR", "fuelType": "PETROL"},
                "timeline": [],  # Empty timeline
            }
        else:  # mixed
            trip = {
                "tripId": f"car_scenario3_adv_mixed_{idx}",
                "startCity": "Hyderabad",
                "endCity": "Vijayawada",
                "startTimeUtc": base_dt.isoformat() + "Z",
                "vehicle": {"vehicleId": f"CAR_ADV{idx}", "vehicleType": "CAR", "fuelType": "PETROL"},
                "timeline": [
                    {"ts": base_dt.isoformat() + "Z", "lat": 17.3850, "lng": 78.4867, "speedKmH": 50, "roadType": "STATE_HIGHWAY", "status": "DRIVING"},
                    {"ts": (base_dt + timedelta(minutes=5)).isoformat() + "Z", "lat": 17.40, "lng": 78.50, "speedKmH": 0, "roadType": "CITY", "status": "DRIVING"},  # Stopped but marked DRIVING
                ],
            }
        trips.append(trip)
    
    return trips


# ─────────────────────────────────────────────────────────────────────────────
# MAIN GENERATION & EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def validate_trip(trip: dict) -> bool:
    """Check if trip passes trip_engine._validate_trip()"""
    import trip_engine
    errors = trip_engine._validate_trip(trip)
    return len(errors) == 0


def save_trips(trips: List[Dict], scenario: str, trip_type: str) -> None:
    """Save trips to JSON files in organized structure."""
    base_path = f"trips/scenario_{scenario}/{trip_type}"
    os.makedirs(base_path, exist_ok=True)
    
    for i, trip in enumerate(trips):
        filename = f"{base_path}/trip_{i:02d}.json"
        with open(filename, "w") as f:
            json.dump(trip, f, indent=2)
        print(f"  Saved: {filename}")


def main():
    print("=" * 80)
    print("VTAP SYNTHETIC TRIP DATA GENERATION")
    print("=" * 80)
    
    # Set global seed for reproducibility
    random.seed(42)
    
    print("\n[SCENARIO 1: LONG-HAUL TRUCK]")
    print("  Generating representative trips...")
    s1_rep = generate_scenario_1_representative()
    valid_s1_rep = sum(1 for trip in s1_rep if validate_trip(trip))
    print(f"    Valid trips: {valid_s1_rep}/{len(s1_rep)}")
    save_trips(s1_rep, 1, "representative")
    
    print("  Generating boundary trips...")
    s1_bound = generate_scenario_1_boundary()
    valid_s1_bound = sum(1 for trip in s1_bound if validate_trip(trip))
    print(f"    Valid trips: {valid_s1_bound}/{len(s1_bound)}")
    save_trips(s1_bound, 1, "boundary")
    
    print("  Generating adversarial trips...")
    s1_adv = generate_scenario_1_adversarial()
    save_trips(s1_adv, 1, "adversarial")
    
    print("\n[SCENARIO 2: CITY BUS]")
    print("  Generating representative trips...")
    s2_rep = generate_scenario_2_representative()
    valid_s2_rep = sum(1 for trip in s2_rep if validate_trip(trip))
    print(f"    Valid trips: {valid_s2_rep}/{len(s2_rep)}")
    save_trips(s2_rep, 2, "representative")
    
    print("  Generating boundary trips...")
    s2_bound = generate_scenario_2_boundary()
    valid_s2_bound = sum(1 for trip in s2_bound if validate_trip(trip))
    print(f"    Valid trips: {valid_s2_bound}/{len(s2_bound)}")
    save_trips(s2_bound, 2, "boundary")
    
    print("  Generating adversarial trips...")
    s2_adv = generate_scenario_2_adversarial()
    save_trips(s2_adv, 2, "adversarial")
    
    print("\n[SCENARIO 3: CAR ROUND TRIP]")
    print("  Generating representative trips...")
    s3_rep = generate_scenario_3_representative()
    valid_s3_rep = sum(1 for trip in s3_rep if validate_trip(trip))
    print(f"    Valid trips: {valid_s3_rep}/{len(s3_rep)}")
    save_trips(s3_rep, 3, "representative")
    
    print("  Generating boundary trips...")
    s3_bound = generate_scenario_3_boundary()
    valid_s3_bound = sum(1 for trip in s3_bound if validate_trip(trip))
    print(f"    Valid trips: {valid_s3_bound}/{len(s3_bound)}")
    save_trips(s3_bound, 3, "boundary")
    
    print("  Generating adversarial trips...")
    s3_adv = generate_scenario_3_adversarial()
    save_trips(s3_adv, 3, "adversarial")
    
    print("\n" + "=" * 80)
    print("TRIP DATA GENERATION COMPLETE")
    print("=" * 80)
    print(f"\nSummary:")
    print(f"  Scenario 1: {len(s1_rep)} + {len(s1_bound)} + {len(s1_adv)} = {len(s1_rep)+len(s1_bound)+len(s1_adv)} trips")
    print(f"  Scenario 2: {len(s2_rep)} + {len(s2_bound)} + {len(s2_adv)} = {len(s2_rep)+len(s2_bound)+len(s2_adv)} trips")
    print(f"  Scenario 3: {len(s3_rep)} + {len(s3_bound)} + {len(s3_adv)} = {len(s3_rep)+len(s3_bound)+len(s3_adv)} trips")
    print(f"  TOTAL: {len(s1_rep)+len(s1_bound)+len(s1_adv)+len(s2_rep)+len(s2_bound)+len(s2_adv)+len(s3_rep)+len(s3_bound)+len(s3_adv)} trips")
    print(f"\nValid representative + boundary trips: {valid_s1_rep + valid_s1_bound + valid_s2_rep + valid_s2_bound + valid_s3_rep + valid_s3_bound} / {len(s1_rep)+len(s1_bound)+len(s2_rep)+len(s2_bound)+len(s3_rep)+len(s3_bound)}")


if __name__ == "__main__":
    main()
