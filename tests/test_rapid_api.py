import os
import json
import re
import requests
from dotenv import load_dotenv

# Load environment variables from your .env file
load_dotenv()
APIMARKET_KEY = os.environ.get("APIMARKET_KEY")

def normalize_date_for_api(raw_date_str):
    """Ensures raw date strings are formatted to standard YYYY-MM-DD."""
    if not raw_date_str:
        return ""
    cleaned = str(raw_date_str).strip().replace("/", "-")
    if re.match(r'^\d{4}-\d{2}-\d{2}$', cleaned):
        return cleaned
    if re.match(r'^\d{2}-\d{2}$', cleaned):
        return f"2026-{cleaned}"
    return cleaned

def debug_date_flight_api(flight_number, raw_date):
    if not APIMARKET_KEY:
        print("CRITICAL ERROR: APIMARKETAPI_KEY not found in your environment or .env file.")
        return

    target_date = normalize_date_for_api(raw_date)
    if not target_date:
        print("ERROR: Please provide a valid date string (e.g., '2026-06-29' or '06-29').")
        return

    print(f"Connecting to AeroDataBox targeted date endpoint...")
    print(f"Target: Flight {flight_number} on Date {target_date}")
    
    url = f"https://aerodatabox.p.rapidapi.com/flights/number/{flight_number}/{target_date}"
    headers = {
        "X-RapidAPI-Key": APIMARKET_KEY,
        "X-RapidAPI-Host": "aerodatabox.p.rapidapi.com"
    }
    
    try:
        response = requests.get(url, headers=headers)
        print(f"HTTP Status Code: {response.status_code}")
        
        if response.status_code == 204:
            print(f" Result: HTTP 204. No schedules exist for {flight_number} on {target_date}.")
            return
        elif response.status_code != 200:
            print(f" Result: Request failed. Error message: {response.text}")
            return
            
        data = response.json()
        print("\n=== RAW API RESPONSE DATA ===")
        print(json.dumps(data, indent=4, ensure_ascii=False))
        print("===============================\n")
        
        if isinstance(data, list):
            print(f"Summary: Found {len(data)} flight instance(s) matching exactly on {target_date}:")
            for i, leg in enumerate(data):
                origin = leg.get("departure", {}).get("airport", {}).get("iata", "Unknown")
                dest = leg.get("arrival", {}).get("airport", {}).get("iata", "Unknown")
                sched_arr = leg.get("arrival", {}).get("scheduledTime", {}).get("local", "N/A")
                status = leg.get("status", "Unknown")
                print(f"  -> Leg #{i+1}: {origin} -> {dest} | Arriving: {sched_arr} | Status: {status}")
        
    except Exception as e:
        print(f"An error occurred while making the network request: {e}")

if __name__ == "__main__":
    # ----------------------------------------------------------------
    # ENTER YOUR TROUBLESOME FLIGHT DETAILS HERE
    # ----------------------------------------------------------------
    TARGET_FLIGHT = "aa551" 
    TARGET_DATE = "2026-06-29"  # Use YYYY-MM-DD or MM-DD matching your manifest
    
    debug_date_flight_api(TARGET_FLIGHT, TARGET_DATE)