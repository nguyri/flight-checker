import csv
import json
import logging
import os
import re
import time
import pdfplumber
import requests
from pathlib import Path
from dotenv import load_dotenv

# Import our custom Stage 2 optimization algorithm
from optimize_pickups import build_pickup_groups
from cache import load_cache, save_cache, generate_shuttle_cache_key

# ----------------------------------------------------------------
# INITIALIZATION & LOGGING SETUP
# ----------------------------------------------------------------
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mute noisy font warnings from the PDF parser
logging.getLogger("pdfminer").setLevel(logging.ERROR)

# Dynamically adjust the log level based on environment settings
VERBOSE_LOGGING = os.environ.get("VERBOSE_LOGGING", "True").lower() in ("true", "1", "yes")
logger.setLevel(logging.DEBUG if VERBOSE_LOGGING else logging.INFO)

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")
INPUT_PDF = os.environ.get("INPUT_PDF", "flights-1.pdf")
OUTPUT_CSV = os.environ.get("OUTPUT_CSV", "flights_output.csv")
PARSE_CSV = os.environ.get("PARSE_CSV", "parse_output.csv")
CACHE_FILE = "flight_cache.json"
ARRIVAL_IATA_CODE = os.environ.get("ARRIVAL_IATA_CODE", "YYC")
MANIFEST_DATE = None
USE_CACHE = True

if not RAPIDAPI_KEY:
    raise ValueError("CRITICAL ERROR: RAPIDAPI_KEY is missing from environment variables!")


# ----------------------------------------------------------------
# DATA FORMATTING & PARSING HELPERS
# ----------------------------------------------------------------
def normalize_date_for_api(raw_date_str):
    """Ensures whatever date string we found matches the YYYY-MM-DD required by AeroDataBox."""
    if not raw_date_str:
        return ""
    
    cleaned = str(raw_date_str).strip().replace("/", "-")
    
    # If the date is already in standard YYYY-MM-DD, return it
    if re.match(r'^\d{4}-\d{2}-\d{2}$', cleaned):
        return cleaned
        
    # If the date is MM-DD (e.g. 06-29), automatically match it against the operational year 2026
    if re.match(r'^\d{2}-\d{2}$', cleaned):
        return f"2026-{cleaned}"
        
    return cleaned

def extract_full_flight_code(cell_text):
    """
    Parses raw text to extract flight codes, handling both '航班:' and '航班号:'.
    Returns the flight code in uppercase, or None if not found.
    """
    if not cell_text or not isinstance(cell_text, str):
        return None
    print(cell_text)

    # Regex breakdown:
    # 1. (?:航班号|航班) - Non-capturing group for the keywords
    # 2. :\s* - Matches the colon and optional following spaces
    # 3. ([A-Za-z0-9]+) - Capture group for the alphanumeric flight code
    pattern = r'(?:航班号|航班):\s*([A-Za-z0-9]+)'
    
    match = re.search(pattern, cell_text)
    
    if match:
        return match.group(1).upper()
    
    # Optional: Log a warning only if you expected a code but didn't find one
    # You can customize this condition based on your data quality needs
    if "航班" in cell_text:
        logging.warning(f"Keyword '航班' found, but no valid code extracted from: '{cell_text}'")
    
    return None

def format_timezone_offset(time_str):
    """Maps ISO timezone offsets (+00:00, -06:00) to clear text acronyms."""
    if not time_str or time_str == "N/A":
        return "N/A"
        
    cleaned = time_str.split(".")[0].replace("T", " ")
    tz_mapping = {
        "-04:00": "EDT", "-05:00": "EST/CDT", "-06:00": "MDT/CST",
        "-07:00": "MST/PDT", "-08:00": "PST", "Z": "UTC", "+00:00": "UTC"
    }
    
    for offset, abbreviation in tz_mapping.items():
        if offset in cleaned:
            return cleaned.replace(offset, f" {abbreviation}")
    return cleaned[:16]

