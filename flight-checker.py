import csv
import re
import time
import pdfplumber
import requests

# ----------------------------------------------------------------
# CONFIGURATION: Put your RapidAPI Key here
# ----------------------------------------------------------------
RAPIDAPI_KEY = "9ef7e6d5afmsh50bd8a9d26d2414p157394jsn456b7eace520"
INPUT_PDF = "flights-1.pdf"
OUTPUT_CSV = "flights_with_live_status.csv"

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
# STEP 2: Fetch Live Status & Arrival/Departure Times from API
# ----------------------------------------------------------------
def get_flight_live_data(flight_number):
    """
    Calls the AeroDataBox 'Search flights by number' endpoint.
    Returns: (Status, Origin, Destination, Sched Departure, Sched Arrival)
    """
    if not flight_number:
        return "N/A", "N/A", "N/A", "N/A", "N/A"

    url = f"https://aerodatabox.p.rapidapi.com/flights/number/{flight_number}"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "aerodatabox.p.rapidapi.com"
    }
    
    try:
        # Respect API free tier limits by adding a short delay
        time.sleep(1) 
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 204:
            return "No data found", "N/A", "N/A", "N/A", "N/A"
        elif response.status_code != 200:
            return f"API Error ({response.status_code})", "N/A", "N/A", "N/A", "N/A"
            
        data = response.json()
        
        if isinstance(data, list) and len(data) > 0:
            latest_flight = data[0]
            status = latest_flight.get("status", "Unknown")
            
            # Extract Departure Information
            departure = latest_flight.get("departure", {})
            origin = departure.get("airport", {}).get("name", "Unknown")
            sched_dep = departure.get("scheduledTime", {}).get("local", "N/A")
            
            # Extract Arrival Information
            arrival = latest_flight.get("arrival", {})
            destination = arrival.get("airport", {}).get("name", "Unknown")
            sched_arr = arrival.get("scheduledTime", {}).get("local", "N/A")
            
            # Clean up the timestamps to look nicer: '2026-10-24T14:30:00' -> '2026-10-24 14:30:00'
            if sched_dep != "N/A":
                sched_dep = sched_dep.split(".")[0].replace("T", " ")
            if sched_arr != "N/A":
                sched_arr = sched_arr.split(".")[0].replace("T", " ")
                
            return status, origin, destination, sched_dep, sched_arr
            
    except Exception as e:
        return f"Fetch Error: {str(e)}", "N/A", "N/A", "N/A", "N/A"
        
    return "No Data", "N/A", "N/A", "N/A", "N/A"

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
                        
                        # Add the Scheduled Arrival column header right after Scheduled Departure
                        header.insert(flt_info_index + 1, "Extracted Flight Code")
                        header.insert(flt_info_index + 2, "Live Status")
                        header.insert(flt_info_index + 3, "Origin Airport")
                        header.insert(flt_info_index + 4, "Destination Airport")
                        header.insert(flt_info_index + 5, "Scheduled Departure")
                        header.insert(flt_info_index + 6, "Scheduled Arrival")  # <-- NEW COLUMN
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
                        status, origin, dest, dep_time, arr_time = get_flight_live_data(flight_code)
                        
                        # Sequentially insert everything right next to FLT Info
                        row.insert(flt_info_index + 1, flight_code)
                        row.insert(flt_info_index + 2, status)
                        row.insert(flt_info_index + 3, origin)
                        row.insert(flt_info_index + 4, dest)
                        row.insert(flt_info_index + 5, dep_time)
                        row.insert(flt_info_index + 6, arr_time)  # <-- NEW VALUE
                    
                    all_rows.append(row)

            # Save data to CSV
            if all_rows:
                with open(OUTPUT_CSV, mode="w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerows(all_rows)
                print(f"\nPipeline complete! Results saved to: {OUTPUT_CSV}")
            else:
                print("No data processed.")

    except FileNotFoundError:
        print(f"Error: PDF '{INPUT_PDF}' not found.")

if __name__ == "__main__":
    if RAPIDAPI_KEY == "YOUR_RAPIDAPI_KEY_HERE":
        print("Please replace 'YOUR_RAPIDAPI_KEY_HERE' with your actual key from the RapidAPI Dashboard.")
    else:
        run_pipeline()