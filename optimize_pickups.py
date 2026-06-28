import csv
from datetime import datetime, timedelta

def parse_flight_time(time_str):
    """
    Parses our cleaned datetime string (e.g., '2026-06-28 11:36 MDT') 
    ignoring newlines or timezone strings for absolute delta math.
    """
    if not time_str or "N/A" in time_str:
        return None
    try:
        # Clean up any newlines embedded by pdfplumber or string formatting
        clean_str = time_str.replace("\n", " ").strip()
        # Drop the timezone text tag at the end to get clean Y_M_D H:M
        base_time = " ".join(clean_str.split()[:2])
        return datetime.strptime(base_time, "%Y-%m-%d %H:%M")
    except Exception:
        return None

def build_pickup_groups(processed_rows, arrival_index, max_wait_hours=2):
    """
    Groups flights together ensuring no passenger waits longer than max_wait_hours.
    """
    # Extract data rows and sort them by parsed arrival datetime
    valid_data_rows = []
    for row in processed_rows:
        arr_dt = parse_flight_time(row[arrival_index])
        if arr_dt:
            valid_data_rows.append((arr_dt, row))
    
    # Sort chronologically by arrival time
    valid_data_rows.sort(key=lambda x: x[0])
    
    optimized_groups = []
    current_group = []
    group_anchor_time = None
    max_wait_delta = timedelta(hours=max_wait_hours)
    
    for arr_dt, row in valid_data_rows:
        # If no group is open, start a new one anchored by this flight
        if not current_group:
            current_group = [row]
            group_anchor_time = arr_dt
            continue
            
        # Check if adding this flight violates the 2-hour wait limit for the first person
        if arr_dt - group_anchor_time <= max_wait_delta:
            current_group.append(row)
        else:
            # Close current group, save it, and open a new group for this flight
            optimized_groups.append({
                "dispatch_time": group_anchor_time + max_wait_delta, # Optional vehicle target departure
                "flights": current_group
            })
            current_group = [row]
            group_anchor_time = arr_dt
            
    # Catch the final lingering group
    if current_group:
        optimized_groups.append({
            "dispatch_time": group_anchor_time + max_wait_delta,
            "flights": current_group
        })
        
    return optimized_groups

# ----------------------------------------------------------------
# Integration Pipeline Example
# ----------------------------------------------------------------
def export_grouped_manifest(all_processed_rows, arrival_idx, final_csv_path):
    # Separate Header from Data
    header = all_processed_rows[0]
    data_rows = all_processed_rows[1:]
    
    # Run optimization grouping (2 hours max wait)
    groups = build_pickup_groups(data_rows, arrival_idx, max_wait_hours=2)
    
    # Append a new Tracking Column to the CSV file header
    header.insert(0, "Pickup Group ID")
    header.insert(1, "Target Vehicle Dispatch")
    
    final_output_rows = [header]
    
    for group_id, group_meta in enumerate(groups, start=1):
        dispatch_str = group_meta["dispatch_time"].strftime("%Y-%m-%d %H:%M")
        for row in group_meta["flights"]:
            # Inject grouping info to the front of every row
            row.insert(0, f"Group #{group_id}")
            row.insert(1, dispatch_str)
            final_output_rows.append(row)
            
    with open(final_csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(final_output_rows)
    print(f"Successfully grouped flights! Consolidated manifest saved to: {final_csv_path}")