import csv
import re
import time
import pdfplumber
import requests
import os
from datetime import datetime
from dotenv import load_dotenv
from optimize_pickups import build_pickup_groups, parse_flight_time
from cache import load_cache, save_cache

# ----------------------------------------------------------------
# CONFIGURATION:
# ----------------------------------------------------------------

load_dotenv()

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")
INPUT_PDF = os.environ.get("INPUT_PDF", "flights-1.pdf")
OUTPUT_CSV = os.environ.get("OUTPUT_CSV", "flights_output.csv")

if not RAPIDAPI_KEY:
    raise ValueError("CRITICAL ERROR: RAPIDAPI_KEY is missing from the environment variables!")


# ----------------------------------------------------------------
# STEP 1: Extract Flight Codes from PDF
# ----------------------------------------------------------------
def extract_full_flight_code(cell_text):
    if not cell_text:
        return ""
    match_chinese = re.search(r'航班号:\s*([A-Za-z0-9]+)', str(cell_text))
    if match_chinese:
        return match_chinese.group(1).upper()
    match_standard = re.search(r'([A-Za-z]{2,3}\d+)', str(cell_text))
    if match_standard:
        return match_standard.group(1).upper()
    return ""

# ----------------------------------------------------------------
# STEP 2: Fetch Live Status & Arrival Time from API
# ----------------------------------------------------------------
def get_flight_live_data(flight_number):
    if not flight_number:
        return "N/A", "N/A", "N/A"

    # 1. Load your local persistent cache
    flight_cache = load_cache()

    # 2. Check if we already have this flight stored locally
    if flight_number in flight_cache:
        print(f"-> [CACHE HIT] Loading data for {flight_number} from local cache.")
        cached_data = flight_cache[flight_number]
        return cached_data["status"], cached_data["origin"], cached_data["sched_arr"]

    # 3. Cache Miss: We need to hit the real AeroDataBox API
    print(f"-> [CACHE MISS] Fetching fresh data from API for {flight_number}...")
    url = f"https://aerodatabox.p.rapidapi.com/flights/number/{flight_number}"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "aerodatabox.p.rapidapi.com"
    }
    
    try:
        time.sleep(1) # Cushion API rate limits
        response = requests.get(url, headers=headers)
        
        if response.status_code == 204:
            status, origin, sched_arr = "No data found", "N/A", "N/A"
        elif response.status_code != 200:
            return f"API Error ({response.status_code})", "N/A", "N/A"
        else:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                latest_flight = data[0]
                status = latest_flight.get("status", "Unknown")
                
                departure = latest_flight.get("departure", {})
                origin = departure.get("airport", {}).get("name", "Unknown").replace(" ", "\n")
                
                arrival = latest_flight.get("arrival", {})
                plain_sched_arr = arrival.get("scheduledTime", {}).get("local", "N/A")
                sched_arr = format_timezone_offset(plain_sched_arr).replace(" ", "\n")
            else:
                status, origin, sched_arr = "No Data", "N/A", "N/A"
                
        # 4. Save the successful result to our cache dictionary so we have it next time
        flight_cache[flight_number] = {
            "status": status,
            "origin": origin,
            "sched_arr": sched_arr,
            "timestamp": time.time() # Optional tracking metric
        }
        save_cache(flight_cache)
        
        return status, origin, sched_arr
            
    except Exception as e:
        return f"Fetch Error: {str(e)}", "N/A", "N/A"

def format_timezone_offset(time_str):
    if not time_str or time_str == "N/A":
        return "N/A"
        
    cleaned = time_str.split(".")[0].replace("T", " ")
    
    tz_mapping = {
        "-04:00": "EDT",
        "-05:00": "EST/CDT",
        "-06:00": "MDT/CST", 
        "-07:00": "MST/PDT",
        "-08:00": "PST",
        "Z": "UTC",
        "+00:00": "UTC"
    }
    
    for offset, abbreviation in tz_mapping.items():
        if offset in cleaned:
            return cleaned.replace(offset, f" {abbreviation}")
            
    return cleaned[:16]

# ----------------------------------------------------------------
# HELPER: Calculate time delta between Arrival and Pick-up time
# ----------------------------------------------------------------
def calculate_wait_time(arrival_text, pickup_text):
    """
    Parses timestamps and returns the difference (Wait Time) in minutes.
    Formated as 'X min'.
    """
    if not arrival_text or not pickup_text or "N/A" in arrival_text:
        return "N/A"
    
    try:
        # Extract HH:MM from the Arrival text (ignoring newlines and timezone suffixes)
        # Matches format like 11:36
        arr_time_match = re.search(r'(\d{1,2}):(\d{2})', arrival_text)
        pUp_time_match = re.search(r'(\d{1,2}):(\d{2})', pickup_text)
        
        if arr_time_match and pUp_time_match:
            arr_hours, arr_mins = map(int, arr_time_match.groups())
            pUp_hours, pUp_mins = map(int, pUp_time_match.groups())
            
            # Convert both to absolute minutes from start of day
            total_arrival_minutes = (arr_hours * 60) + arr_mins
            total_pickup_minutes = (pUp_hours * 60) + pUp_mins
            
            # OP pickup time minus arrival time
            delta_minutes = total_pickup_minutes - total_arrival_minutes
            
            # Handle possible overnight wraps gracefully
            if delta_minutes < -600: 
                delta_minutes += 1440
                
            return f"{delta_minutes} min"
    except Exception:
        pass
        
    return "N/A"

