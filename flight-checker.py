import csv
import re
import time
import pdfplumber
import requests
import os
from dotenv import load_dotenv

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
    """
    Calls the AeroDataBox API.
    Returns only: (Status, Origin, Sched Arrival)
    """
    if not flight_number:
        return "N/A", "N/A", "N/A"

    url = f"https://aerodatabox.p.rapidapi.com/flights/number/{flight_number}"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "aerodatabox.p.rapidapi.com"
    }
    
    try:
        # Rate-limiting cushion for the RapidAPI tier
        time.sleep(1) 
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 204:
            return "No data found", "N/A", "N/A"
        elif response.status_code != 200:
            return f"API Error ({response.status_code})", "N/A", "N/A"
            
        data = response.json()
        
        if isinstance(data, list) and len(data) > 0:
            latest_flight = data[0]
            status = latest_flight.get("status", "Unknown")
            
            # Extract Origin (Departure Airport)
            departure = latest_flight.get("departure", {})
            origin = departure.get("airport", {}).get("name", "Unknown")
            origin = origin.replace(" ", "\n")
            
            # Extract Scheduled Arrival Time
            arrival = latest_flight.get("arrival", {})
            plain_sched_arr = arrival.get("scheduledTime", {}).get("local", "N/A")
            sched_arr = format_timezone_offset(plain_sched_arr)
            sched_arr = sched_arr.replace(" ", "\n")
                
            return status, origin, sched_arr
            
    except Exception as e:
        return f"Fetch Error: {str(e)}", "N/A", "N/A"
        
    return "No Data", "N/A", "N/A"

def format_timezone_offset(time_str):
    if not time_str or time_str == "N/A":
        return "N/A"
        
    # Clean up standard characters first: '2026-06-28T11:36:00-06:00' -> '2026-06-28 11:36:00-06:00'
    cleaned = time_str.split(".")[0].replace("T", " ")
    
    # A mapping dictionary for common North American / Global offsets
    # (Adjust abbreviations based on your current season/needs)
    tz_mapping = {
        "-04:00": "EDT",
        "-05:00": "EST/CDT",
        "-06:00": "MDT/CST", # Currently -06:00 in Summer is MDT or CST
        "-07:00": "MST/PDT",
        "-08:00": "PST",
        "Z": "UTC",
        "+00:00": "UTC"
    }
    
    # Scan the string for any matching numerical offset key
    for offset, abbreviation in tz_mapping.items():
        if offset in cleaned:
            # Swap out the numeric suffix with the text acronym
            return cleaned.replace(offset, f" {abbreviation}")
            
    # Fallback if the offset isn't in our dictionary (just drops the characters)
    return cleaned[:16]
# ----------------------------------------------------------------
# STEP 3: Core Pipeline Execution
# ----------------------------------------------------------------
def run_pipeline():
    print(f"Opening {INPUT_PDF}...")
    all_rows = []
    flt_info_index = None
    
    try:
        with pdfplumber.open(INPUT_PDF) as pdf:
            for page_num, page in enumerate(pdf.pages):
                table = page.extract_table()
                if not table:
                    continue
                
                if page_num == 0:
                    header = table[0]
                    try:
                        flt_info_index = [h.strip().upper() for h in header if h].index("FLT INFO")
                        
                        # Add headers sequentially right next to FLT INFO
                        header.insert(flt_info_index + 1, "Flight Code")
                        header.insert(flt_info_index + 2, "Arrival")  # <-- Moved next to code
                        header.insert(flt_info_index + 3, "Status")
                        header.insert(flt_info_index + 4, "Origin Airport")
                        all_rows.append(header)
                        
                        data_rows = table[1:]
                    except ValueError:
                        print("Error: Could not find 'FLT Info' column.")
                        return
                else:
                    data_rows = table

                for row in data_rows:
                    if flt_info_index is not None and len(row) > flt_info_index:
                        flt_info_data = row[flt_info_index]
                        flight_code = extract_full_flight_code(flt_info_data)
                        
                        print(f"Checking API for Flight: {flight_code if flight_code else 'Empty Row'}...")
                        status, origin, arr_time = get_flight_live_data(flight_code)
                        
                        # Sequential injection order matching our new header structure
                        row.insert(flt_info_index + 1, flight_code)
                        row.insert(flt_info_index + 2, arr_time)   # <-- Swapped position
                        row.insert(flt_info_index + 3, status)
                        row.insert(flt_info_index + 4, origin)
                    
                    all_rows.append(row)

            # Save data to CSV
            if all_rows:
                with open(OUTPUT_CSV, mode="w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerows(all_rows)
                print(f"\nPipeline complete! Streamlined results saved to: {OUTPUT_CSV}")
            else:
                print("No data processed.")

    except FileNotFoundError:
        print(f"Error: PDF '{INPUT_PDF}' not found.")

if __name__ == "__main__":
    if RAPIDAPI_KEY == "YOUR_RAPIDAPI_KEY_HERE":
        print("Please replace 'YOUR_RAPIDAPI_KEY_HERE' with your actual key from the RapidAPI Dashboard.")
    else:
        run_pipeline()