"""
Hybrid Document Classifier for Prior Authorization Detection

This module implements a hybrid approach combining:
- PyMuPDF for fast digital PDF text extraction
- TinyOCR (lightweight PaddleOCR) for scanned document OCR
- Smart multi-page processing with confidence-based early stopping
- Template matching against 8 major healthcare payers
"""

import logging
import time
import re
import os
import tempfile
import uuid
import cv2
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None

from fax_ingress.config.authorization_templates import (
    AUTHORIZATION_TEMPLATES,
    COMMON_PA_KEYWORDS,
    NON_PA_KEYWORDS,
)

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Structured classification result"""
    document_type: str  # "prior_authorization" or "other"
    confidence: float  # 0.0-1.0
    matched_payer: Optional[str] = None
    extraction_method: str = "unknown"  # "pymupdf" or "tinyocr"
    pages_processed: int = 0
    total_pages: int = 0
    processing_time_ms: float = 0.0
    keywords_found: Optional[List[str]] = None
    company_names_found: Optional[List[str]] = None
    raw_confidence_scores: Optional[Dict[str, float]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return asdict(self)


class HybridDocumentClassifier:
    """
    Hybrid classifier combining PyMuPDF and TinyOCR for document classification.
    
    Workflow:
    1. Attempt fast PyMuPDF extraction on entire PDF
    2. If low confidence or extraction fails, use TinyOCR on first N pages
    3. Stop processing when confidence >= 0.85 (configurable)
    4. Match against 8 healthcare payer templates
    """
    
    def __init__(
        self,
        confidence_threshold: float = 0.85,
        max_ocr_pages: int = 3,
        use_pymupdf: bool = True,
        use_tinyocr: bool = True,
        pymupdf_early_stop: float = 0.60,
    ):
        """
        Initialize the hybrid classifier.
        
        Args:
            confidence_threshold: Stop processing when confidence >= this value (NOT USED - for upload endpoint)
            max_ocr_pages: Maximum pages to process with TinyOCR
            use_pymupdf: Enable PyMuPDF extraction
            use_tinyocr: Enable TinyOCR extraction
            pymupdf_early_stop: Return from PyMuPDF if >= this confidence (avoids OCR on digital PDFs)
        """
        self.pymupdf_early_stop = pymupdf_early_stop  # For PyMuPDF: 0.60 = reasonable PA
        self.pymupdf_early_stop = pymupdf_early_stop  # For PyMuPDF: 0.60 = reasonable PA
        self.confidence_threshold = confidence_threshold  # For upload endpoint  
        self.max_ocr_pages = max_ocr_pages
        self.use_pymupdf = use_pymupdf and fitz is not None
        self.use_tinyocr = use_tinyocr and PaddleOCR is not None
        
        # Initialize OCR engine if available
        self.ocr_engine = None
        if self.use_tinyocr:
            try:
                self.ocr_engine = PaddleOCR(
                    lang='en',
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                    det_model_dir="/root/.paddlex/official_models/PP-OCRv3_server_det",
                    rec_model_dir="/root/.paddlex/official_models/en_PP-OCRv3_mobile_rec",
                )
                logger.info("PaddleOCR PPv3 classifier engine initialized (lightweight)")
            except Exception as e:
                logger.warning(f"Failed to initialize PaddleOCR: {e}. Falling back to PyMuPDF only.")
                self.use_tinyocr = False
        
        if not self.use_pymupdf and not self.use_tinyocr:
            logger.warning("Neither PyMuPDF nor Tesseract/pytesseract available. Install pymupdf and pytesseract.")
    
    def _preprocess_image(self, image_path: str) -> np.ndarray:
        """
        Preprocess image for better OCR results.
        Based on: https://github.com/janusquadrifrons/tinyOCR
        
        Steps:
        1. Read image with OpenCV
        2. Resize 2x for better detail
        3. Denoise with median blur
        4. Adjust brightness/contrast based on image brightness
        5. Convert to grayscale
        
        Args:
            image_path: Path to image file
            
        Returns:
            Preprocessed grayscale image (numpy array)
        """
        try:
            # Read image
            image = cv2.imread(image_path)
            
            if image is None:
                logger.error(f"Cannot read image: {image_path}")
                return None
            
            # Step 1: Resize 2x for better OCR
            image = cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            logger.debug(f"Resized image to {image.shape}")
            
            # Step 2: Denoise using median blur
            image = cv2.medianBlur(image, 3)
            logger.debug("Applied median blur denoising")
            
            # Step 3: Detect brightness and adjust contrast/brightness
            # Convert to grayscale temporarily to measure brightness
            gray_for_brightness = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            mean_brightness = cv2.mean(gray_for_brightness)[0]
            
            logger.debug(f"Image brightness: {mean_brightness:.1f}")
            
            # Adaptive contrast/brightness adjustment
            if mean_brightness < 100:
                # Dark image - increase contrast and brightness
                alpha = 1.5
                beta = 50
                logger.debug("Dark image detected - increasing contrast and brightness")
            elif mean_brightness > 150:
                # Bright image - decrease brightness, keep contrast normal
                alpha = 1.0
                beta = -50
                logger.debug("Bright image detected - decreasing brightness")
            else:
                # Normal brightness
                alpha = 1.0
                beta = 0
                logger.debug("Normal brightness - no adjustment needed")
            
            # Apply contrast/brightness adjustment
            image = cv2.convertScaleAbs(image, alpha=alpha, beta=beta)
            
            # Step 4: Apply histogram equalization for better detail
            gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            gray_image = cv2.equalizeHist(gray_image)
            
            logger.debug("Image preprocessing complete")
            return gray_image
        
        except Exception as e:
            logger.error(f"Image preprocessing failed: {e}")
            # Return image as-is if preprocessing fails
            try:
                image = cv2.imread(image_path)
                return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image is not None else None
            except:
                return None
    
    def classify(self, pdf_path: str) -> ClassificationResult:
        """
        Classify a document as prior authorization or other.
        
        Workflow:
        1. Try PyMuPDF (fast, for digital PDFs with text layers)
           - Return early if confidence >= 0.60 (reasonable PA doc)
        2. If PyMuPDF fails/low confidence, fallback to TinyOCR (handles scanned PDFs)
           - More accurate for image-based PDFs
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            ClassificationResult with document type, confidence, and metadata
        """
        start_time = time.time()
        result = None
        
        logger.info(f"Starting classification - PyMuPDF enabled: {self.use_pymupdf}, TinyOCR enabled: {self.use_tinyocr}")
        
        try:
            # Step 1: Try PyMuPDF for fast digital PDF extraction
            if self.use_pymupdf:
                pymupdf_result = self._classify_with_pymupdf(pdf_path)
                
                if pymupdf_result:
                    logger.info(
                        f"PyMuPDF result: {pymupdf_result.document_type} "
                        f"(confidence: {pymupdf_result.confidence:.2f})"
                    )
                    
                    # Return if GOOD confidence from PyMuPDF (digital PDF with clear text)
                    if pymupdf_result.confidence >= self.pymupdf_early_stop:
                        pymupdf_result.processing_time_ms = (time.time() - start_time) * 1000
                        logger.info(
                            f"✓ Digital PDF classification (PyMuPDF): {pymupdf_result.document_type} "
                            f"(confidence: {pymupdf_result.confidence:.2f}) - No OCR needed"
                        )
                        return pymupdf_result
                    else:
                        logger.info(
                            f"PyMuPDF confidence low ({pymupdf_result.confidence:.2f}), "
                            f"likely scanned PDF - using OCR fallback"
                        )
                else:
                    logger.info(
                        "PyMuPDF extraction failed (scanned/image PDF detected), "
                        "switching to TinyOCR..."
                    )
            
            # Step 2: Use TinyOCR for scanned documents or low confidence
            if self.use_tinyocr:
                logger.info("Starting TinyOCR processing (may take 2-5 seconds for scanned PDFs)...")
                result = self._classify_with_tinyocr(pdf_path)
                
                if result is None:
                    logger.warning("TinyOCR failed - returning low confidence result")
                    result = ClassificationResult(
                        document_type="other",
                        confidence=0.0,
                        extraction_method="tinyocr",
                        processing_time_ms=(time.time() - start_time) * 1000,
                    )
                else:
                    result.processing_time_ms = (time.time() - start_time) * 1000
                    logger.info(
                        f"✓ Scanned PDF classification (TinyOCR): {result.document_type} "
                        f"(confidence: {result.confidence:.2f})"
                    )
            else:
                logger.error("TinyOCR not available - cannot process scanned PDF")
            
            if result is None:
                result = ClassificationResult(
                    document_type="other",
                    confidence=0.0,
                    processing_time_ms=(time.time() - start_time) * 1000,
                )
            
            return result
        
        except Exception as e:
            logger.error(f"Error classifying document: {e}", exc_info=True)
            return ClassificationResult(
                document_type="other",
                confidence=0.0,
                processing_time_ms=(time.time() - start_time) * 1000,
            )
    
    def _classify_with_pymupdf(self, pdf_path: str) -> Optional[ClassificationResult]:
        """
        Extract text using PyMuPDF and classify.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            ClassificationResult or None if extraction fails
        """
        try:
            pdf_document = fitz.open(pdf_path)
            total_pages = len(pdf_document)
            
            # Extract text from first page as quick check
            full_text = ""
            for page_num in range(total_pages):
                page = pdf_document[page_num]
                page_text = page.get_text()
                full_text += page_text
                
                # Early stopping: check confidence every few pages
                if page_num > 0 and page_num % 2 == 0:
                    temp_result = self._analyze_text(
                        full_text,
                        extraction_method="pymupdf",
                        pages_processed=page_num + 1,
                        total_pages=total_pages,
                    )
                    if temp_result.confidence >= self.confidence_threshold:
                        pdf_document.close()
                        return temp_result
            
            pdf_document.close()
            
            # Final result with all pages
            result = self._analyze_text(
                full_text,
                extraction_method="pymupdf",
                pages_processed=total_pages,
                total_pages=total_pages,
            )
            result.pages_processed = total_pages
            result.total_pages = total_pages
            
            return result
        
        except Exception as e:
            logger.warning(f"PyMuPDF extraction failed: {e}")
            return None
    
    def _classify_with_tinyocr(self, pdf_path: str) -> Optional[ClassificationResult]:
        """
        Extract text using TinyOCR approach with PaddleOCR.
        
        Uses exact TinyOCR preprocessing pipeline:
        1. Resize 2x
        2. Denoise with median blur
        3. Adaptive brightness/contrast
        4. Histogram equalization
        5. PaddleOCR extraction
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            ClassificationResult or None if extraction fails
        """
        pdf_document = None
        try:
            if not fitz:
                logger.error("PyMuPDF required for TinyOCR mode")
                return None
            
            if not self.ocr_engine:
                logger.error("PaddleOCR engine not initialized")
                return None
                
            pdf_document = fitz.open(pdf_path)
            total_pages = len(pdf_document)
            full_text = ""
            
            logger.info(f"TinyOCR: Processing {total_pages} total pages (max {self.max_ocr_pages})")
            
            # Process up to max_ocr_pages
            pages_to_process = min(self.max_ocr_pages, total_pages)
            
            for page_num in range(pages_to_process):
                try:
                    logger.info(f"Page {page_num}: Converting PDF page to image...")
                    page = pdf_document[page_num]
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom
                    
                    # Save temporary image
                    temp_dir = tempfile.gettempdir()
                    unique_id = str(uuid.uuid4())[:8]
                    temp_image_path = os.path.join(temp_dir, f"ocr_page_{page_num}_{unique_id}.png")
                    pix.save(temp_image_path)
                    logger.info(f"Page {page_num}: Saved image to {temp_image_path}")
                    
                    # === TinyOCR PREPROCESSING ===
                    logger.info(f"Page {page_num}: Running TinyOCR preprocessing...")
                    
                    # Read image
                    image = cv2.imread(temp_image_path)
                    if image is None:
                        logger.warning(f"Page {page_num}: Cannot read image")
                        continue
                    
                    # Step 1: Resize 2x
                    image = cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                    logger.debug(f"Page {page_num}: Resized image")
                    
                    # Step 2: Denoise
                    image = cv2.medianBlur(image, 3)
                    logger.debug(f"Page {page_num}: Applied median blur denoising")
                    
                    # Step 3: Adaptive brightness/contrast
                    gray_for_brightness = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                    mean_brightness = cv2.mean(gray_for_brightness)[0]
                    logger.debug(f"Page {page_num}: Mean brightness = {mean_brightness:.1f}")
                    
                    if mean_brightness < 100:
                        alpha = 1.5
                        beta = 50
                    elif mean_brightness > 150:
                        alpha = 1.0
                        beta = -50
                    else:
                        alpha = 1.0
                        beta = 0
                    
                    image = cv2.convertScaleAbs(image, alpha=alpha, beta=beta)
                    logger.debug(f"Page {page_num}: Applied brightness/contrast adjustment (alpha={alpha}, beta={beta})")
                    
                    # Step 4: Grayscale + Histogram equalization
                    gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                    gray_image = cv2.equalizeHist(gray_image)
                    logger.debug(f"Page {page_num}: Converted to grayscale with histogram equalization")
                    # PaddleOCR 3.x needs 3-channel image
                    ocr_input = cv2.cvtColor(gray_image, cv2.COLOR_GRAY2BGR)
                    
                    # === PaddleOCR ===
                    logger.info(f"Page {page_num}: Running PaddleOCR on preprocessed image...")
                    ocr_result = self.ocr_engine.ocr(ocr_input)
                    logger.info(f"Page {page_num}: PaddleOCR returned results")
                    
                    # Extract text - handle PaddleOCR 3.x (dict) and 2.x (list) formats
                    page_text = ""
                    if ocr_result:
                        first = ocr_result[0] if ocr_result else None
                        if first is not None and isinstance(first, dict) and 'rec_texts' in first:
                            # PaddleOCR 3.x format
                            for text in first.get('rec_texts', []):
                                if text:
                                    page_text += str(text) + " "
                        else:
                            # PaddleOCR 2.x format
                            for line in ocr_result:
                                if line:
                                    for word_info in line:
                                        if word_info and len(word_info) >= 2:
                                            text_content = word_info[1]
                                            if isinstance(text_content, (list, tuple)):
                                                page_text += str(text_content[0]) + " "
                                            else:
                                                page_text += str(text_content) + " "
                    
                    if page_text.strip():
                        full_text += page_text + "\n"
                        logger.info(f"Page {page_num}: OCR SUCCESS - Extracted {len(page_text)} characters, Preview: {page_text[:100]}")
                    else:
                        logger.warning(f"Page {page_num}: No text extracted (blank page?)")
                    
                    # Early stopping
                    if full_text.strip():
                        temp_result = self._analyze_text(
                            full_text,
                            extraction_method="tinyocr",
                            pages_processed=page_num + 1,
                            total_pages=total_pages,
                        )
                        logger.info(f"Page {page_num}: Confidence check: {temp_result.confidence:.2%}")
                        if temp_result.confidence >= self.confidence_threshold:
                            logger.info(f"Early stopping at page {page_num + 1}")
                            if pdf_document is not None:
                                pdf_document.close()
                            return temp_result
                    
                    # Cleanup temp image
                    try:
                        os.remove(temp_image_path)
                    except:
                        pass
                
                except Exception as page_error:
                    logger.error(f"Page {page_num} error: {page_error}", exc_info=True)
                    continue
            
            # Return final result from all processed pages
            if full_text.strip():
                logger.info(f"TinyOCR: Total {len(full_text)} characters extracted from {pages_to_process} pages")
                result = self._analyze_text(
                    full_text,
                    extraction_method="tinyocr",
                    pages_processed=pages_to_process,
                    total_pages=total_pages,
                )
                return result
            else:
                logger.error(f"TinyOCR: No text extracted from any of {pages_to_process} pages")
                return None
        
        except Exception as e:
            logger.error(f"TinyOCR failed: {e}", exc_info=True)
            return None
        
        finally:
            if pdf_document is not None:
                try:
                    pdf_document.close()
                except:
                    pass

    
    def _analyze_text(
        self,
        text: str,
        extraction_method: str = "unknown",
        pages_processed: int = 0,
        total_pages: int = 0,
    ) -> ClassificationResult:
        """
        Analyze extracted text for PA classification and payer matching.
        
        Args:
            text: Extracted text content
            extraction_method: "pymupdf" or "tinyocr"
            pages_processed: Number of pages processed
            total_pages: Total pages in document
            
        Returns:
            ClassificationResult with confidence scores
        """
        logger.info(f"Analyzing text ({len(text)} characters) extracted via {extraction_method}")
        logger.debug(f"Text preview: {text[:300]}")
        
        # Normalize text
        text_lower = text.lower()
        
        # Check for non-PA keywords
        non_pa_matches = sum(1 for keyword in NON_PA_KEYWORDS if keyword in text_lower)
        if non_pa_matches >= 2:
            logger.warning(f"Found {non_pa_matches} non-PA keywords - classified as OTHER")
            return ClassificationResult(
                document_type="other",
                confidence=0.95,
                extraction_method=extraction_method,
                pages_processed=pages_processed,
                total_pages=total_pages,
                keywords_found=[],
            )
        
        # Extract PA keywords
        keywords_found = self._extract_keywords(text_lower)
        logger.info(f"PA keywords found: {keywords_found} ({len(keywords_found)} total)")
        
        pa_keyword_score = min(len(keywords_found) / 3.0, 1.0)  # Normalize by 3 keywords
        
        # Match payers and extract company names
        company_names_found, payer_scores = self._match_payers(text_lower)
        logger.info(f"Payer matches: {payer_scores}")
        logger.info(f"Company names found: {company_names_found}")
        
        payer_match_score = max(payer_scores.values()) if payer_scores else 0.0
        best_payer = max(payer_scores, key=payer_scores.get) if payer_scores else None
        
        # Calculate final confidence
        confidence = self._calculate_confidence(
            pa_keyword_score,
            payer_match_score,
            len(keywords_found),
        )
        
        logger.info(f"Confidence scores - PA keywords: {pa_keyword_score:.2%}, Payer match: {payer_match_score:.2%}, Final: {confidence:.2%}")
        
        # Lower threshold from 0.5 to 0.40 - be more lenient for PA classification
        document_type = "prior_authorization" if confidence >= 0.40 else "other"
        logger.info(f"Classification result: {document_type} (confidence: {confidence:.2%})")
        
        return ClassificationResult(
            document_type=document_type,
            confidence=confidence,
            matched_payer=best_payer,
            extraction_method=extraction_method,
            pages_processed=pages_processed,
            total_pages=total_pages,
            keywords_found=keywords_found,
            company_names_found=company_names_found if company_names_found else None,
            raw_confidence_scores={
                "pa_keywords": pa_keyword_score,
                "payer_match": payer_match_score,
            },
        )
    
    def _extract_keywords(self, text_lower: str) -> List[str]:
        """Extract PA-relevant keywords from text"""
        found_keywords = []
        for keyword in COMMON_PA_KEYWORDS:
            # Use word boundary matching for more accuracy
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, text_lower):
                found_keywords.append(keyword)
        return found_keywords
    
    def _match_payers(self, text_lower: str) -> Tuple[List[str], Dict[str, float]]:
        """
        Match text against known payers.
        
        Returns:
            Tuple of (company_names_found, payer_scores_dict)
        """
        company_names_found = []
        payer_scores = {}
        
        for payer_name, template in AUTHORIZATION_TEMPLATES.items():
            # Company name matching (higher weight)
            company_matches = sum(
                1 for company in template["company_names"]
                if company.lower() in text_lower
            )
            company_score = min(company_matches / 2.0, 0.6)  # Max 60% from company names
            
            if company_matches > 0:
                company_names_found.extend([
                    c for c in template["company_names"]
                    if c.lower() in text_lower
                ])
            
            # Keyword matching
            keyword_matches = sum(
                1 for keyword in template["keywords"]
                if keyword.lower() in text_lower
            )
            keyword_score = min(keyword_matches / 3.0, 0.3)  # Max 30% from keywords
            
            # Approval status keywords
            approval_matches = sum(
                1 for keyword in template["approval_status_keywords"]
                if keyword.lower() in text_lower
            )
            approval_score = min(approval_matches / 1.0, 0.15)  # Max 15% from approval keywords
            
            # Combined score for this payer
            total_score = company_score + keyword_score + approval_score
            
            if total_score > 0:
                payer_scores[payer_name] = total_score
        
        return list(set(company_names_found)), payer_scores
    
    def _calculate_confidence(
        self,
        pa_keyword_score: float,
        payer_match_score: float,
        keyword_count: int,
    ) -> float:
        """
        Calculate final confidence score with improved weighting.
        
        Weights:
        - PA keywords: 45% (lowered from 50% to allow more flexibility)
        - Payer match: 30% (lowered from 35%)
        - Keyword count bonus: 15% (same)
        - Base score: 10% (give benefit of doubt if keywords found)
        """
        keyword_bonus = min(keyword_count / 5.0, 0.15)  # Bonus for multiple keywords
        base_score = 0.10  # 10% base for having content extracted
        
        confidence = (
            pa_keyword_score * 0.45 +
            payer_match_score * 0.30 +
            keyword_bonus +
            base_score
        )
        
        return min(confidence, 1.0)


def classify_document(pdf_path: str, **kwargs) -> ClassificationResult:
    """
    Convenience function to classify a single document.
    
    Args:
        pdf_path: Path to PDF file
        **kwargs: Additional arguments for HybridDocumentClassifier
        
    Returns:
        ClassificationResult
    """
    classifier = HybridDocumentClassifier(**kwargs)
    return classifier.classify(pdf_path)
