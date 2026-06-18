"""
OCR engine with evidence layer (bounding boxes)
"""
import os
import sys
from pathlib import Path

# Fix imports - ensure project root is in path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Disable OneDNN and PIR to avoid compatibility issues on Windows with PaddlePaddle 3.0
os.environ['FLAGS_use_mkldnn'] = '0'
os.environ['FLAGS_use_onednn'] = '0'
os.environ['FLAGS_enable_pir_api'] = '0'
os.environ['FLAGS_enable_pir_in_executor'] = '0'
os.environ['FLAGS_enable_pir'] = '0'
os.environ['FLAGS_use_legacy_executor'] = '1'

from paddleocr import PaddleOCR
from PIL import Image
from typing import List, Dict, Any
import json

from fax_processing.config.settings import settings
from fax_processing.core.storage import storage
from fax_processing.models.schemas import OCRToken, BoundingBox, PageMetadata


class OCREngine:
    """PaddleOCR wrapper with evidence layer support"""
    
    def __init__(self):
        self._ocr = None  # Lazy initialization
    
    @property
    def ocr(self):
        """Lazy-load PaddleOCR with PPv3 models"""
        if self._ocr is None:
            print(f"🔧 Initializing PaddleOCR PPv3 (CPU-optimized, no angle cls, lightweight)...")
            self._ocr = PaddleOCR(
                lang=settings.OCR_LANG,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                det_model_dir="/root/.paddlex/official_models/PP-OCRv3_server_det",
                rec_model_dir="/root/.paddlex/official_models/en_PP-OCRv3_mobile_rec",
            )
            print(f"✅ PaddleOCR PPv3 models loaded successfully")
        return self._ocr
    
    def process_page(self, job_id: str, tenant_id: str, page_num: int, 
                    page_image_path: Path) -> PageMetadata:
        """
        Run OCR on a page and extract tokens with bounding boxes
        
        Returns: PageMetadata with OCR tokens
        """
        # Load image to get dimensions
        img = Image.open(page_image_path)
        width, height = img.size
        
        # Run OCR on all pages (blank page skipping disabled for now)
        results = self.ocr.ocr(str(page_image_path))
        
        # Parse results
        tokens = self._parse_ocr_results(results, page_num)
        
        # Create page metadata
        page_meta = PageMetadata(
            page_id=f"{job_id}_page_{page_num:04d}",
            page_num=page_num,
            job_id=job_id,
            width=width,
            height=height,
            dpi=settings.OCR_DPI,
            file_path=str(page_image_path),
            ocr_tokens=tokens
        )
        
        # Save raw OCR results as evidence
        raw_ocr_data = {
            "page_num": page_num,
            "raw_results": self._serialize_results(results),
            "total_tokens": len(tokens)
        }
        storage.save_ocr_results(job_id, tenant_id, page_num, raw_ocr_data)
        
        # Save page metadata
        storage.save_page_metadata(page_meta, tenant_id)
        
        return page_meta
    
    
    def _parse_ocr_results(self, results: List, page_num: int) -> List[OCRToken]:
        """Parse PaddleOCR results into OCRToken objects"""
        tokens = []
        
        if not results:
            return tokens
        
        result = results[0]
        
        # New PaddleOCR format returns OCRResult object (dict-like)
        # Access via: rec_texts (list of strings), rec_scores (list of floats), rec_polys (list of numpy arrays)
        if 'rec_texts' in result and 'rec_scores' in result and 'rec_polys' in result:
            rec_texts = result['rec_texts']
            rec_scores = result['rec_scores']
            rec_polys = result['rec_polys']
            
            for text, score, poly in zip(rec_texts, rec_scores, rec_polys):
                if not text or poly is None:
                    continue
                
                # poly is a numpy array of shape (4, 2) representing [x, y] for each corner
                # Convert to list if needed
                if hasattr(poly, 'tolist'):
                    poly_points = poly.tolist()
                else:
                    poly_points = list(poly)
                
                if len(poly_points) >= 4:
                    bbox = BoundingBox(
                        x1=float(poly_points[0][0]),
                        y1=float(poly_points[0][1]),
                        x2=float(poly_points[1][0]),
                        y2=float(poly_points[1][1]),
                        x3=float(poly_points[2][0]),
                        y3=float(poly_points[2][1]),
                        x4=float(poly_points[3][0]),
                        y4=float(poly_points[3][1])
                    )
                    
                    token = OCRToken(
                        text=text,
                        confidence=float(score),
                        bbox=bbox,
                        page_num=page_num
                    )
                    
                    tokens.append(token)
        
        # Fallback to old format (list of lists)
        elif isinstance(result, list):
            for line in result:
                if not line or len(line) < 2:
                    continue
                
                # PaddleOCR old format: [bbox, (text, confidence)]
                bbox_points = line[0]
                text_info = line[1]
                
                text = text_info[0] if isinstance(text_info, (list, tuple)) else text_info
                confidence = text_info[1] if isinstance(text_info, (list, tuple)) and len(text_info) > 1 else 0.0
                
                # Create BoundingBox
                bbox = BoundingBox(
                    x1=float(bbox_points[0][0]),
                    y1=float(bbox_points[0][1]),
                    x2=float(bbox_points[1][0]),
                    y2=float(bbox_points[1][1]),
                    x3=float(bbox_points[2][0]),
                    y3=float(bbox_points[2][1]),
                    x4=float(bbox_points[3][0]),
                    y4=float(bbox_points[3][1])
                )
                
                token = OCRToken(
                    text=text,
                    confidence=float(confidence),
                    bbox=bbox,
                    page_num=page_num
                )
                
                tokens.append(token)
        
        return tokens
    
    def _serialize_results(self, results: Any) -> Dict:
        """Serialize OCR results for JSON storage (handles numpy conversion)"""
        import numpy as np
        
        def numpy_to_native(obj):
            """Recursively convert numpy types to native Python types"""
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, np.floating):
                return float(obj)
            elif isinstance(obj, dict):
                return {k: numpy_to_native(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [numpy_to_native(item) for item in obj]
            else:
                return obj
        
        if not results:
            return {}
        
        result = results[0]
        
        # New PaddleOCR format
        if hasattr(result, 'rec_texts') or (isinstance(result, dict) and 'rec_texts' in result):
            try:
                rec_texts = result['rec_texts'] if isinstance(result, dict) else result.rec_texts
                rec_scores = result['rec_scores'] if isinstance(result, dict) else result.rec_scores
                rec_polys = result['rec_polys'] if isinstance(result, dict) else result.rec_polys
                
                # Convert all numpy arrays to native Python types
                polys_serialized = [numpy_to_native(poly) for poly in rec_polys]
                confidences = [numpy_to_native(s) for s in rec_scores]
                
                serialized = {
                    "format": "paddleocr_new",
                    "text_count": len(rec_texts),
                    "texts": list(rec_texts),
                    "confidences": confidences,
                    "polygons": polys_serialized
                }
                return serialized
            except Exception as e:
                return {"format": "error", "error": str(e)}
        
        # Old PaddleOCR format
        elif isinstance(result, list):
            page_data = []
            for line in result:
                if line and len(line) >= 2:
                    page_data.append({
                        "bbox": numpy_to_native(line[0]),
                        "text": line[1][0] if isinstance(line[1], (list, tuple)) else line[1],
                        "confidence": float(line[1][1]) if isinstance(line[1], (list, tuple)) and len(line[1]) > 1 else 0.0
                    })
            return {"format": "paddleocr_old", "data": page_data}
        
        return {}


# Singleton instance
ocr_engine = OCREngine()
