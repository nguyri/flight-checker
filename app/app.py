import streamlit as st
import pandas as pd
import io
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

# Optional: Mute noisy third-party libraries
logging.getLogger("urllib3").setLevel(logging.WARNING)

# Set page layout to wide for large dispatcher tables
st.set_page_config(page_title="Flight Shuttle Dispatcher", layout="wide")

st.title("✈️ Flight Checker")
st.write("Upload your passenger flight manifest CSV to extract live flight statuses, filter by destination, and optimize vehicle dispatch windows.")

# --- SIDEBAR CONFIGURATION LAYER ---
st.sidebar.header("Pipeline Configurations")
arrival_iata = st.sidebar.text_input("Target Arrival IATA Code", value="YYC").upper()

# ADDED: Date selector in the sidebar (defaults to today's date)
target_date = st.sidebar.date_input("Target Operational Date")

max_wait = st.sidebar.slider("Maximum Passenger Wait Window (Hours)", 1.0, 4.0, 2.0, step=0.5)

# --- STAGE 1: FILE UPLOAD HANDLER ---
uploaded_file = st.file_uploader("Choose a Manifest CSV file", type=["csv"])

if uploaded_file is not None:
    st.success("CSV Uploaded Successfully!")
    
    # Simple trigger button so you don't waste API quota on every page click
    if st.button("🚀 Check Flights & Shuttles"):
        
        with st.spinner("Processing Stage 1 & 2: Parsing CSV, hitting api.market gateway, and calculating optimization windows..."):
            
            # Temporarily save the uploaded bytes to a local CSV file path
            with open("temp_manifest.csv", "wb") as f:
                f.write(uploaded_file.getbuffer())
                
            # Convert the date object to standard YYYY-MM-DD string format
            date_str = target_date.strftime("%Y-%m-%d")
                
            # Run your exact backend code
            # UPDATED: Passing the target_date string into the extraction pipeline
            processed_rows = run_extraction_pipeline(
                csv_path="temp_manifest.csv", 
                target_iata=arrival_iata,
                manifest_date=date_str
            )
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
            st.subheader("Export Schedule")

            col1, col2 = st.columns(2)

            with col1:
                # 1. CSV Export
                csv_buffer = io.StringIO()
                df.to_csv(csv_buffer, index=False)
                csv_bytes = csv_buffer.getvalue().encode('utf-8')
                
                st.download_button(
                    label="📥 Download Manifest CSV",
                    data=csv_bytes,
                    file_name=f"shuttle_manifest_{date_str}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
                
            with col2:
                # 2. PDF Export using your existing module
                with st.spinner("Compiling PDF document..."):
                    # Create an in-memory byte buffer
                    pdf_buffer = io.BytesIO()
                    
                    # Re-compile your DataFrame back into rows format [[header], [row1], [row2]]
                    compiled_rows = [df.columns.tolist()] + df.values.tolist()
                    
                    # Execute your existing function directly into the buffer
                    success = save_pipeline_to_pdf(
                        compiled_rows=compiled_rows, 
                        output_pdf_path=pdf_buffer, # Passing the buffer stream
                        MANIFEST_DATE=date_str
                    )
                    
                    if success:
                        # Grab the raw bytes out of the completed buffer
                        pdf_bytes = pdf_buffer.getvalue()
                        
                        st.download_button(
                            label="📄 Download Printable PDF Report",
                            data=pdf_bytes,
                            file_name=f"shuttle_manifest_{date_str}.pdf",
                            mime="application/pdf",
                            use_container_width=True
                        )
                    else:
                        st.error("Could not compile PDF report. Check backend logs.")
        else:
            st.error("Pipeline failure. Check your console logs or verify the format structure of your CSV.")