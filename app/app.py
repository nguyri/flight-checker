import streamlit as st
import pandas as pd
import io
# Import your existing backend logic
from flight_checker import run_extraction_pipeline
from flight_checker import run_optimization_pipeline

import logging
import sys

# --- VERBOSE STREAM LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout) # Forces logs directly into your terminal screen
    ]
)

# Optional: Mute noisy third-party libraries (like pdfplumber or urllib3) 
# so they don't flood your screen when tracking API payloads
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("pdfplumber").setLevel(logging.WARNING)

# Set page layout to wide for large dispatcher tables
st.set_page_config(page_title="Flight Shuttle Dispatcher", layout="wide")

st.title("✈️ Flight Checker")
st.write("Upload your passenger flight manifest PDF to extract live flight statuses, filter by destination, and optimize vehicle dispatch windows.")

# --- SIDEBAR CONFIGURATION LAYER ---
st.sidebar.header("Pipeline Configurations")
arrival_iata = st.sidebar.text_input("Target Arrival IATA Code", value="YYC").upper()
max_wait = st.sidebar.slider("Maximum Passenger Wait Window (Hours)", 1.0, 4.0, 2.0, step=0.5)

# --- STAGE 1: FILE UPLOAD HANDLER ---
uploaded_file = st.file_uploader("Choose a Manifest PDF file", type=["pdf"])

if uploaded_file is not None:
    st.success("PDF Uploaded Successfully!")
    
    # Simple trigger button so you don't waste API quota on every page click
    if st.button("🚀 Check Flights & Shuttles"):
        
        with st.spinner("Processing Stage 1 & 2: Parsing PDF, hitting api.market gateway, and calculating optimization windows..."):
            
            # Temporarily save the uploaded bytes to a local string/path or pass to file handler
            # (Assuming your pipeline is adjusted to accept a file object or path string)
            with open("temp_manifest.pdf", "wb") as f:
                f.write(uploaded_file.getbuffer())
                
            # Run your exact backend code
            # Pass your side-bar variables to dynamically update your environment configs on the fly
            processed_rows = run_extraction_pipeline(pdf_path="temp_manifest.pdf", target_iata=arrival_iata)
            final_optimized_rows = run_optimization_pipeline(processed_rows, max_wait_hours=max_wait)
            
        if final_optimized_rows:
            # Separate out the structural layout for UI presentation
            header = final_optimized_rows[0]
            data = final_optimized_rows[1:]
            
            # Convert to a pandas DataFrame for visual manipulation
            df = pd.DataFrame(data, columns=header)

            # --- CLEANING LAYER: Ensure all column headers are completely unique ---
            seen = {}
            unique_columns = []
            for col in df.columns:
                col_str = str(col) if col else "Blank"
                seen[col_str] = seen.get(col_str, 0) + 1
                # If it's a duplicate, append a numeric suffix (e.g., "Flight", "Flight_1")
                unique_columns.append(col_str if seen[col_str] == 1 else f"{col_str}_{seen[col_str]-1}")

            df.columns = unique_columns

            # Force the row index to be a clean, unique 0 to N sequence
            df = df.reset_index(drop=True)

            # --- STAGE 2: LIVE OPERATIONAL REVIEW SHEET ---
            st.subheader("Schedule View")
            st.write(f"Total Rows Accounted For: **{len(df)}**")

            # Highlight Rows needing manual review due to API mismatch or bad times
            def highlight_issues(row):
                return ['background-color: #ffcccc' if 'MANUAL REVIEW' in str(val) or 'INVALID' in str(val) else '' for val in row]

            st.dataframe(df.style.apply(highlight_issues, axis=1), width="stretch")
            # --- STAGE 3: DOWNLOAD HANDLER ---
            # Stream the updated data straight into a local browser download buffer
            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False)
            csv_bytes = csv_buffer.getvalue().encode('utf-8')
            
            st.download_button(
                label="📥 Download Grouped Manifest CSV",
                data=csv_bytes,
                file_name="optimized_shuttle_manifest.csv",
                mime="text/csv",
            )
        else:
            st.error("Pipeline failure. Check your console logs or verify the format structure of your PDF.")