import json
import os
import re
import logging  # <-- Changed from 'import logger'

# Set up a logger dedicated to this module's operations
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------
# CACHE IMPLEMENTATION LAYER
# ----------------------------------------------------------------
def load_cache(cache_file):
    """Reads the persistent local JSON flight cache."""
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(cache_data, cache_file):
    """Writes the updated flight definitions back to disk."""
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Could not write to cache file: {e}")

def generate_shuttle_cache_key(flight_number, pickup_time_str, manifest_date):
    """Creates a unique compound key for short-haul commuter routes, explicitly scoped by date."""
    clean_pickup = re.sub(r'[\s\:\-]', '', str(pickup_time_str))
    clean_date = re.sub(r'[\s\:\-]', '', str(manifest_date or "anyday"))
    return f"{flight_number}_{clean_date}_{clean_pickup}"