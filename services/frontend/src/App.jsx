import { useState, useRef } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8001";
const API_UPLOAD_URL = `${API_BASE_URL}/upload`;
const API_UPLOAD_COMPLETE_URL = `${API_BASE_URL}/upload/complete`;
const API_BULK_UPLOAD_URL = `${API_BASE_URL}/upload/bulk`;
const API_PROCESS_URL = (jobId) => `${API_BASE_URL}/process/${jobId}`;
const API_PROCESS_BULK_URL = `${API_BASE_URL}/process/bulk`;
const API_PROCESS_STATUS_URL = (jobId) => `${API_BASE_URL}/process/status/${jobId}`;
const API_JOBS_URL = `${API_BASE_URL}/jobs`;
const API_JOB_URL = (jobId) => `${API_BASE_URL}/jobs/${jobId}`;
const API_JOB_SUMMARY_URL = (jobId) => `${API_BASE_URL}/jobs/${jobId}/summary`;
const API_JOB_FIELDS_URL = (jobId) => `${API_BASE_URL}/jobs/${jobId}/fields`;
const API_EXPORT_CSV_URL = (jobId) => `${API_BASE_URL}/export-csv/${jobId}`;
const API_DATABASE_TABLES_URL = `${API_BASE_URL}/database/tables`;
const API_DATABASE_TABLE_URL = (tableName) => `${API_BASE_URL}/database/tables/${encodeURIComponent(tableName)}`;