def find_manifest_date(data_rows, flt_info_idx):
    """Scans the data rows to extract the manifest date ONCE."""
    global MANIFEST_DATE
    
    for row in data_rows:
        if len(row) <= flt_info_idx or not row[flt_info_idx]:
            continue
            
        text_str = str(row[flt_info_idx]).strip()
        
        # Look for standard YYYY-MM-DD or MM-DD patterns
        date_match = re.search(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2})', text_str)
        if date_match:
            MANIFEST_DATE = date_match.group(1).replace("/", "-")
            logger.info(f"[DATE DETECTED] Locked target manifest date: {MANIFEST_DATE}")
            return
            
        # Fallback for word-based months like '29-Jun'
        text_month_match = re.search(r'\d{1,2}[-\s][A-Za-z]{3}', text_str)
        if text_month_match:
            MANIFEST_DATE = text_month_match.group(0)
            logger.info(f"[DATE DETECTED] Locked target manifest date: {MANIFEST_DATE}")
            return
            
    logger.warning("[DATE WARNING] No operational date found in 'FLT Info'. Falling back to general tracking.")

def calculate_wait_time(arrival_text, pickup_text):
    """Computes delta duration (OP pickup time minus Arrival time) in minutes."""
    if not arrival_text or not pickup_text or "N/A" in arrival_text:
        return "N/A"
    try:
        arr_match = re.search(r'(\d{1,2}):(\d{2})', arrival_text)
        p_match = re.search(r'(\d{1,2}):(\d{2})', pickup_text)
        
        if arr_match and p_match:
            arr_mins = (int(arr_match.group(1)) * 60) + int(arr_match.group(2))
            p_mins = (int(p_match.group(1)) * 60) + int(p_match.group(2))
            
            delta_minutes = p_mins - arr_mins
            if delta_minutes < -600:  # Overnight wrap correction
                delta_minutes += 1440
            return f"{delta_minutes} min"
    except Exception:
        pass
    return "N/A"

# ----------------------------------------------------------------
# API CORE & INTELLIGENT SHUTTLE MATCHING
# ----------------------------------------------------------------
def pick_best_shuttle_leg(api_data_list, pdf_pickup_time_str):
    """
    Evaluates multi-leg raw payloads to isolate the leg arriving closest 
    to the target manifest pickup window.
    """
    if not api_data_list:
        return None
    if len(api_data_list) == 1:
        return api_data_list[0]
        
    p_match = re.search(r'(\d{1,2}):(\d{2})', str(pdf_pickup_time_str))
    if not p_match:
        return api_data_list[0]
        
    pdf_pickup_minutes = (int(p_match.group(1)) * 60) + int(p_match.group(2))
    best_match_leg = api_data_list[0]
    min_delta = float('inf')
    
    for leg in api_data_list:
        arrival_node = leg.get("arrival", {})
        arrival_local = arrival_node.get("scheduledTime", {}).get("local", "")
        dest_airport = arrival_node.get("airport", {}).get("iata", "UNK")
        
        # Matches times out of both standard spaces and 'T' delimiters (e.g., '2026-06-29 12:30-06:00')
        arr_match = re.search(r'[\sT](\d{2}):(\d{2})', arrival_local)
        
        if arr_match:
            api_arr_minutes = (int(arr_match.group(1)) * 60) + int(arr_match.group(2))
            delta = abs(pdf_pickup_minutes - api_arr_minutes)
            
            logger.info(f"[PROXIMITY EVAL] Destination: {dest_airport} | Arrives: {arr_match.group(1)}:{arr_match.group(2)} | Delta: {delta} mins")
            
            if delta < min_delta:
                min_delta = delta
                best_match_leg = leg
                
    logger.info(f"[MATCH LOCKED] Winner Destination: {best_match_leg.get('arrival', {}).get('airport', {}).get('iata')} landing at local time: {best_match_leg.get('arrival', {}).get('scheduledTime', {}).get('local')}")
    return best_match_leg

