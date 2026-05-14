"""
GCCC Property Zoning Analyser — Streamlit UI
=============================================
Run with:
    streamlit run app.py

Workflow:
    1. Upload a CSV from harvest_addresses.py  OR  paste addresses manually
    2. Click Analyse
    3. Watch live results populate the table
    4. Download colour-coded Excel or CSV
"""

import sys
import os
import csv
import time
import tempfile
import io
from pathlib import Path

import streamlit as st
import pandas as pd

# ---------------------------------------------------------------------------
# Import core analyser — looks in same folder as this script
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))
import gccc_zoning_analyser as ga


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="GCCC Zoning Analyser",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS — clean, professional look
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* Main header */
    .main-header {
        background: linear-gradient(135deg, #1a3a5c 0%, #2d6a9f 100%);
        padding: 2rem;
        border-radius: 12px;
        color: white;
        margin-bottom: 1.5rem;
    }
    .main-header h1 { color: white; margin: 0; font-size: 2rem; }
    .main-header p  { color: #b8d4ea; margin: 0.3rem 0 0; font-size: 1rem; }

    /* Metric cards */
    .metric-card {
        background: white;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        border-left: 5px solid #2d6a9f;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        margin-bottom: 0.5rem;
    }
    .metric-card.ldr  { border-left-color: #4caf50; }
    .metric-card.mdr  { border-left-color: #ff9800; }
    .metric-card.hdr  { border-left-color: #f44336; }
    .metric-card.hi   { border-left-color: #9c27b0; }
    .metric-card.err  { border-left-color: #9e9e9e; }
    .metric-number { font-size: 2rem; font-weight: 700; color: #1a3a5c; }
    .metric-label  { font-size: 0.85rem; color: #666; margin-top: 0.2rem; }

    /* Status badges */
    .badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.78rem;
        font-weight: 600;
    }
    .badge-ldr { background: #e8f5e9; color: #2e7d32; }
    .badge-mdr { background: #fff3e0; color: #e65100; }
    .badge-hdr { background: #fce4ec; color: #c62828; }
    .badge-hi  { background: #f3e5f5; color: #6a1b9a; }
    .badge-err { background: #f5f5f5; color: #616161; }

    /* Progress section */
    .progress-label { font-size: 0.9rem; color: #444; margin-bottom: 0.3rem; }

    /* Instruction steps */
    .step-box {
        background: #f8f9ff;
        border: 1px solid #dde3f0;
        border-radius: 8px;
        padding: 0.8rem 1rem;
        margin-bottom: 0.5rem;
        font-size: 0.9rem;
    }
    .step-num {
        background: #2d6a9f;
        color: white;
        border-radius: 50%;
        width: 22px;
        height: 22px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 0.75rem;
        font-weight: 700;
        margin-right: 8px;
    }

    /* Hide streamlit branding */
    #MainMenu { visibility: hidden; }
    footer     { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ZONE_BADGE = {
    "Low Density Residential":    ("badge badge-ldr", "🟢 Low Density"),
    "Medium Density Residential": ("badge badge-mdr", "🟠 Medium Density"),
    "Higher Density Residential": ("badge badge-hdr", "🔴 Higher Density"),
    "High Density Residential":   ("badge badge-hdr", "🔴 High Density"),
    "High Rise":                  ("badge badge-hi",  "🟣 High Rise"),
}

ZONE_SORT_ORDER = {
    "Low Density Residential":    0,
    "Medium Density Residential": 1,
    "Higher Density Residential": 2,
    "High Density Residential":   2,
    "High Rise":                  3,
    "Lookup failed":              5,
}

RESULTS_COLS = {
    "address":       "Address",
    "price":         "Price",
    "zone_cat":      "Zone Category",
    "zone_code":     "Density Code",
    "zone_precinct": "Zone Precinct",
    "zone_desc":     "Description",
    "api_error":     "Error",
}


# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------
def init_state():
    defaults = {
        "results":    [],
        "running":    False,
        "complete":   False,
        "error_msg":  None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()


# ---------------------------------------------------------------------------
# Helper — parse uploaded or pasted addresses into list[dict]
# ---------------------------------------------------------------------------
def parse_csv_upload(uploaded_file) -> list[dict]:
    """Parse an uploaded CSV file (from harvest_addresses.py)."""
    content = uploaded_file.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    records = []
    for row in reader:
        addr = row.get("address", "").strip()
        if addr:
            records.append({
                "address": addr,
                "price":   row.get("price", "").strip(),
                "url":     row.get("url", "").strip(),
            })
    return records


def parse_pasted_addresses(text: str) -> list[dict]:
    """Parse manually pasted addresses — one per line."""
    records = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            records.append({"address": line, "price": "", "url": ""})
    return records


# ---------------------------------------------------------------------------
# Helper — colour-code the results dataframe
# ---------------------------------------------------------------------------
def style_results(df: pd.DataFrame) -> pd.DataFrame.style:
    """Apply zone category background colours to the dataframe."""
    colour_map = {
        "Low Density Residential":    "#C6EFCE",
        "Medium Density Residential": "#FFECC7",
        "Higher Density Residential": "#FFC7CE",
        "High Density Residential":   "#FFC7CE",
        "High Rise":                  "#E2CFFE",
        "Lookup failed":              "#D9D9D9",
    }

    def row_colour(row):
        colour = colour_map.get(row.get("Zone Category", ""), "#FFFFFF")
        return [f"background-color: {colour}" for _ in row]

    return df.style.apply(row_colour, axis=1)


# ---------------------------------------------------------------------------
# Helper — run analysis with live progress updates
# ---------------------------------------------------------------------------
def run_analysis(records: list[dict], progress_bar, status_text, results_placeholder):
    """
    Process each address one by one, updating the UI live.
    Returns the full results list.
    """
    results    = []
    total      = len(records)
    delay_geo  = st.session_state.get("delay_geo", 1.2)
    delay_api  = st.session_state.get("delay_api", 0.3)

    for i, item in enumerate(records):
        address = item.get("address", "")
        price   = item.get("price", "")
        url     = item.get("url", "")

        status_text.markdown(
            f'<p class="progress-label">Processing {i+1} of {total}: '
            f'<strong>{address[:60]}</strong></p>',
            unsafe_allow_html=True
        )

        # Geocode
        time.sleep(delay_geo)
        lat, lng = ga.geocode_address(address)

        result = {
            "address":       address,
            "price":         price,
            "url":           url,
            "lat":           round(lat, 6) if lat else "",
            "lng":           round(lng, 6) if lng else "",
            "zone_name":     "",
            "zone_cat":      "",
            "zone_precinct": "",
            "zone_desc":     "",
            "zone_code":     "",
            "cat_desc":      "",
            "ovl_cat":       "",
            "ovl2_desc":     "",
            "api_error":     "",
        }

        if lat is None:
            result["zone_cat"]  = "Lookup failed"
            result["api_error"] = "Geocoding failed"
        else:
            time.sleep(delay_api)
            zone = ga.get_residential_density(lat, lng)
            result.update(zone)

        results.append(result)
        progress_bar.progress((i + 1) / total)

        # Update live results table
        _show_live_table(results, results_placeholder)

    return results


def _show_live_table(results: list[dict], placeholder):
    """Render the results table into a Streamlit placeholder."""
    if not results:
        return
    display_rows = []
    for r in results:
        display_rows.append({
            "Address":       r.get("address", ""),
            "Price":         r.get("price", ""),
            "Zone Category": r.get("zone_cat", ""),
            "Density Code":  r.get("zone_code", ""),
            "Description":   r.get("zone_desc", "")[:60] if r.get("zone_desc") else "",
            "Error":         r.get("api_error", ""),
        })
    df = pd.DataFrame(display_rows)
    styled = style_results(df)
    placeholder.dataframe(styled, use_container_width=True, height=350)


# ---------------------------------------------------------------------------
# Helper — summary metric cards
# ---------------------------------------------------------------------------
def show_summary_cards(results: list[dict]):
    counts = {}
    for r in results:
        cat = r.get("zone_cat") or "Lookup failed"
        counts[cat] = counts.get(cat, 0) + 1

    card_config = [
        ("Low Density Residential",    "ldr", "🟢"),
        ("Medium Density Residential", "mdr", "🟠"),
        ("Higher Density Residential", "hdr", "🔴"),
        ("High Density Residential",   "hdr", "🔴"),
        ("High Rise",                  "hi",  "🟣"),
        ("Lookup failed",              "err", "⚪"),
    ]

    # Deduplicate HDR rows
    seen = set()
    cols_needed = []
    for label, css, icon in card_config:
        if counts.get(label, 0) > 0 and label not in seen:
            seen.add(label)
            cols_needed.append((label, css, icon))

    total_col, *zone_cols = st.columns(len(cols_needed) + 1)
    with total_col:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-number">{len(results)}</div>
            <div class="metric-label">Total properties</div>
        </div>""", unsafe_allow_html=True)

    for col, (label, css, icon) in zip(zone_cols, cols_needed):
        with col:
            st.markdown(f"""
            <div class="metric-card {css}">
                <div class="metric-number">{counts.get(label, 0)}</div>
                <div class="metric-label">{icon} {label}</div>
            </div>""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helper — build download files
# ---------------------------------------------------------------------------
def build_downloads(results: list[dict]) -> tuple[bytes, bytes]:
    """Returns (csv_bytes, excel_bytes)."""
    # CSV
    fieldnames = [
        "address", "price", "url",
        "zone_name", "zone_cat", "zone_precinct",
        "zone_code", "zone_desc",
        "cat_desc", "ovl_cat", "ovl2_desc",
        "api_error", "lat", "lng",
    ]
    csv_buf = io.StringIO()
    writer  = csv.DictWriter(csv_buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(results)
    csv_bytes = csv_buf.getvalue().encode("utf-8")

    # Excel — write to temp file, read back as bytes
    excel_bytes = None
    try:
        tmp_csv  = tempfile.mktemp(suffix=".csv")
        tmp_xlsx = tmp_csv.replace(".csv", ".xlsx")
        ga.write_excel(results, tmp_csv)
        if os.path.exists(tmp_xlsx):
            with open(tmp_xlsx, "rb") as f:
                excel_bytes = f.read()
            os.remove(tmp_xlsx)
        if os.path.exists(tmp_csv):
            os.remove(tmp_csv)
    except Exception as e:
        st.warning(f"Excel generation failed: {e}")

    return csv_bytes, excel_bytes


# ===========================================================================
# MAIN UI
# ===========================================================================

# --- Header ---
st.markdown("""
<div class="main-header">
    <h1>🏠 GCCC Property Zoning Analyser</h1>
    <p>Gold Coast City Council — identify Low, Medium & High Density zoning for property listings</p>
</div>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Sidebar — settings
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Settings")

    st.subheader("Geocoder")
    geocoder = st.selectbox(
        "Preferred geocoder",
        ["QLD Government (recommended)", "Nominatim (OpenStreetMap)", "Google Maps API"],
        help="QLD Government uses official council address data — most accurate for Gold Coast."
    )
    if geocoder == "Google Maps API":
        google_key = st.text_input("Google Maps API Key", type="password")
        if google_key:
            os.environ["GOOGLE_MAPS_API_KEY"] = google_key

    st.subheader("Rate limits")
    st.session_state["delay_geo"] = st.slider(
        "Geocoding delay (seconds)",
        min_value=0.5, max_value=3.0, value=1.2, step=0.1,
        help="Delay between geocoding requests. Increase if you hit rate limits."
    )
    st.session_state["delay_api"] = st.slider(
        "Zone API delay (seconds)",
        min_value=0.1, max_value=2.0, value=0.3, step=0.1,
        help="Delay between GCCC ArcGIS queries."
    )

    st.divider()
    st.subheader("🔗 How to get addresses")
    st.markdown("""
    <div class="step-box">
        <span class="step-num">1</span>
        Run <code>harvest_addresses.py</code> on your PC
    </div>
    <div class="step-box">
        <span class="step-num">2</span>
        It saves <code>addresses.csv</code> with address, price & listing URL
    </div>
    <div class="step-box">
        <span class="step-num">3</span>
        Upload that CSV here → click Analyse
    </div>
    """, unsafe_allow_html=True)

    st.divider()
    st.caption("GCCC ArcGIS — City Plan V7\nmaps1.goldcoast.qld.gov.au")


# ---------------------------------------------------------------------------
# Input section
# ---------------------------------------------------------------------------
st.subheader("📥 Input")
tab_upload, tab_manual = st.tabs(["📁 Upload CSV", "✏️ Paste Addresses"])

records = []

with tab_upload:
    st.markdown("Upload the `addresses.csv` file generated by **harvest_addresses.py**")
    uploaded = st.file_uploader(
        "Choose file",
        type=["csv", "txt"],
        help="CSV from harvest_addresses.py (with address, price, url columns) or plain TXT (one address per line)"
    )
    if uploaded:
        try:
            if uploaded.name.endswith(".csv"):
                records = parse_csv_upload(uploaded)
            else:
                content = uploaded.read().decode("utf-8")
                records = parse_pasted_addresses(content)
            st.success(f"✓ Loaded **{len(records)}** address(es) from {uploaded.name}")

            # Preview
            if records:
                preview_df = pd.DataFrame(records[:5])
                st.dataframe(preview_df, use_container_width=True, height=200)
                if len(records) > 5:
                    st.caption(f"Showing first 5 of {len(records)} rows")
        except Exception as e:
            st.error(f"Could not read file: {e}")

with tab_manual:
    st.markdown("Paste addresses below — one per line. Include suburb and postcode for best results.")
    example = (
        "12 James Street, Burleigh Heads QLD 4220\n"
        "8 Hedges Avenue, Mermaid Beach QLD 4218\n"
        "100 Surf Parade, Broadbeach QLD 4218"
    )
    pasted = st.text_area(
        "Addresses",
        placeholder=example,
        height=180,
        help="One address per line. Lines starting with # are ignored."
    )
    if pasted.strip():
        manual_records = parse_pasted_addresses(pasted)
        if manual_records:
            records = manual_records
            st.caption(f"✓ {len(records)} address(es) ready to analyse")


# ---------------------------------------------------------------------------
# Analyse button
# ---------------------------------------------------------------------------
st.divider()
col_btn, col_info = st.columns([1, 3])
with col_btn:
    run_btn = st.button(
        "🔍 Analyse Zoning",
        type="primary",
        disabled=len(records) == 0,
        use_container_width=True,
    )
with col_info:
    if not records:
        st.info("Upload a file or paste addresses above to get started.")
    else:
        est_secs = len(records) * (
            st.session_state.get("delay_geo", 1.2) +
            st.session_state.get("delay_api", 0.3) + 0.3
        )
        est_mins = est_secs / 60
        if est_mins < 1:
            st.info(f"Ready to analyse **{len(records)}** properties — estimated time: ~{int(est_secs)}s")
        else:
            st.info(f"Ready to analyse **{len(records)}** properties — estimated time: ~{est_mins:.1f} mins")


# ---------------------------------------------------------------------------
# Run analysis
# ---------------------------------------------------------------------------
if run_btn and records:
    st.session_state["results"]  = []
    st.session_state["complete"] = False
    st.session_state["running"]  = True

    st.divider()
    st.subheader("⏳ Processing")

    progress_bar      = st.progress(0)
    status_text       = st.empty()
    results_placeholder = st.empty()

    with st.spinner("Analysing properties..."):
        try:
            results = run_analysis(
                records,
                progress_bar,
                status_text,
                results_placeholder
            )
            st.session_state["results"]  = results
            st.session_state["complete"] = True
            st.session_state["running"]  = False
            status_text.markdown(
                '<p class="progress-label">✅ Analysis complete!</p>',
                unsafe_allow_html=True
            )
        except Exception as e:
            st.error(f"Analysis failed: {e}")
            st.session_state["running"] = False


# ---------------------------------------------------------------------------
# Results section
# ---------------------------------------------------------------------------
if st.session_state["complete"] and st.session_state["results"]:
    results = st.session_state["results"]

    st.divider()
    st.subheader("📊 Results")

    # Summary cards
    show_summary_cards(results)
    st.markdown("<br>", unsafe_allow_html=True)

    # Sort results
    sorted_results = sorted(
        results,
        key=lambda r: (
            ZONE_SORT_ORDER.get(r.get("zone_cat", ""), 4),
            r.get("address", "")
        )
    )

    # Full table
    display_rows = []
    for r in sorted_results:
        display_rows.append({
            "Address":        r.get("address", ""),
            "Price":          r.get("price", ""),
            "Zone Category":  r.get("zone_cat", ""),
            "Density Code":   r.get("zone_code", ""),
            "Zone Precinct":  r.get("zone_precinct", ""),
            "Description":    r.get("zone_desc", ""),
            "Error":          r.get("api_error", ""),
        })

    df = pd.DataFrame(display_rows)
    st.dataframe(
        style_results(df),
        use_container_width=True,
        height=min(50 + len(df) * 38, 600),
    )

    # Filter shortcuts
    st.markdown("**Quick filters:**")
    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        if st.button("🟢 Low Density only"):
            filtered = [r for r in sorted_results if "Low Density" in r.get("zone_cat", "")]
            st.dataframe(
                style_results(pd.DataFrame([{
                    "Address": r["address"], "Price": r["price"],
                    "Zone Category": r["zone_cat"], "Density Code": r["zone_code"]
                } for r in filtered])),
                use_container_width=True
            )
    with fc2:
        if st.button("🟠 Medium Density only"):
            filtered = [r for r in sorted_results if "Medium Density" in r.get("zone_cat", "")]
            st.dataframe(
                style_results(pd.DataFrame([{
                    "Address": r["address"], "Price": r["price"],
                    "Zone Category": r["zone_cat"], "Density Code": r["zone_code"]
                } for r in filtered])),
                use_container_width=True
            )
    with fc3:
        if st.button("🔴 Higher Density only"):
            filtered = [r for r in sorted_results if "Higher Density" in r.get("zone_cat", "") or "High Density" in r.get("zone_cat", "")]
            st.dataframe(
                style_results(pd.DataFrame([{
                    "Address": r["address"], "Price": r["price"],
                    "Zone Category": r["zone_cat"], "Density Code": r["zone_code"]
                } for r in filtered])),
                use_container_width=True
            )
    with fc4:
        if st.button("⚠️ Failed lookups"):
            filtered = [r for r in sorted_results if r.get("api_error")]
            if filtered:
                st.dataframe(pd.DataFrame([{
                    "Address": r["address"], "Error": r["api_error"]
                } for r in filtered]), use_container_width=True)
            else:
                st.success("No failed lookups 🎉")

    # Downloads
    st.divider()
    st.subheader("💾 Download Results")

    csv_bytes, excel_bytes = build_downloads(sorted_results)

    dl1, dl2, dl3 = st.columns(3)
    with dl1:
        st.download_button(
            label="📥 Download Excel (.xlsx)",
            data=excel_bytes or b"",
            file_name="zoning_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            disabled=excel_bytes is None,
            type="primary",
        )
    with dl2:
        st.download_button(
            label="📥 Download CSV",
            data=csv_bytes,
            file_name="zoning_results.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with dl3:
        # MDR-only CSV
        mdr_results = [r for r in sorted_results if "Medium Density" in r.get("zone_cat", "")]
        if mdr_results:
            mdr_buf = io.StringIO()
            fieldnames = ["address", "price", "url", "zone_cat", "zone_code", "zone_desc"]
            mdr_writer = csv.DictWriter(mdr_buf, fieldnames=fieldnames, extrasaction="ignore")
            mdr_writer.writeheader()
            mdr_writer.writerows(mdr_results)
            st.download_button(
                label=f"📥 MDR Only CSV ({len(mdr_results)})",
                data=mdr_buf.getvalue().encode("utf-8"),
                file_name="zoning_results_mdr.csv",
                mime="text/csv",
                use_container_width=True,
            )

    st.caption(
        f"Results sorted by zone category. "
        f"Excel file includes colour coding and a Legend sheet. "
    )