function App() {
  const [tenantId, setTenantId] = useState("default");
  const [files, setFiles] = useState([]);
  const fileInputRef = useRef(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [bulkJobs, setBulkJobs] = useState([]);
  const [bulkMessage, setBulkMessage] = useState("");
  const [bulkError, setBulkError] = useState("");

  const [processMessage, setProcessMessage] = useState("");
  const [processStatus, setProcessStatus] = useState("");
  const [processError, setProcessError] = useState("");
  const [latestJobSummary, setLatestJobSummary] = useState(null);
  const [summaryError, setSummaryError] = useState("");
  const [bulkSummaries, setBulkSummaries] = useState({});
  const [bulkFields, setBulkFields] = useState({});
  const summaryPollRef = useRef(null);
  const singleFileInputRef = useRef(null);
  const [singleTenantId, setSingleTenantId] = useState("default");
  const [singleFile, setSingleFile] = useState(null);
  const [singleAutoProcess, setSingleAutoProcess] = useState(true);
  const [singleWaitForResult, setSingleWaitForResult] = useState(false);
  const [singleUploading, setSingleUploading] = useState(false);
  const [singleMessage, setSingleMessage] = useState("");
  const [singleError, setSingleError] = useState("");
  const [singleResult, setSingleResult] = useState(null);
  const [manualJobId, setManualJobId] = useState("");
  const [manualTenantId, setManualTenantId] = useState("default");
  const [processStatusResult, setProcessStatusResult] = useState(null);
  const [jobsTenantFilter, setJobsTenantFilter] = useState("");
  const [jobsStatusFilter, setJobsStatusFilter] = useState("");
  const [jobsLoading, setJobsLoading] = useState(false);
  const [jobsError, setJobsError] = useState("");
  const [jobsPayload, setJobsPayload] = useState(null);
  const [lookupJobId, setLookupJobId] = useState("");
  const [lookupResult, setLookupResult] = useState(null);
  const [lookupError, setLookupError] = useState("");
  const [exportJobId, setExportJobId] = useState("");

  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const fetchJobSummary = async (jobIdValue, tenantValue) => {
    const params = new URLSearchParams({ tenant_id: tenantValue }).toString();
    const response = await fetch(`${API_JOB_SUMMARY_URL(jobIdValue)}?${params}`);
    const data = await response.json();

    if (!response.ok) {
      const message = data.detail || data.message || "Unable to load job summary";
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }

    return data;
  };

  const startSummaryPolling = (jobIdValue, tenantValue) => {
    const token = Symbol("summary-poll");
    summaryPollRef.current = token;

    const poll = async () => {
      const maxAttempts = 120; // ~5 minutes at 2.5s interval
      const intervalMs = 2500;

      for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
        if (summaryPollRef.current !== token) {
          return;
        }

        try {
          const summary = await fetchJobSummary(jobIdValue, tenantValue);
          setLatestJobSummary(summary);
          setSummaryError("");
          setProcessStatus(summary.status || "");
          setProcessMessage(
            summary.status_message ||
              summary.summary_message ||
              summary.status ||
              "Processing complete"
          );

          if (summary.is_final) {
            return;
          }
        } catch (err) {
          const message = err.message || "Unable to load job summary";
          if (err.status === 404) {
            setSummaryError(`Job ${jobIdValue} not found`);
            setProcessError(`Job ${jobIdValue} not found`);
            // Stop polling this job
            if (summaryPollRef.current === token) {
              summaryPollRef.current = null;
            }
            return;
          }
          setSummaryError(message);
          if (attempt === maxAttempts - 1) {
            setProcessError(message);
          }
        }

        await delay(intervalMs);
      }

      if (summaryPollRef.current === token) {
        setProcessMessage("Still waiting for extraction summary...");
      }
    };

    poll();
  };

  const pollJobSummary = async (jobIdValue, tenantValue) => {
    const maxAttempts = 120; // ~5 minutes
    const intervalMs = 2500;

    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      try {
        const summary = await fetchJobSummary(jobIdValue, tenantValue);
        setBulkSummaries((prev) => ({ ...prev, [jobIdValue]: summary }));
        if (summary.is_final) {
          try {
            const params = new URLSearchParams({ tenant_id: tenantValue }).toString();
            const resp = await fetch(`${API_JOB_FIELDS_URL(jobIdValue)}?${params}`);
            const payload = await resp.json();
            if (resp.ok) {
              setBulkFields((prev) => ({ ...prev, [jobIdValue]: payload.fields || {} }));
            }
          } catch (err) {
            // best-effort; ignore field fetch errors
          }
          return;
        }
        if (summary.is_final) {
          return;
        }
      } catch (err) {
        if (err.status === 404) {
          setBulkSummaries((prev) => ({ ...prev, [jobIdValue]: { error: `Job ${jobIdValue} not found` } }));
          return;
        }
        if (attempt === maxAttempts - 1) {
          setBulkSummaries((prev) => ({ ...prev, [jobIdValue]: { error: err.message } }));
        }
      }

      await delay(intervalMs);
    }
  };

  const startBulkSummaryPolling = (jobIds, tenantValue) => {
    jobIds.forEach((jobId) => {
      pollJobSummary(jobId, tenantValue);
    });
  };

  const [lastJobMeta, setLastJobMeta] = useState(null);
  const [reviewJobId, setReviewJobId] = useState("");
  const [reviewMessage, setReviewMessage] = useState("");
  const [reviewError, setReviewError] = useState("");
  const [reviewFrameUrl, setReviewFrameUrl] = useState("");
  const [reviewHistory, setReviewHistory] = useState([]);
  const [activeTab, setActiveTab] = useState("workspace");
  const [dbTables, setDbTables] = useState([]);
  const [dbTablesLoading, setDbTablesLoading] = useState(false);
  const [dbError, setDbError] = useState("");
  const [selectedDbTable, setSelectedDbTable] = useState("");
  const [dbRowsPayload, setDbRowsPayload] = useState(null);
  const [dbRowsLoading, setDbRowsLoading] = useState(false);
  const [dbLimit, setDbLimit] = useState(50);
  const [dbOffset, setDbOffset] = useState(0);

  const triggerProcessing = async (jobIdValue, tenantValue) => {
    const numericId = Number(jobIdValue);
    if (!numericId) {
      setProcessError("Enter a valid job ID");
      return false;
    }

    setProcessError("");
    setProcessMessage("");

    try {
      const normalizedTenant = tenantValue.trim() || "default";
      const url = `${API_PROCESS_URL(numericId)}?tenant_id=${encodeURIComponent(
        normalizedTenant
      )}`;
      const response = await fetch(url, {
        method: "POST"
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to start processing");
      }

      setProcessMessage(data.message || "Processing started");
      setProcessStatus(data.status || "processing");
      setLastJobMeta({ jobId: numericId, tenantId: normalizedTenant });
      setLatestJobSummary(null);
      setSummaryError("");
      setProcessError("");
      startSummaryPolling(numericId, normalizedTenant);
      return true;
    } catch (err) {
      setProcessError(err.message || "Processing request failed");
      return false;
    }
  };

  const startBulkProcessing = async (jobIds, tenantValue) => {
    if (!jobIds?.length) {
      return;
    }

    setProcessError("");
    setProcessMessage("");
    setProcessStatus("processing");

    try {
      const response = await fetch(API_PROCESS_BULK_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ job_ids: jobIds, tenant_id: tenantValue })
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || data.message || "Unable to start bulk processing");
      }

      setProcessMessage(data.message || "Bulk processing started");
      setLastJobMeta({ jobId: jobIds[jobIds.length - 1], tenantId: tenantValue });
      setLatestJobSummary(null);
      setSummaryError("");
      startBulkSummaryPolling(jobIds, tenantValue);
    } catch (err) {
      setProcessError(err.message || "Bulk processing request failed");
    }
  };

  const handleSingleUpload = async (event) => {
    event.preventDefault();
    setSingleMessage("");
    setSingleError("");
    setSingleResult(null);

    if (!singleFile) {
      setSingleError("Choose a document to upload");
      return;
    }

    setSingleUploading(true);
    const normalizedTenant = singleTenantId.trim() || "default";
    const formData = new FormData();
    formData.append("file", singleFile);
    formData.append("tenant_id", normalizedTenant);
    formData.append("auto_process", String(singleAutoProcess));

    try {
      const response = await fetch(singleWaitForResult ? API_UPLOAD_COMPLETE_URL : API_UPLOAD_URL, {
        method: "POST",
        body: formData
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || data.reason || data.message || "Upload failed");
      }

      setSingleResult(data);
      setSingleMessage(data.message || "Document uploaded");

      const jobId = data.fax_job_id;
      if (jobId) {
        setLastJobMeta({ jobId, tenantId: normalizedTenant });
        setReviewJobId(String(jobId));
        setManualJobId(String(jobId));
        setLookupJobId(String(jobId));
        setExportJobId(String(jobId));
        if (singleAutoProcess && !singleWaitForResult) {
          startSummaryPolling(jobId, normalizedTenant);
        } else if (singleWaitForResult && data.summary) {
          setLatestJobSummary(data.summary);
        }
      }

      setSingleFile(null);
      if (singleFileInputRef.current) {
        singleFileInputRef.current.value = "";
      }
    } catch (err) {
      setSingleError(err.message || "Upload failed");
    } finally {
      setSingleUploading(false);
    }
  };

  const handleManualProcess = async (event) => {
    event.preventDefault();
    setProcessStatusResult(null);
    await triggerProcessing(manualJobId, manualTenantId);
  };

  const handleFetchProcessStatus = async () => {
    const numericId = Number(manualJobId);
    if (!numericId) {
      setProcessError("Enter a valid job ID");
      return;
    }

    setProcessError("");
    try {
      const tenantValue = manualTenantId.trim() || "default";
      const params = new URLSearchParams({ tenant_id: tenantValue }).toString();
      const response = await fetch(`${API_PROCESS_STATUS_URL(numericId)}?${params}`);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to load processing status");
      }

      setProcessStatusResult(data);
    } catch (err) {
      setProcessError(err.message || "Unable to load processing status");
    }
  };

  const handleLookupJob = async (event) => {
    event.preventDefault();
    setLookupResult(null);
    setLookupError("");

    const numericId = Number(lookupJobId);
    if (!numericId) {
      setLookupError("Enter a valid job ID");
      return;
    }

    try {
      const response = await fetch(API_JOB_URL(numericId));
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to load job");
      }

      setLookupResult(data);
    } catch (err) {
      setLookupError(err.message || "Unable to load job");
    }
  };

  const handleLoadJobs = async (event) => {
    if (event) {
      event.preventDefault();
    }

    setJobsLoading(true);
    setJobsError("");

    try {
      const params = new URLSearchParams();
      if (jobsTenantFilter.trim()) {
        params.set("tenant_id", jobsTenantFilter.trim());
      }
      if (jobsStatusFilter.trim()) {
        params.set("status", jobsStatusFilter.trim());
      }

      const query = params.toString();
      const response = await fetch(query ? `${API_JOBS_URL}?${query}` : API_JOBS_URL);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to load jobs");
      }

      setJobsPayload(data);
    } catch (err) {
      setJobsError(err.message || "Unable to load jobs");
    } finally {
      setJobsLoading(false);
    }
  };

  const handleExportCsv = (event) => {
    event.preventDefault();
    const numericId = Number(exportJobId);
    if (!numericId) {
      setProcessError("Enter a job ID to export");
      return;
    }

    const tenantValue = manualTenantId.trim() || "default";
    const params = new URLSearchParams({ tenant_id: tenantValue }).toString();
    window.open(`${API_EXPORT_CSV_URL(numericId)}?${params}`, "_blank", "noopener");
  };

  const loadDatabaseTables = async () => {
    setDbTablesLoading(true);
    setDbError("");

    try {
      const response = await fetch(API_DATABASE_TABLES_URL);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to load database tables");
      }

      const tables = data.tables || [];
      setDbTables(tables);

      if (!selectedDbTable && tables.length > 0) {
        await loadDatabaseRows(tables[0].name, dbLimit, 0);
      }
    } catch (err) {
      setDbError(err.message || "Unable to load database tables");
    } finally {
      setDbTablesLoading(false);
    }
  };

  const loadDatabaseRows = async (tableName, limitValue = dbLimit, offsetValue = dbOffset) => {
    if (!tableName) {
      return;
    }

    setDbRowsLoading(true);
    setDbError("");
    setSelectedDbTable(tableName);
    setDbLimit(Number(limitValue) || 50);
    setDbOffset(Number(offsetValue) || 0);

    try {
      const params = new URLSearchParams({
        limit: String(limitValue || 50),
        offset: String(offsetValue || 0)
      }).toString();
      const response = await fetch(`${API_DATABASE_TABLE_URL(tableName)}?${params}`);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Unable to load table rows");
      }

      setDbRowsPayload(data);
    } catch (err) {
      setDbError(err.message || "Unable to load table rows");
    } finally {
      setDbRowsLoading(false);
    }
  };

  const openDatabaseTab = async () => {
    setActiveTab("database");
    if (dbTables.length === 0) {
      await loadDatabaseTables();
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setStatus("");
    setError("");
    setResult(null);
    setBulkJobs([]);
    setBulkMessage("");
    setBulkError("");

    if (!files || files.length === 0) {
      setError("Choose one or more documents to upload");
      return;
    }

    setUploading(true);

    const normalizedTenant = tenantId.trim() || "default";
    const formData = new FormData();
    files.forEach((item) => formData.append("files", item));
    formData.append("tenant_id", normalizedTenant);

    try {
      const response = await fetch(API_BULK_UPLOAD_URL, {
        method: "POST",
        body: formData
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || data.message || "Upload failed");
      }

      setResult(data);
      setBulkJobs(data.jobs || []);
      setStatus(data.message || "Bulk upload accepted");
      setBulkMessage(`Queued ${data.accepted_count || 0} of ${data.requested_count || files.length} files`);

      const createdJobIds = (data.jobs || [])
        .map((job) => job.fax_job_id)
        .filter(Boolean);

      if (createdJobIds.length) {
        await startBulkProcessing(createdJobIds, normalizedTenant);
      }
    } catch (err) {
      setError(err.message || "Upload failed");
      setBulkError(err.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const handleOpenReviewUI = (event) => {
    if (event) {
      event.preventDefault();
    }

    setReviewMessage("");
    setReviewError("");

    const numericId = Number(reviewJobId);
    if (!numericId) {
      setReviewError("Enter a job ID to open the review UI");
      return;
    }

    const reviewUrl = `${API_BASE_URL}/review-ui/${numericId}`;
    setReviewFrameUrl(reviewUrl);
    setReviewHistory((prev) => {
      const next = [
        { jobId: numericId, url: reviewUrl },
        ...prev.filter((item) => item.jobId !== numericId)
      ];
      return next.slice(0, 6);
    });
    setReviewMessage(`Loaded review interface for #${numericId}`);
  };

  const reviewCount = latestJobSummary?.review_required_count ?? 0;
  const reviewFields = latestJobSummary?.review_required_fields ?? [];

  return (
    <div className="app-shell">
      <div className="hero-card">
        <div>
          <p className="hero-eyebrow">OCR-ArcheAI · Fax Intelligence</p>
          <h1>Control tower for document processing</h1>
          <p className="hero-lead">
            Upload, monitor, and export fax jobs with a calm, transparent interface that mirrors
            how the backend thinks about tenants, jobs, and processing pipelines.
          </p>
        </div>
        <div className="hero-status">
          <span className="status-pill success">Ingress online</span>
          <span className="status-pill neutral">Processing ready</span>
          <span className="status-pill outlined">Storage synced</span>
        </div>
      </div>

      <div className="tab-bar" role="tablist" aria-label="Main sections">
        <button
          type="button"
          className={activeTab === "workspace" ? "tab-button active" : "tab-button"}
          onClick={() => setActiveTab("workspace")}
          role="tab"
          aria-selected={activeTab === "workspace"}
        >
          Workspace
        </button>
        <button
          type="button"
          className={activeTab === "review" ? "tab-button active" : "tab-button"}
          onClick={() => setActiveTab("review")}
          role="tab"
          aria-selected={activeTab === "review"}
        >
          Human review
        </button>
        <button
          type="button"
          className={activeTab === "database" ? "tab-button active" : "tab-button"}
          onClick={openDatabaseTab}
          role="tab"
          aria-selected={activeTab === "database"}
        >
          Database
        </button>
      </div>

      {activeTab === "workspace" && (
        <>
      <div className="grid grid-2">
        <section className="card">
          <div className="card-head">
            <div>
              <p className="hero-eyebrow">Single ingest</p>
              <h2>Upload one document</h2>
            </div>
            <p className="subtle">{singleWaitForResult ? "POST /upload/complete" : "POST /upload"}</p>
          </div>
          <form className="form-grid" onSubmit={handleSingleUpload}>
            <label>
              Tenant ID
              <input
                type="text"
                value={singleTenantId}
                onChange={(event) => setSingleTenantId(event.target.value)}
              />
            </label>
            <label>
              File
              <input
                ref={singleFileInputRef}
                type="file"
                accept=".pdf,.tif,.tiff,.png,.jpg,.jpeg"
                onChange={(event) => setSingleFile(event.target.files?.[0] || null)}
              />
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={singleAutoProcess}
                onChange={(event) => setSingleAutoProcess(event.target.checked)}
              />
              Auto process after upload
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={singleWaitForResult}
                onChange={(event) => setSingleWaitForResult(event.target.checked)}
              />
              Wait for final result
            </label>
            <button type="submit" disabled={singleUploading}>
              {singleUploading ? "Uploading..." : "Upload document"}
            </button>
          </form>
          <div className="status-row">
            {singleMessage && <span className="status-pill info">{singleMessage}</span>}
            {singleError && <span className="status-pill error">{singleError}</span>}
          </div>
          {singleResult && (
            <div className="response-grid">
              <div>
                <strong>Job</strong>
                <p>{singleResult.fax_job_id || singleResult.job_id || "Created"}</p>
              </div>
              <div>
                <strong>Status</strong>
                <p>{singleResult.processing_status || singleResult.status || "ingested"}</p>
              </div>
              <div>
                <strong>File</strong>
                <p>{singleResult.filename || singleResult.original_filename || singleFile?.name || "Uploaded"}</p>
              </div>
            </div>
          )}
        </section>

        <section className="card">
          <div className="card-head">
            <div>
              <p className="hero-eyebrow">Processing</p>
              <h2>Run or inspect a job</h2>
            </div>
            <p className="subtle">POST /process/{"{job_id}"}</p>
          </div>
          <form className="form-grid" onSubmit={handleManualProcess}>
            <label>
              Tenant ID
              <input
                type="text"
                value={manualTenantId}
                onChange={(event) => setManualTenantId(event.target.value)}
              />
            </label>
            <label>
              Job ID
              <input
                type="number"
                min="1"
                value={manualJobId}
                onChange={(event) => setManualJobId(event.target.value)}
              />
            </label>
            <button type="submit">Start processing</button>
            <button type="button" onClick={handleFetchProcessStatus}>Check status</button>
          </form>
          <form className="form-grid slim" onSubmit={handleExportCsv}>
            <label>
              Export Job ID
              <input
                type="number"
                min="1"
                value={exportJobId}
                onChange={(event) => setExportJobId(event.target.value)}
              />
            </label>
            <button type="submit">Export CSV</button>
          </form>
          <div className="status-row">
            {processMessage && <span className="status-pill info">{processMessage}</span>}
            {processError && <span className="status-pill error">{processError}</span>}
          </div>
          {processStatusResult && (
            <div className="summary-grid">
              <div className="summary-item">
                <span className="summary-label">Status</span>
                <span className="summary-value">{processStatusResult.status}</span>
              </div>
              <div className="summary-item">
                <span className="summary-label">Pages</span>
                <span className="summary-value">{processStatusResult.total_pages}</span>
              </div>
              <div className="summary-item">
                <span className="summary-label">OCR pages</span>
                <span className="summary-value">{processStatusResult.ocr_pages}</span>
              </div>
            </div>
          )}
        </section>
      </div>

      <div className="grid">
        <section className="card">
          <div className="card-head">
            <div>
              <p className="hero-eyebrow">Jobs</p>
              <h2>Lookup and list jobs</h2>
            </div>
            <p className="subtle">GET /jobs</p>
          </div>
          <form className="form-grid slim" onSubmit={handleLookupJob}>
            <label>
              Job ID
              <input
                type="number"
                min="1"
                value={lookupJobId}
                onChange={(event) => setLookupJobId(event.target.value)}
              />
            </label>
            <button type="submit">Lookup</button>
          </form>
          {lookupError && <span className="status-pill error">{lookupError}</span>}
          {lookupResult && (
            <div className="summary-grid">
              <div className="summary-item">
                <span className="summary-label">Job</span>
                <span className="summary-value">{lookupResult.fax_job_id}</span>
              </div>
              <div className="summary-item">
                <span className="summary-label">Tenant</span>
                <span className="summary-value">{lookupResult.tenant_id}</span>
              </div>
              <div className="summary-item">
                <span className="summary-label">Status</span>
                <span className="summary-value">{lookupResult.status}</span>
              </div>
              <div className="summary-item">
                <span className="summary-label">Review</span>
                <span className="summary-value">{lookupResult.review_needed ? "Required" : "No"}</span>
              </div>
            </div>
          )}
          <form className="form-grid" onSubmit={handleLoadJobs}>
            <label>
              Tenant filter
              <input
                type="text"
                value={jobsTenantFilter}
                onChange={(event) => setJobsTenantFilter(event.target.value)}
                placeholder="optional"
              />
            </label>
            <label>
              Status filter
              <input
                type="text"
                value={jobsStatusFilter}
                onChange={(event) => setJobsStatusFilter(event.target.value)}
                placeholder="optional"
              />
            </label>
            <button type="submit" disabled={jobsLoading}>
              {jobsLoading ? "Loading..." : "Load jobs"}
            </button>
          </form>
          {jobsError && <span className="status-pill error">{jobsError}</span>}
          {jobsPayload?.jobs?.length > 0 && (
            <div className="jobs-table">
              {jobsPayload.jobs.slice(0, 12).map((job) => (
                <div className="jobs-row" key={job.fax_job_id}>
                  <p>
                    <span className="jobs-label">Job</span>
                    {job.fax_job_id}
                  </p>
                  <p>
                    <span className="jobs-label">Tenant</span>
                    {job.tenant_id}
                  </p>
                  <p>
                    <span className="jobs-label">Status</span>
                    {job.status || "unknown"}
                  </p>
                  <p>
                    <span className="jobs-label">Review</span>
                    {job.review_needed ? "Required" : "No"}
                  </p>
                  <p>
                    <span className="jobs-label">Created</span>
                    {job.created_at || "pending"}
                  </p>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="card">
          <div className="card-head">
            <div>
              <p className="hero-eyebrow">Upload</p>
              <h2>Upload fax batch</h2>
            </div>
            <p className="subtle">POST /upload/bulk</p>
          </div>
          <form className="form-grid" onSubmit={handleSubmit}>
            <label>
              Tenant ID
              <input
                type="text"
                value={tenantId}
                onChange={(event) => setTenantId(event.target.value)}
              />
            </label>
            <div className="file-picker-stack">
              <label>
                File
                <input
                  ref={fileInputRef}
                  type="file"
                  name="files"
                  accept=".pdf,.tif,.tiff,.png,.jpg,.jpeg"
                  onChange={(event) => {
                    const incoming = Array.from(event.target.files || []);
                    if (incoming.length) {
                      setFiles((prev) => [...prev, ...incoming]);
                    }
                    if (fileInputRef.current) {
                      fileInputRef.current.value = "";
                    }
                  }}
                />
              </label>
              <button
                type="button"
                onClick={() => fileInputRef.current && fileInputRef.current.click()}
              >
                Add another file
              </button>
            </div>
            <button type="submit" disabled={uploading}>
              {uploading ? "Uploading…" : "Upload documents"}
            </button>
          </form>
          <div className="status-row">
            {status && <span className="status-pill info">{status}</span>}
            {error && <span className="status-pill error">{error}</span>}
          </div>
          {files.length > 0 && (
            <div className="subtle" style={{ display: "grid", gap: "4px" }}>
              <div>Selected {files.length} file{files.length === 1 ? "" : "s"}:</div>
              <div style={{ display: "grid", gap: "4px" }}>
                {files.map((f, idx) => (
                  <div key={`${f.name}-${idx}`} style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <span>{f.name}</span>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => setFiles((prev) => prev.filter((_, i) => i !== idx))}
                    >
                      remove
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
          {bulkMessage && <div className="subtle">{bulkMessage}</div>}
          {bulkError && <span className="status-pill error">{bulkError}</span>}
          {bulkJobs.length > 0 && (
            <div style={{ display: "grid", gap: "12px", marginTop: "12px" }}>
              {bulkJobs.map((job) => (
                <div
                  className="card"
                  style={{ padding: "12px" }}
                  key={`${job.filename}-${job.fax_job_id || job.status}`}
                >
                  <div className="summary-item" style={{ marginBottom: "8px" }}>
                    <span className="summary-label">{job.filename || "File"}</span>
                    <span className="summary-value">
                      {job.fax_job_id ? `Job ${job.fax_job_id}` : "No job"}
                      {job.status ? ` · ${job.status}` : ""}
                    </span>
                  </div>
                  {job.fax_job_id && bulkSummaries[job.fax_job_id] && (
                    <div className="subtle" style={{ marginTop: "6px" }}>
                      {bulkSummaries[job.fax_job_id].error ? (
                        <span className="status-pill error">{bulkSummaries[job.fax_job_id].error}</span>
                      ) : (
                        <>
                          <span className="status-pill neutral">{bulkSummaries[job.fax_job_id].status || "processing"}</span>
                          {bulkSummaries[job.fax_job_id].status_message && (
                            <div>{bulkSummaries[job.fax_job_id].status_message}</div>
                          )}
                          {bulkSummaries[job.fax_job_id].total_pages != null && (
                            <div>Total pages: {bulkSummaries[job.fax_job_id].total_pages}</div>
                          )}
                          {bulkSummaries[job.fax_job_id].review_required_count > 0 && (
                            <div style={{ marginTop: "6px", color: "#b00020" }}>
                              ⚠️ Agree-to-finalize mode: Review required for {bulkSummaries[job.fax_job_id].review_required_count} field{bulkSummaries[job.fax_job_id].review_required_count === 1 ? "" : "s"}
                              {bulkSummaries[job.fax_job_id].review_required_fields?.length ? (
                                <div className="review-required-list" style={{ marginTop: "4px", display: "flex", flexWrap: "wrap", gap: "6px" }}>
                                  {bulkSummaries[job.fax_job_id].review_required_fields.map((field) => (
                                    <span className="status-pill outlined" style={{ borderColor: "#b00020", color: "#b00020" }} key={`${job.fax_job_id}-rr-${field}`}>
                                      {field}
                                    </span>
                                  ))}
                                </div>
                              ) : null}
                            </div>
                          )}
                          {bulkFields[job.fax_job_id] && (
                            <div className="summary-fields" style={{ marginTop: "8px" }}>
                              {Object.entries(bulkFields[job.fax_job_id]).map(([key, value]) => (
                                <div className="summary-field" key={`${job.fax_job_id}-${key}`}>
                                  <strong>{key.replace(/_/g, " ")}</strong>
                                  <p>{value}</p>
                                </div>
                              ))}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  )}
                  {job.error && (
                    <span className="status-pill error" style={{ marginTop: "6px" }}>
                      {job.error}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
          {lastJobMeta && (
            <div className="processing-card">
              <div className="progress-track">
                <div className="progress-fill" style={{ width: "100%" }} />
              </div>
              <p className="status-text">
                {latestJobSummary ? (
                  <>
                    <span className="summary-icon">
                      {latestJobSummary.status_icon || "✅"}
                    </span>
                    {latestJobSummary.status_message || latestJobSummary.status || "Status ready"}
                  </>
                ) : (
                  <>
                    <span className="summary-icon">⚙️</span>
                    {processMessage || "Processing started"}
                  </>
                )}
              </p>
              <p className="status-subtext">
                Job {lastJobMeta.jobId} · Tenant {lastJobMeta.tenantId}
              </p>
              {latestJobSummary && (
                <div className="summary-grid">
                  <div className="summary-item">
                    <span className="summary-label">Status</span>
                    <span className="summary-value">{latestJobSummary.status || "—"}</span>
                  </div>
                  <div className="summary-item">
                    <span className="summary-label">Review</span>
                    <span className="summary-value">
                      {latestJobSummary.review_needed ? "Required" : "Not needed"}
                    </span>
                  </div>
                  <div className="summary-item">
                    <span className="summary-label">Human edits</span>
                    <span className="summary-value">
                      {latestJobSummary.has_human_modifications ? "Detected" : "None"}
                    </span>
                  </div>
                  <div className="summary-item">
                    <span className="summary-label">Total pages</span>
                    <span className="summary-value">
                      {latestJobSummary.total_pages ?? "—"}
                    </span>
                  </div>
                  <div className="summary-item">
                    <span className="summary-label">Finalized</span>
                    <span className="summary-value">
                      {latestJobSummary.finalized_at || "Pending"}
                    </span>
                  </div>
                  <div className="summary-item">
                    <span className="summary-label">Modified fields</span>
                    <span className="summary-value">
                      {latestJobSummary.modified_fields || "None"}
                    </span>
                  </div>
                </div>
              )}
              {latestJobSummary?.key_fields?.length > 0 && (
                <div className="summary-fields">
                  {latestJobSummary.key_fields.map((field) => (
                    <div className="summary-field" key={`${field.label}-${field.value}`}>
                      <strong>{field.label}</strong>
                      <p>{field.value}</p>
                    </div>
                  ))}
                </div>
              )}
              {reviewCount > 0 && (
                <div className="review-required-block">
                  <p className="review-required-message">
                    ⚠️ Agree-to-finalize mode: Review required for {reviewCount} field
                    {reviewCount > 1 ? "s" : ""}.
                  </p>
                  <div className="review-required-list">
                    {reviewFields.map((field) => (
                      <span className="review-required-chip" key={field}>
                        {field}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {(summaryError || processError) && (
                <span className={`status-pill ${summaryError ? "warning" : "error"}`}>
                  {summaryError || processError}
                </span>
              )}
            </div>
          )}
        </section>
      </div>
        </>
      )}

      {activeTab === "database" && (
        <div className="grid database-grid">
          <section className="card">
            <div className="card-head">
              <div>
                <p className="hero-eyebrow">Database</p>
                <h2>Tables and rows</h2>
              </div>
              <p className="subtle">GET /database/tables</p>
            </div>
            <div className="database-toolbar">
              <button type="button" className="ghost dark" onClick={loadDatabaseTables} disabled={dbTablesLoading}>
                {dbTablesLoading ? "Refreshing..." : "Refresh tables"}
              </button>
              {selectedDbTable && (
                <span className="status-pill info">
                  {selectedDbTable}
                </span>
              )}
              {dbError && <span className="status-pill error">{dbError}</span>}
            </div>
            <div className="database-layout">
              <aside className="database-sidebar">
                {dbTables.length === 0 && !dbTablesLoading && (
                  <p className="subtle">No tables loaded yet.</p>
                )}
                {dbTables.map((table) => (
                  <button
                    type="button"
                    className={selectedDbTable === table.name ? "table-button active" : "table-button"}
                    key={table.name}
                    onClick={() => loadDatabaseRows(table.name, dbLimit, 0)}
                  >
                    <span>{table.name}</span>
                    <small>{table.row_count} rows</small>
                  </button>
                ))}
              </aside>
              <div className="database-main">
                {dbRowsPayload ? (
                  <>
                    <div className="database-controls">
                      <label>
                        Limit
                        <input
                          type="number"
                          min="1"
                          max="200"
                          value={dbLimit}
                          onChange={(event) => setDbLimit(Number(event.target.value))}
                        />
                      </label>
                      <label>
                        Offset
                        <input
                          type="number"
                          min="0"
                          value={dbOffset}
                          onChange={(event) => setDbOffset(Number(event.target.value))}
                        />
                      </label>
                      <button
                        type="button"
                        onClick={() => loadDatabaseRows(selectedDbTable, dbLimit, dbOffset)}
                        disabled={dbRowsLoading}
                      >
                        {dbRowsLoading ? "Loading..." : "Load rows"}
                      </button>
                    </div>
                    <div className="subtle">
                      Showing {dbRowsPayload.rows.length} of {dbRowsPayload.total} rows
                    </div>
                    <div className="extraction-table-wrapper">
                      <table className="extraction-table">
                        <thead>
                          <tr>
                            {dbRowsPayload.columns.map((column) => (
                              <th key={column}>{column}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {dbRowsPayload.rows.map((row, rowIndex) => (
                            <tr key={`${dbRowsPayload.table}-${rowIndex}`}>
                              {dbRowsPayload.columns.map((column) => (
                                <td key={`${rowIndex}-${column}`}>
                                  {row[column] === null || row[column] === undefined
                                    ? <span>null</span>
                                    : typeof row[column] === "object"
                                      ? JSON.stringify(row[column])
                                      : String(row[column])}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : (
                  <p className="subtle">Choose a table to inspect rows.</p>
                )}
              </div>
            </div>
          </section>
        </div>
      )}

      {activeTab === "review" && (
      <div className="grid review-tab-grid">
        <section className="card">
          <div className="card-head">
            <div>
              <p className="hero-eyebrow">Human review</p>
              <h2>Launch review UI</h2>
            </div>
            <p className="subtle">GET /review-ui/{"{job_id}"}</p>
          </div>
          <form className="form-grid" onSubmit={handleOpenReviewUI}>
            <label>
              Job ID
              <input
                type="number"
                min="1"
                value={reviewJobId}
                onChange={(event) => setReviewJobId(event.target.value)}
              />
            </label>
            <button type="submit">Open below</button>
          </form>
          <div className="status-row">
            {reviewMessage && <span className="status-pill info">{reviewMessage}</span>}
            {reviewError && <span className="status-pill error">{reviewError}</span>}
          </div>
          {reviewHistory.length > 0 && (
            <div className="review-history">
              {reviewHistory.map((item) => (
                <button
                  type="button"
                  className={reviewFrameUrl === item.url ? "review-chip active" : "review-chip"}
                  key={item.jobId}
                  onClick={() => {
                    setReviewJobId(String(item.jobId));
                    setReviewFrameUrl(item.url);
                    setReviewMessage(`Loaded review interface for #${item.jobId}`);
                    setReviewError("");
                  }}
                >
                  Job #{item.jobId}
                </button>
              ))}
            </div>
          )}
          {reviewFrameUrl ? (
            <div className="embedded-review">
              <iframe
                title={`Human review job ${reviewJobId}`}
                src={reviewFrameUrl}
              />
            </div>
          ) : (
            <div className="embedded-review-placeholder">
              Enter a job ID to load the review interface here.
            </div>
          )}
        </section>
      </div>
      )}
    </div>
  );
}

export default App;