def fetch_live_flight_payload(flight_number):
    """Executes network requests routed completely through the api.market gateway structure."""
    logger.info(f"[API ROUTE] Querying api.market for flight: {flight_number}")
    
    time.sleep(1.5)
    url = f"https://prod.api.market/api/v1/aedbx/aerodatabox/flights/number/{flight_number}/{MANIFEST_DATE}"
    
    headers = {
        "x-api-market-key": RAPIDAPI_KEY
    }
    
    response = requests.get(url, headers=headers)
    if response.status_code == 204:
        return []
        
    response.raise_for_status()
    return response.json()
#rapid-api
# def fetch_live_flight_payload(flight_number):
#     """Executes network requests against the date-specific AeroDataBox API endpoint."""
#     global MANIFEST_DATE
#     target_date = normalize_date_for_api(MANIFEST_DATE)
    
#     headers = {"X-RapidAPI-Key": RAPIDAPI_KEY, "X-RapidAPI-Host": "aerodatabox.p.rapidapi.com"}
    
#     if target_date:
#         logger.info(f"[API ROUTE] Fetching {flight_number} specifically for date: {target_date}")
#         url = f"https://aerodatabox.p.rapidapi.com/flights/number/{flight_number}/{target_date}"
#     else:
#         logger.warning("[API ROUTE FALLBACK] No manifest date locked. Falling back to general flight loop.")
#         url = f"https://aerodatabox.p.rapidapi.com/flights/number/{flight_number}"
    
#     time.sleep(1)  # API Rate cushion
#     response = requests.get(url, headers=headers)
#     if response.status_code == 204:
#         return []
#     response.raise_for_status()
#     return response.json()

def get_flight_live_data(flight_number, pdf_pickup_time_str):
    if not flight_number:
        return "N/A", "N/A", "N/A"

    if USE_CACHE:
        flight_cache = load_cache(CACHE_FILE)
        cache_key = generate_shuttle_cache_key(flight_number, pdf_pickup_time_str, MANIFEST_DATE)
        if cache_key in flight_cache:
            logger.info(f"[CACHE HIT] Found stored data for {flight_number} ({cache_key}). Skipping API call.")
            cached = flight_cache[cache_key]
            return cached["status"], cached["origin"], cached["sched_arr"]
        else:
            logger.info(f"[CACHE MISS] No cached data for {flight_number} ({cache_key}). Querying api.market...")

    try:
        api_data = fetch_live_flight_payload(flight_number)
        if not api_data:
            return "No data found", "N/A", "N/A"

        # 1. Standardize the incoming API data array
        raw_legs = api_data if isinstance(api_data, list) else api_data.get("legs", [api_data])

        # 2. Filter down to legs matching your target destination (e.g., "Calgary" or "YYC")
        destination_matched_legs = []
        for leg in raw_legs:
            arrival_node = leg.get("arrival", {})
            dest_airport_name = arrival_node.get("airport", {}).get("name", "").upper()
            dest_airport_iata = arrival_node.get("airport", {}).get("iata", "").upper()
            dest_municipality = arrival_node.get("airport", {}).get("municipalityName", "").upper()

            if (ARRIVAL_IATA_CODE in dest_airport_name or 
                ARRIVAL_IATA_CODE in dest_airport_iata or 
                ARRIVAL_IATA_CODE in dest_municipality):
                destination_matched_legs.append(leg)

        # 3. SOFT ENFORCEMENT: Populate the row, but override variables if the city doesn't match
        if not destination_matched_legs:
            logger.warning(f"[ROUTE REJECTED] Flight {flight_number} lands in {raw_legs[0].get('arrival', {}).get('airport', {}).get('iata', 'UNK')} instead of {ARRIVAL_IATA_CODE}.")
            
            bad_leg = raw_legs[0]
            status = "Mismatch"
            origin = bad_leg.get("departure", {}).get("airport", {}).get("name", "Unknown").replace(" ", "\n")
            sched_arr = "INVALID\nDESTINATION"
            
            if USE_CACHE:
                flight_cache[cache_key] = {"status": status, "origin": origin, "sched_arr": sched_arr}
                save_cache(flight_cache, CACHE_FILE)
                
            return status, origin, sched_arr

        # 4. Route successfully filtered legs to your proximity scorer
        if len(destination_matched_legs) > 1:
            logger.info(f"[CONNECTING ROUTE] Found {len(destination_matched_legs)} target legs. Scoring proximity...")
            target_leg = pick_best_shuttle_leg(destination_matched_legs, pdf_pickup_time_str)
        else:
            target_leg = destination_matched_legs[0]

        # 5. EXTRACT AND RETURN VALUES (Ensure this block wasn't deleted!)
        status = target_leg.get("status", "Unknown")
        origin = target_leg.get("departure", {}).get("airport", {}).get("name", "Unknown").replace(" ", "\n")
        plain_sched_arr = target_leg.get("arrival", {}).get("scheduledTime", {}).get("local", "N/A")
        sched_arr = format_timezone_offset(plain_sched_arr).replace(" ", "\n")

        if USE_CACHE:
            flight_cache[cache_key] = {"status": status, "origin": origin, "sched_arr": sched_arr}
            save_cache(flight_cache, CACHE_FILE)
        
        return status, origin, sched_arr

    except Exception as e:
        logger.error(f"[FETCH FAILED] -> Error parsing flight {flight_number}: {e}")
        return f"Fetch Error: {str(e)}", "N/A", "N/A"    
