import csv
import re
from datetime import datetime, timedelta
import copy

def parse_flight_time(time_str):
    """
    Parses cleaned datetime string (e.g., '2026-06-28 11:36 MDT') 
    ignoring newlines or timezone strings for absolute delta math.
    """
    if not time_str or "N/A" in time_str:
        return None
    try:
        clean_str = time_str.replace("\n", " ").strip()
        base_time = " ".join(clean_str.split()[:2])
        return datetime.strptime(base_time, "%Y-%m-%d %H:%M")
    except Exception:
        return None

def is_international_flight(row, origin_index):
    """
    Flags flights as international if their origin is outside Canada and the US.
    Treats major Canadian airports as domestic.
    """
    origin_text = str(row[origin_index]).strip().upper()
    
    # 1. Explicitly track domestic/transborder airport IATA codes
    domestic_airports = {
        # Canadian Hubs
        "YYC", "YVR", "YUL", "YYZ", "YEG", "YOW", "YWG", "YHZ",
    }
    
    # 2. Check if an explicit IATA code is present in the origin text
    for iata in domestic_airports:
        if iata in origin_text:
            return False  # It's domestic / transborder (30-min clearing window)
            
    # 3. Fallback broad string keywords
    broad_domestic_keywords = ["CANADA", "USA", "UNITED STATES"]
    if any(keyword in origin_text for keyword in broad_domestic_keywords):
        return False

    return True  # Otherwise, treat as international (1-hour customs window)


def get_passenger_count(row, header):
    """
    Looks up the 'No.' or 'AGE' column to count passengers.
    Counts the number of comma-separated items. Fallback to 1 if empty/unparseable.
    """
    try:
        # Find the column index for "No."
        no_idx = next(i for i, h in enumerate(header) if h and "NO." in str(h).upper())
        val = str(row[no_idx]).strip()
        if val and val != "N/A":
            return len([item for item in val.split(",") if item.strip()])
    except StopIteration:
        pass
        
    try:
        # Fallback to "AGE" column index if "No." isn't found
        age_idx = next(i for i, h in enumerate(header) if h and "AGE" in str(h).upper())
        val = str(row[age_idx]).strip()
        if val and val != "N/A":
            return len([item for item in val.split(",") if item.strip()])
    except StopIteration:
        pass

    print("Warning: Passenger count columns missing; defaulting to 1 passenger per row.")
    return 1 # Baseline fallback if columns are missing

def build_pickup_groups(processed_rows, header, arrival_index, origin_index, max_wait_hours=2, max_capacity=10):
    """
    Groups flights together while tracking precise passenger volume. 
    Splits multi-passenger rows safely across vehicles if a capacity boundary is hit.
    """
    valid_data_rows = []
    unassigned_rows = []
    
    for row in processed_rows:
        arr_dt = parse_flight_time(row[arrival_index])
        if arr_dt:
            if is_international_flight(row, origin_index):
                ready_dt = arr_dt + timedelta(minutes=60)
            else:
                ready_dt = arr_dt + timedelta(minutes=30)
            p_count = get_passenger_count(row, header)
            valid_data_rows.append((ready_dt, p_count, row))
        else:
            unassigned_rows.append(row)
            
    valid_data_rows.sort(key=lambda x: x[0])
    
    optimized_groups = []
    current_group = []
    current_capacity = 0
    group_anchor_time = None
    max_wait_delta = timedelta(hours=max_wait_hours)
    
    for ready_dt, p_count, row in valid_data_rows:
        if not current_group:
            current_group = [row]
            current_capacity = p_count
            group_anchor_time = ready_dt
            continue
            
        within_time = (ready_dt - group_anchor_time <= max_wait_delta)
        
        if within_time:
            # Check if adding this entire multi-passenger row fits
            if current_capacity + p_count <= max_capacity:
                current_group.append(row)
                current_capacity += p_count
            else:
                # SPLIT LOGIC: Take what fits, push the rest to a new vehicle
                available_seats = max_capacity - current_capacity
                
                if available_seats > 0:
                    # Put a copy of the row in the current vehicle to fill remaining seats
                    current_group.append(copy.deepcopy(row))
                    optimized_groups.append({
                        "dispatch_time": group_anchor_time + max_wait_delta,
                        "flights": current_group,
                        "is_valid": True
                    })
                    
                    # Carry the remainder over to start the next group
                    remainder_count = p_count - available_seats
                    current_group = [copy.deepcopy(row)]
                    current_capacity = remainder_count
                    group_anchor_time = ready_dt
                else:
                    # No seats left at all, close out and start fresh group
                    optimized_groups.append({
                        "dispatch_time": group_anchor_time + max_wait_delta,
                        "flights": current_group,
                        "is_valid": True
                    })
                    current_group = [row]
                    current_capacity = p_count
                    group_anchor_time = ready_dt
        else:
            # Time window expired
            optimized_groups.append({
                "dispatch_time": group_anchor_time + max_wait_delta,
                "flights": current_group,
                "is_valid": True
            })
            current_group = [row]
            current_capacity = p_count
            group_anchor_time = ready_dt
            
    if current_group:
        optimized_groups.append({
            "dispatch_time": group_anchor_time + max_wait_delta,
            "flights": current_group,
            "is_valid": True
        })
        
    if unassigned_rows:
        optimized_groups.append({
            "dispatch_time": None,
            "flights": unassigned_rows,
            "is_valid": False
        })
        
    return optimized_groups

