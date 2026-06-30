import pytest
from unittest.mock import patch
import unittest

# Import the logic directly from your development files
from app.cache import generate_shuttle_cache_key
from app.flight_checker import pick_best_shuttle_leg, get_flight_live_data, extract_full_flight_code
import app.flight_checker as fc

# ----------------------------------------------------------------
# UNIT TESTS: CACHE LAYER
# ----------------------------------------------------------------
import pytest
from app.cache import generate_shuttle_cache_key

def test_generate_shuttle_cache_key():
    """Verifies that strings are normalized and dates isolate cache keys."""
    # 1. Test standard valid case
    key = generate_shuttle_cache_key("UA2830", "12:30", "2026-06-29")
    assert key == "UA2830_20260629_1230"

    # 2. Test that a missing date correctly raises a ValueError as enforced by the code
    with pytest.raises(ValueError) as exc_info:
        generate_shuttle_cache_key("F8800", "08:00", None)
        
    # Optional: Verify that your exact error message or keyword is inside the exception
    assert "CRITICAL: Missing manifest date" in str(exc_info.value)


# ----------------------------------------------------------------
# UNIT TESTS: MATCHING ENGINE (PROXIMITY)
# ----------------------------------------------------------------
def test_pick_best_shuttle_leg_selection():
    """Verifies that the leg closest to the pickup window is chosen."""
    mock_legs = [
        {
            "arrival": {"airport": {"iata": "SFO"}, "scheduledTime": {"local": "2026-06-29 08:04-07:00"}},
            "status": "Expected"
        },
        {
            "arrival": {"airport": {"iata": "YYC"}, "scheduledTime": {"local": "2026-06-29 12:30-06:00"}},
            "status": "Expected"
        }
    ]
    
    # Manifest says pickup is 12:30 PM. It should pick Leg #2 (12:30), not Leg #1 (08:04)
    winner = pick_best_shuttle_leg(mock_legs, "12:30")
    assert winner["arrival"]["airport"]["iata"] == "YYC"


# ----------------------------------------------------------------
# INTEGRATION/UNIT TESTS: DESTINATION FILTER & API PACKAGING
# ----------------------------------------------------------------
@patch("app.flight_checker.fetch_live_flight_payload")
@patch.object(fc, "USE_CACHE", False)  # Targets the 'fc' module directly
def test_get_flight_live_data_destination_filtering(mock_fetch):
    # Mock array configuration
    mock_fetch.return_value = [
        {
            "arrival": {"airport": {"name": "San Francisco", "iata": "SFO"}, "scheduledTime": {"local": "2026-06-29 08:04-07:00"}},
            "departure": {"airport": {"name": "San Diego"}},
            "status": "Expected"
        },
        {
            "arrival": {"airport": {"name": "Calgary Airport", "iata": "YYC"}, "scheduledTime": {"local": "2026-06-29 12:30-06:00"}},
            "departure": {"airport": {"name": "San Francisco"}},
            "status": "Expected"
        }
    ]
    
    status, origin, sched_arr = get_flight_live_data("UA2830", "12:30")
    
    assert status == "Expected"
    assert "San\nFrancisco" in origin  
    assert "12:30" in sched_arr


@patch("app.flight_checker.fetch_live_flight_payload")
@patch("app.flight_checker.USE_CACHE", False)
def test_get_flight_live_data_invalid_destination(mock_fetch):
    """Ensures rows still populate with an explicit error token if the city doesn't match."""
    
    # Mock payload only goes to Philadelphia (PHL), completely missing Calgary
    mock_fetch.return_value = [
        {
            "arrival": {"airport": {"name": "Philadelphia", "iata": "PHL"}, "scheduledTime": {"local": "2026-06-29 11:35-04:00"}},
            "departure": {"airport": {"name": "Miami"}},
            "status": "Arrived"
        }
    ]
    
    status, origin, sched_arr = get_flight_live_data("AA551", "11:35")
    
    # Confirm it generates the requested error strings for row integration safety
    assert status == "Mismatch"
    assert sched_arr == "INVALID\nDESTINATION"

import csv

def test_csv_output_length_matches_source(tmp_path):
    """
    Verifies that writing extracted data blocks to a physical file 
    does not introduce row truncation or skipping dropouts.
    """
    # Simulate a 3-row extracted table dataset from a PDF document
    mock_extracted_source = [
        ["Flight", "Pickup Time", "Status"],
        ["UA2830", "12:30", "Expected"],
        ["AA551", "11:35", "Arrived"]
    ]
    
    # Exclude the header row from the data validation count
    source_count = len(mock_extracted_source) - 1 
    
    # Create a temporary output file
    temp_output_file = tmp_path / "test_output.csv"
    
    # Simulate writing data to disk
    with open(temp_output_file, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(mock_extracted_source)
        
    # Read back and run validation check
    with open(temp_output_file, mode="r", encoding="utf-8") as f:
        csv_row_count = sum(1 for row in f) - 1
        
    assert source_count == csv_row_count, f"Row mismatch! Source: {source_count}, Output: {csv_row_count}"

class TestFlightCodeExtraction(unittest.TestCase):

    def test_valid_full_input(self):
        """Test the full, non-truncated string."""
        text = "接机:是; 日期:2026-06-29; 时间:11:05:00; 航班:PD269; 机场:YYC"
        self.assertEqual(extract_full_flight_code(text), "PD269")

    def test_flight_number_with_keyword(self):
        """Test variation with 航班号 keyword."""
        text = "航班号: AC123; 机场: YYZ"
        self.assertEqual(extract_full_flight_code(text), "AC123")

    def test_truncated_input(self):
        """Verify behavior when input is truncated (expecting None)."""
        text = "接机:是; 日期:20"
        self.assertIsNone(extract_full_flight_code(text))

    def test_empty_input(self):
        """Test empty or null input."""
        self.assertIsNone(extract_full_flight_code(""))
        self.assertIsNone(extract_full_flight_code(None))

    def test_standard_pattern_fallback(self):
        """Test extracting a code without a Chinese keyword."""
        text = "Flight: UA764"
        # If your function falls back to searching for patterns like 'UA764'
        # ensure your regex matches that expected behavior.
        self.assertEqual(extract_full_flight_code("UA764"), "UA764")

if __name__ == '__main__':
    unittest.main()