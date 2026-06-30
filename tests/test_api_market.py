import os
import json
import requests
from dotenv import load_dotenv
import pytest

# Load environment variables from your .env file
load_dotenv()

# Note: Ensure this environment variable contains your api.market token string!
API_MARKET_KEY = os.environ.get("RAPIDAPI_KEY") 

@pytest.mark.skip(reason="Temporarily disabling due to API rate limit")
def test_single_market_call(flight_number, target_date):
    if not API_MARKET_KEY:
        print("CRITICAL ERROR: API Key token not found. Please check your .env file setup.")
        return

    print("================================================================")
    print(f"CONNECTING TO GATEWAY: api.market")
    print(f"TARGET QUERY       : Flight {flight_number} on {target_date}")
    print("================================================================")
    
    # Correctly route to the api.market base URL proxy string
    url = f"https://prod.api.market/api/v1/aedbx/aerodatabox/flights/number/{flight_number}/{target_date}"
    
    # Headers required explicitly by api.market
    headers = {
        "x-api-market-key": API_MARKET_KEY
    }
    
    try:
        response = requests.get(url, headers=headers)
        print(f"HTTP Status Code: {response.status_code}")
        
        if response.status_code == 401:
            print("\n❌ 401 UNAUTHORIZED: Your api.market token is either missing, invalid, or mismatched.")
            return
        elif response.status_code == 204:
            print(f"\nℹ️ 204 NO CONTENT: No flight history schedules found for {flight_number} on {target_date}.")
            return
        elif response.status_code != 200:
            print(f"\n❌ ERROR RESPONSE: {response.text}")
            return
            
        # Parse and print formatted JSON raw payload
        data = response.json()
        print("\n=== RAW API.MARKET RESPONSE DATA ===")
        print(json.dumps(data, indent=4, ensure_ascii=False))
        print("======================================\n")
        
        # Quick data structure map
        if isinstance(data, list):
            print(f"Structure verification: Returned a flat list containing {len(data)} leg(s).")
            for i, leg in enumerate(data):
                origin = leg.get("departure", {}).get("airport", {}).get("iata", "???")
                dest = leg.get("arrival", {}).get("airport", {}).get("iata", "???")
                local_arr = leg.get("arrival", {}).get("scheduledTime", {}).get("local", "N/A")
                print(f"  -> Leg #{i+1}: {origin} ➔ {dest} | Arriving (Local): {local_arr}")
        else:
            print("Structure verification: Payload returned as a single Dictionary object block.")

    except Exception as e:
        print(f"An unexpected script exception occurred: {e}")

if __name__ == "__main__":
    # Change these test parameters to whatever you want to verify!
    TEST_FLIGHT = "AA551"
    TEST_DATE = "2026-06-29"
    
    test_single_market_call(TEST_FLIGHT, TEST_DATE)