import json
import os

# Define where your local cache file lives
CACHE_FILE = "flight_cache.json"

def load_cache():
    """Loads the local JSON cache file if it exists, otherwise returns an empty dict."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(cache_data):
    """Saves the updated cache dictionary back to the local file."""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Warning: Could not write to cache file: {e}")