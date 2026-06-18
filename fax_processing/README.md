# Prior Authorization Extraction System

## MVP - Phase 1: Core Pipeline

Production-ready system for extracting structured Prior Authorization data from faxes.

### Current Phase: Pipeline Foundation
- ✅ Fax ingestion API
- ✅ Page splitting & preprocessing
- ✅ OCR with bounding boxes (evidence layer)
- ✅ Job management & storage

### Architecture
```
pa-extraction/
├── api/                    # FastAPI endpoints
├── core/                   # Business logic
│   ├── ingestion.py       # Fax intake, SHA256, job creation
│   ├── preprocessing.py   # Page split, deskew, denoise
│   ├── ocr_engine.py      # PaddleOCR with bbox evidence
│   └── storage.py         # File system storage management
├── models/                 # Data models (Pydantic)
├── config/                 # Configuration
└── storage/                # Local file storage (jobs, pages, results)
```

### Setup
```bash
pip install -r requirements.txt
python main.py
```

### API Usage
```bash
# Ingest fax
curl -X POST http://localhost:8000/api/v1/fax/ingest \
  -F "file=@fax.pdf" \
  -F "tenant_id=tenant_001"

# Get job status
curl http://localhost:8000/api/v1/fax/job/{job_id}
```

### Next Phases
- Phase 2: Template matching (Anthem, CareSource, etc.)
- Phase 3: Validation & confidence scoring
- Phase 4: VLM integration (Donut)