# ----------------------------------------------------------------
# INDEX IDENTIFICATION & SCHEMA SETUP
# ----------------------------------------------------------------
def identify_column_indices(header_row):
    """Locates original structural indexes while cleaning newline text artifacts."""
    flt_info_index = None
    original_pickup_index = None
    
    for i, h in enumerate(header_row):
        if not h: continue
        clean_header = re.sub(r'[\s\-]', '', str(h)).upper()
        if "FLTINFO" in clean_header:
            flt_info_index = i
        if any(x in clean_header for x in ["PICKTIME", "PICKUP"]):
            original_pickup_index = i
            
    return flt_info_index, original_pickup_index

def inject_api_headers(header_row, flt_info_idx, original_pickup_idx):
    """Mutates structural headers to include newly integrated API metrics."""
    if original_pickup_idx is not None:
        header_row[original_pickup_idx] = "OP pickup time"
        
    header_row.insert(flt_info_idx + 1, "Flight Code")
    header_row.insert(flt_info_idx + 2, "Arrival")
    header_row.insert(flt_info_idx + 3, "Status")
    header_row.insert(flt_info_idx + 4, "Origin Airport")
    
    current_pickup_idx = original_pickup_idx + 4 if original_pickup_idx > flt_info_idx else original_pickup_idx
    if current_pickup_idx is not None:
        header_row.insert(current_pickup_idx + 1, "Wait time")
        
    return header_row

def verify_pipeline_integrity(extracted_rows_count, output_csv_path):
    """
    Compares total structured rows extracted from the source document 
    against actual logical rows saved in the final CSV output.
    """
    try:
        with open(output_csv_path, mode="r", encoding="utf-8", newline="") as f:
            # Use csv.reader so cells with internal \n are not counted as new lines
            reader = csv.reader(f)
            
            # Counts include the header
            csv_row_count = sum(1 for row in reader) 
            
        logger.info(f"[INTEGRITY CHECK] Source Records: {extracted_rows_count} | Destination CSV Rows: {csv_row_count}")
        
        if extracted_rows_count == csv_row_count:
            logger.info("✅ Integrity Check Passed: All records safely accounted for.")
            return True
        else:
            logger.error(f"❌ CRITICAL MISMATCH: Data variance detected! Source records: {extracted_rows_count}, CSV rows: {csv_row_count}")
            return False
            
    except Exception as e:
        logger.error(f"Could not complete integrity check: {e}")
        return False
    