# ----------------------------------------------------------------
# Integration Pipeline Example
# ----------------------------------------------------------------
def export_grouped_manifest(all_processed_rows, arrival_idx, origin_idx, final_csv_path):
    header = all_processed_rows[0]
    data_rows = all_processed_rows[1:]
    
    # Pass origin_idx down to the grouping engine
    groups = build_pickup_groups(data_rows, arrival_idx, origin_idx, max_wait_hours=2)
    
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
            
    with open(final_csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(final_output_rows)

def run_optimization_pipeline(processed_rows, max_wait_hours=2, max_capacity=10):
    """
    STAGE 2: Evaluates windowing constraints and exports grouped manifest.
    Accepts variable max_wait_hours thresholds dynamically from the web frontend.
    """
    if not processed_rows or len(processed_rows) <= 1:
        print("No active datasets passed down to run optimization groupings.")
        return []

    print("\nStarting Stage 2: Grouping passenger schedules...")

    import copy
    header = copy.deepcopy(processed_rows[0])
    data_rows = copy.deepcopy(processed_rows[1:])

    # 1. Locate the Arrival column
    try:
        arrival_idx = next(i for i, h in enumerate(header) if h and "ARRIVAL" in str(h).upper())
    except StopIteration:
        print("Structural Mapping Error: Missing active 'Arrival' field definitions.")
        return []

    # 2. Locate the Origin column (New Addition)
    try:
        origin_idx = next(i for i, h in enumerate(header) if h and "ORIGIN" in str(h).upper())
    except StopIteration:
        print("Structural Mapping Error: Missing active 'Origin' field definitions.")
        return []

    # 3. Pass both indices down to the upgraded windowing engine
    groups = build_pickup_groups(
        data_rows, 
        header=header, # <-- Pass down the unmutated header context here
        arrival_index=arrival_idx, 
        origin_index=origin_idx, 
        max_wait_hours=max_wait_hours,
        max_capacity=max_capacity
    )

    # UPDATED: Insert columns sequentially so the header indexes match the data rows perfectly
    header.insert(0, "Pickup Group ID")
    header.insert(1, "Target Vehicle Dispatch")
    header.insert(2, "Passenger Wait Time") # <-- Added here to match row.insert(2, ...) below
    final_output_rows = [header]

    for group_id, group_meta in enumerate(groups, start=1):
        if group_meta.get("is_valid", True):
            group_name = f"Group #{group_id}"
            dispatch_dt = group_meta["dispatch_time"]
            dispatch_str = dispatch_dt.strftime("%Y-%m-%d %H:%M")
        else:
            group_name = "MANUAL REVIEW"
            dispatch_str = "N/A - Review Flight"

        for row in group_meta["flights"]:
            
            # Calculate wait time by looking up the arrival cell inside the row
            if group_meta.get("is_valid", True) and dispatch_dt:
                arr_dt = parse_flight_time(row[arrival_idx])
                if arr_dt:
                    # Dynamically re-verify clearing delay for accuracy
                    if is_international_flight(row, origin_idx):
                        ready_dt = arr_dt + timedelta(minutes=60)
                    else:
                        ready_dt = arr_dt + timedelta(minutes=30)
                        
                    wait_delta = dispatch_dt - ready_dt
                    wait_minutes = int(wait_delta.total_seconds() / 60)
                    wait_str = f"{wait_minutes} min"
                else:
                    wait_str = "N/A"
            else:
                wait_str = "N/A"

            # Insert values sequentially matching header mapping
            row.insert(0, group_name)
            row.insert(1, dispatch_str)
            row.insert(2, wait_str) 
            final_output_rows.append(row)

    return final_output_rows