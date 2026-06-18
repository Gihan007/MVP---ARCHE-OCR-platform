import streamlit as st
import requests
import json

# API Configuration
API_BASE_URL = "http://localhost:8001"
PROCESSING_API_URL = "http://localhost:8002/api/v1"

st.set_page_config(
    page_title="OCR-ArcheAI Frontend",
    page_icon="📄",
    layout="wide"
)

st.title("📄 OCR-ArcheAI - Fax Processing System")
st.markdown("---")

# Functions
def upload_file(file, tenant_id: str = "default"):
    """Upload a file to the system"""
    if file is None:
        return None

    files = {"file": (file.name, file.getvalue(), file.type)}
    data = {"tenant_id": tenant_id}

    try:
        response = requests.post(f"{API_BASE_URL}/upload", files=files, data=data)
        if response.status_code in [200, 201]:
            return response.json()
        else:
            st.error(f"Upload failed: {response.text}")
            return None
    except Exception as e:
        st.error(f"Error uploading file: {str(e)}")
        return None

def process_job_via_processing_api(job_id: int, tenant_id: str = "default"):
    """Process a job via the processing API"""
    try:
        response = requests.post(
            f"{PROCESSING_API_URL}/fax/process/{job_id}",
            json={"tenant_id": tenant_id}
        )
        if response.status_code in [200, 201]:
            return response.json()
        else:
            st.error(f"Processing failed: {response.text}")
            return None
    except Exception as e:
        st.error(f"Error processing job: {str(e)}")
        return None

def export_csv(job_id: int, tenant_id: str = "default"):
    """Export extracted fields as CSV"""
    try:
        response = requests.get(f"{API_BASE_URL}/export-csv/{job_id}", params={"tenant_id": tenant_id})
        if response.status_code == 200:
            return response.content
        else:
            st.error(f"Failed to export CSV: {response.text}")
            return None
    except Exception as e:
        st.error(f"Error exporting CSV: {str(e)}")
        return None

# Main Components
tab1, tab2, tab3, tab4 = st.tabs(["📤 Upload Document", "📋 View Jobs", "⚙️ Process Job", "📊 Export CSV"])

with tab1:
    st.header("📤 Upload Document")
    st.markdown("Upload a fax document to get started")

    uploaded_file = st.file_uploader(
        "Choose a fax document",
        type=["pdf", "tiff", "tif", "jpg", "jpeg", "png"]
    )

    tenant_id = st.text_input("Tenant ID", value="default")

    if st.button("🚀 Upload Document", type="primary") and uploaded_file is not None:
        with st.spinner("Uploading..."):
            result = upload_file(uploaded_file, tenant_id)
            if result:
                st.success("✅ Upload successful!")
                st.json(result)

with tab2:
    st.header("📋 View Jobs")
    st.markdown("[🔗 pgAdmin](http://localhost:5050) | See all current jobs and their details")

    if st.button("🔄 Load Jobs"):
        with st.spinner("Loading jobs..."):
            response = requests.get(f"{API_BASE_URL}/jobs")
            if response.status_code == 200:
                data = response.json()
                jobs = data.get("jobs", [])
                total = data.get("total", 0)

                if jobs:
                    st.write(f"**Total Jobs:** {total}")

                    # Simple expandable list
                    for job in jobs:
                        with st.expander(f"Job {job.get('fax_job_id')} - {job.get('status', 'Unknown')}"):
                            col1, col2 = st.columns(2)
                            with col1:
                                st.write(f"**ID:** {job.get('fax_job_id')}")
                                st.write(f"**Tenant:** {job.get('tenant_id')}")
                                st.write(f"**Status:** {job.get('status')}")
                            with col2:
                                st.write(f"**Created:** {job.get('created_at', 'N/A')}")
                                st.write(f"**SHA256:** {job.get('sha256', 'N/A')[:16]}...")
                                st.write(f"**Review:** {'Yes' if job.get('review_needed') else 'No'}")
                else:
                    st.info("No jobs found")
            else:
                st.error(f"Failed to load jobs: {response.text}")

with tab3:
    st.header("⚙️ Process Job")
    st.markdown("Enter a Job ID to start processing")

    job_id = st.number_input("Job ID", min_value=1, step=1)
    process_tenant_id = st.text_input("Tenant ID (for processing)", value="default")

    if st.button("🚀 Start Processing"):
        if job_id:
            with st.spinner("Processing..."):
                result = process_job_via_processing_api(job_id, process_tenant_id)
                if result:
                    st.success("✅ Processing started!")
                    st.json(result)
                else:
                    st.error("Processing failed")
        else:
            st.error("Please enter a Job ID")

with tab4:
    st.header("📊 Export CSV")
    st.markdown("Export extracted fields for a job as CSV")

    export_job_id = st.number_input("Job ID for Export", min_value=1, step=1)
    export_tenant_id = st.text_input("Tenant ID (for export)", value="default")

    if st.button("📥 Download CSV"):
        if export_job_id:
            with st.spinner("Exporting CSV..."):
                csv_data = export_csv(export_job_id, export_tenant_id)
                if csv_data:
                    st.download_button(
                        label="📥 Download CSV File",
                        data=csv_data,
                        file_name=f"job_{export_job_id}_extracted_fields.csv",
                        mime="text/csv"
                    )
                    st.success("✅ CSV exported successfully!")
                else:
                    st.error("Failed to export CSV")
        else:
            st.error("Please enter a Job ID")

# Footer
st.markdown("---")
st.subheader("API Status")

col1, col2 = st.columns(2)
with col1:
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=5)
        st.success("✅ Main API Connected") if response.status_code == 200 else st.error("❌ Main API Error")
    except:
        st.error("❌ Main API Not Reachable")

with col2:
    try:
        response = requests.get(f"{PROCESSING_API_URL}/health", timeout=5)
        st.success("✅ Processing API Connected") if response.status_code == 200 else st.error("❌ Processing API Error")
    except:
        st.error("❌ Processing API Not Reachable")