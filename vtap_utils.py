"""
vtap_utils.py - Shared utility functions for VTAP framework

Contains common functions used across scenario_pipeline.py, validator.py, and runner.py.
"""

import math
from datetime import datetime


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate haversine distance between two points in kilometers.
    
    Args:
        lat1, lng1: Starting latitude and longitude
        lat2, lng2: Ending latitude and longitude
    
    Returns:
        Distance in kilometers
    """
    R = 6371.0  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_ts(ts_str: str) -> datetime:
    """
    Parse ISO 8601 UTC timestamp string to datetime object.
    
    Handles both explicit 'Z' suffix and '+00:00' format.
    
    Args:
        ts_str: Timestamp string in ISO 8601 format (e.g., "2024-03-15T06:00:00Z" or "2024-03-15T06:00:00+00:00")
    
    Returns:
        datetime object with timezone info
    """
    # Normalize: remove Z and add +00:00, but avoid double +00:00
    ts_str = ts_str.rstrip('Z')  # Remove trailing Z if present
    if not ts_str.endswith(('+00:00', '-00:00')):  # Check if timezone info is already present
        ts_str += '+00:00'
    return datetime.fromisoformat(ts_str)