def save_pipeline_to_csv(compiled_rows, output_csv_path):
    """Stage 2: Commits compiled data row arrays safely to disk as a CSV file."""
    if not compiled_rows:
        logger.error("CSV Output Stage aborted: No data rows found to write.")
        return False

    logger.info(f"Starting Stage 2: Exporting {len(compiled_rows) - 1} records to {output_csv_path}...")
    
    try:
        # Path normalization ensures directories exist if using nested folders
        csv_file = Path(output_csv_path)
        csv_file.parent.mkdir(parents=True, exist_ok=True)

        with csv_file.open(mode="w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(compiled_rows)
            
        logger.info(f"✅ CSV Output Stage Complete! File saved successfully.")
        return True
        
    except IOError as e:
        logger.error(f"❌ Storage write failure on {output_csv_path}: {e}")
        return False
# ----------------------------------------------------------------
# EXECUTION STAGES
# ----------------------------------------------------------------
def run_extraction_pipeline(pdf_path=None, target_iata=None):
    """
    STAGE 1: Parses PDF data and matches live flight info via api.market.
    Accepts explicit file paths and target IATA codes dynamically.
    """
    # Fall back to environment variable if no parameter is explicitly passed
    source_pdf = pdf_path if pdf_path else INPUT_PDF
    
    # Safely override the global target destination if provided by the web UI
    global ARRIVAL_IATA_CODE
    if target_iata:
        ARRIVAL_IATA_CODE = target_iata.strip().upper()

    print(f"Starting Stage 1: Parsing PDF data from {source_pdf}...")
    all_rows = []
    flt_info_idx, original_pickup_idx = None, None
    
    try:
        with pdfplumber.open(source_pdf) as pdf:
            for page_num, page in enumerate(pdf.pages):
                table = page.extract_table(table_settings={
                    "horizontal_strategy": "text",
                    "vertical_strategy": "text",
                    "keep_blank_chars": True,
                    "snap_tolerance": 10 
                })
                if not table: continue
                
                if page_num == 0:
                    header = table[0]
                    flt_info_idx, original_pickup_idx = identify_column_indices(header)
                    if flt_info_idx is None:
                        print("Error: Could not find 'FLT Info' column.")
                        return []
                        
                    header = inject_api_headers(header, flt_info_idx, original_pickup_idx)
                    all_rows.append(header)
                    data_rows = table[1:]
                    find_manifest_date(data_rows, flt_info_idx)
                else:
                    data_rows = table

                for row in data_rows:
                    if len(row) > flt_info_idx:
                        flight_code = extract_full_flight_code(row[flt_info_idx])
                        
                        row_pickup_idx = original_pickup_idx + 4 if (original_pickup_idx and original_pickup_idx > flt_info_idx) else original_pickup_idx
                        pickup_val = row[row_pickup_idx] if row_pickup_idx is not None else ""
                        
                        status, origin, arr_time = get_flight_live_data(flight_code, pickup_val)
                        
                        row.insert(flt_info_idx + 1, flight_code)
                        row.insert(flt_info_idx + 2, arr_time)   
                        row.insert(flt_info_idx + 3, status)
                        row.insert(flt_info_idx + 4, origin)
                        
                        if row_pickup_idx is not None:
                            row_pickup_idx = original_pickup_idx + 4 if original_pickup_idx > flt_info_idx else original_pickup_idx
                            if "INVALID" in str(arr_time) or status == "Mismatch":
                                wait_time_val = "N/A"
                            else:
                                wait_time_val = calculate_wait_time(arr_time, row[row_pickup_idx])
                                
                            row.insert(row_pickup_idx + 1, wait_time_val)
                    all_rows.append(row)
                    
        return all_rows
    except Exception as e:
        logger.error(f"Pipeline failure: {e}")
        return []


def run_optimization_pipeline(processed_rows, max_wait_hours=2):
    """
    STAGE 2: Evaluates windowing constraints and exports grouped manifest.
    Accepts variable max_wait_hours thresholds dynamically from the web frontend.
    """
    if not processed_rows or len(processed_rows) <= 1:
        print("No active datasets passed down to run optimization groupings.")
        return []
        
    print("\nStarting Stage 2: Grouping passenger schedules...")
    
    # Deep copy the array structure to prevent mutational drift back in Stage 1 records
    import copy
    header = copy.deepcopy(processed_rows[0])
    data_rows = copy.deepcopy(processed_rows[1:])
    
    try:
        # Search the header to find where the arrival time cell lives dynamically
        arrival_idx = next(i for i, h in enumerate(header) if h and "ARRIVAL" in str(h).upper())
    except StopIteration:
        print("Structural Mapping Error: Missing active 'Arrival' field definitions.")
        return []

    # Run the window tracking algorithm
    groups = build_pickup_groups(data_rows, arrival_idx, max_wait_hours=max_wait_hours)
    
    header.insert(0, "Pickup Group ID")
    header.insert(1, "Target Vehicle Dispatch")
    final_output_rows = [header]
    
    for group_id, group_meta in enumerate(groups, start=1):
        if group_meta.get("is_valid", True):
            group_name = f"Group #{group_id}"
            dispatch_str = group_meta["dispatch_time"].strftime("%Y-%m-%d %H:%M")
        else:
            group_name = "MANUAL REVIEW"
            dispatch_str = "N/A - Review Flight"

        for row in group_meta["flights"]:
            row.insert(0, group_name)
            row.insert(1, dispatch_str)
            final_output_rows.append(row)
            
    return final_output_rows
    """STAGE 2: Evaluates windowing constraints and exports grouped manifest."""
    if not processed_rows or len(processed_rows) <= 1:
        print("No active datasets passed down to run optimization groupings.")
        return
        
    print("\nStarting Stage 2: Grouping passenger schedules...")
    header = processed_rows[0]
    data_rows = processed_rows[1:]
    
    try:
        arrival_idx = next(i for i, h in enumerate(header) if h and "ARRIVAL" in str(h).upper())
    except StopIteration:
        print("Structural Mapping Error: Missing active 'Arrival' field definitions.")
        return

    # Call out to the algorithm engine file
    groups = build_pickup_groups(data_rows, arrival_idx, max_wait_hours=2)
    
    header.insert(0, "Pickup Group ID")
    header.insert(1, "Target Vehicle Dispatch")
    final_output_rows = [header]
    
    for group_id, group_meta in enumerate(groups, start=1):
        # Gracefully assign names based on whether the data is valid or unassigned
        if group_meta.get("is_valid", True):
            group_name = f"Group #{group_id}"
            dispatch_str = group_meta["dispatch_time"].strftime("%Y-%m-%d %H:%M")
        else:
            group_name = "MANUAL REVIEW"
            dispatch_str = "N/A - Review Flight"

        for row in group_meta["flights"]:
            row.insert(0, group_name)
            row.insert(1, dispatch_str)
            final_output_rows.append(row)
    return final_output_rows

# ----------------------------------------------------------------
# SYSTEM ENTRY LEVEL CONTROLLER
# ----------------------------------------------------------------
if __name__ == "__main__":
    extracted_data = run_extraction_pipeline()
    
    if extracted_data:
        save_pipeline_to_csv(extracted_data, PARSE_CSV)
        
        total_source_records = len(extracted_data) 
        verify_pipeline_integrity(total_source_records, PARSE_CSV)

        optimized_data = run_optimization_pipeline(extracted_data)
        
        if optimized_data:
            save_pipeline_to_csv(optimized_data, OUTPUT_CSV)
            verify_pipeline_integrity(total_source_records, OUTPUT_CSV)