# ----------------------------------------------------------------
# STEP 3: Core Pipeline Execution
# ----------------------------------------------------------------
def run_extraction_pipeline():
    print(f"Opening {INPUT_PDF}...")
    all_rows = []
    
    flt_info_index = None
    original_pickup_index = None
    
    try:
        with pdfplumber.open(INPUT_PDF) as pdf:
            for page_num, page in enumerate(pdf.pages):
                table = page.extract_table()
                if not table:
                    continue
                
                if page_num == 0:
                    header = table[0]
                    
                    try:
                        # Normalize headers by converting to uppercase and stripping ALL spaces/newlines
                        # This turns "Pick\nTime", "Pick Time", or "pick-time" into "PICKTIME"
                        flt_info_index = next(
                            i for i, h in enumerate(header) 
                            if h and "FLTINFO" in re.sub(r'[\s\-]', '', str(h)).upper()
                        )
                    except StopIteration:
                        print("Error: Could not find 'FLT Info' column.")
                        return
                        
                    try:
                        # This will now successfully match "Pick\nTime", "Pick Time", "Pick-up Time", etc.
                        original_pickup_index = next(
                            i for i, h in enumerate(header) 
                            if h and any(x in re.sub(r'[\s\-]', '', str(h)).upper() for x in ["PICKTIME", "PICKUP"])
                        )
                        # Clean up the label entirely in the final output CSV
                        header[original_pickup_index] = "OP\npick\ntime"
                    except StopIteration:
                        print("Warning: Could not find a 'Pick Time' column to rename.")

                    # 2. Add API columns immediately next to FLT INFO
                    header.insert(flt_info_index + 1, "Flight Code")
                    header.insert(flt_info_index + 2, "Arrival")
                    header.insert(flt_info_index + 3, "Status")
                    header.insert(flt_info_index + 4, "Origin Airport")
                    
                    # Adjust pickup index position if it sat to the right of FLT INFO
                    if original_pickup_index is not None and original_pickup_index > flt_info_index:
                        current_pickup_index = original_pickup_index + 4
                    else:
                        current_pickup_index = original_pickup_index
                        
                    # 3. Add the Wait Time column header directly after OP pickup time
                    if current_pickup_index is not None:
                        header.insert(current_pickup_index + 1, "Wait time")
                        
                    all_rows.append(header)
                    data_rows = table[1:]
                else:
                    data_rows = table

                for row in data_rows:
                    if flt_info_index is not None and len(row) > flt_info_index:
                        flt_info_data = row[flt_info_index]
                        flight_code = extract_full_flight_code(flt_info_data)
                        
                        print(f"Checking API for Flight: {flight_code if flight_code else 'Empty Row'}...")
                        status, origin, arr_time = get_flight_live_data(flight_code)
                        
                        # Sequential insertions for flight info
                        row.insert(flt_info_index + 1, flight_code)
                        row.insert(flt_info_index + 2, arr_time)   
                        row.insert(flt_info_index + 3, status)
                        row.insert(flt_info_index + 4, origin)
                        
                        # Recalculate where pickup data lives now after insertions
                        if original_pickup_index is not None and original_pickup_index > flt_info_index:
                            row_pickup_index = original_pickup_index + 4
                        else:
                            row_pickup_index = original_pickup_index
                            
                        # Calculate and inject wait time
                        if row_pickup_index is not None and len(row) > row_pickup_index:
                            pickup_val = row[row_pickup_index]
                            wait_time_val = calculate_wait_time(arr_time, pickup_val)
                            row.insert(row_pickup_index + 1, wait_time_val)
                    
                    all_rows.append(row)

            # Save data to CSV
            if all_rows:
                with open(OUTPUT_CSV, mode="w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerows(all_rows)
                print(f"\nPipeline complete! Streamlined results saved to: {OUTPUT_CSV}")
                return all_rows
            else:
                print("No data processed.")
                return []

    except FileNotFoundError:
        print(f"Error: PDF '{INPUT_PDF}' not found.")

def run_optimization_pipeline(processed_rows):
    if not processed_rows or len(processed_rows) <= 1:
        print("No rows to optimize.")
        return
        
    header = processed_rows[0]
    data_rows = processed_rows[1:]
    
    # 1. Dynamically locate where the 'Arrival' data index is
    try:
        arrival_idx = next(i for i, h in enumerate(header) if h and "ARRIVAL" in str(h).upper())
    except StopIteration:
        print("Error: Could not find 'Arrival' column for time math.")
        return

    # 2. Run your grouping logic (from the previous response)
    groups = build_pickup_groups(data_rows, arrival_idx, max_wait_hours=2)
    
    # 3. Add Tracking Columns to the CSV header
    header.insert(0, "Pickup Group ID")
    header.insert(1, "Target Vehicle Dispatch")
    
    final_output_rows = [header]
    
    # 4. Flatten the groups back into row format
    for group_id, group_meta in enumerate(groups, start=1):
        dispatch_str = group_meta["dispatch_time"].strftime("%Y-%m-%d %H:%M")
        for row in group_meta["flights"]:
            row.insert(0, f"Group #{group_id}")
            row.insert(1, dispatch_str)
            final_output_rows.append(row)
            
    # 5. Write the final optimized spreadsheet to disk
    with open(OUTPUT_CSV, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(final_output_rows)
    print(f"\nSuccess! Optimized manifest saved to: {OUTPUT_CSV}")

if __name__ == "__main__":
    # Execution Block
    # Step 1: Extract and Fetch (Hits the PDF and API once)
    extracted_data = run_extraction_pipeline()
    
    # Step 2: Optimize and Sort (Pure local Python math)
    run_optimization_pipeline(extracted_data)