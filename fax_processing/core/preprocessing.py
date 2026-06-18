"""
Preprocessing module - page splitting, deskewing, denoising, DPI normalization
"""
import sys
from pathlib import Path

# Fix imports - ensure project root is in path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import cv2
import numpy as np
from PIL import Image
from typing import List, Tuple
import fitz  # PyMuPDF
from io import BytesIO

# Now import project modules with absolute paths
from fax_processing.config.settings import settings
from fax_processing.core.storage import storage
from fax_processing.models.schemas import JobStatus


class Preprocessor:
    """Handles page splitting and image preprocessing"""
    
    def __init__(self):
        self.target_dpi = settings.OCR_DPI
    
    def process_document(self, job_id: str, tenant_id: str, file_path: Path) -> int:
        """
        Process document: split into pages and preprocess each
        
        Returns: number of pages processed
        """
        import time
        import logging
        logger = logging.getLogger(__name__)
        
        # Verify file exists
        file_path = Path(file_path)
        if not file_path.exists():
            logger.error(f"❌ FILE NOT FOUND: {file_path}")
            raise FileNotFoundError(f"Cannot find file: {file_path}")
        
        logger.info(f"✅ File found: {file_path} (size: {file_path.stat().st_size / 1024 / 1024:.1f} MB)")
        
        # Read file content
        start = time.time()
        logger.info(f"📖 Reading file...")
        with open(file_path, "rb") as f:
            content = f.read()
        elapsed = time.time() - start
        logger.info(f"✅ Read {len(content) / 1024 / 1024:.1f} MB in {elapsed:.1f}s")
        
        # Split into pages
        start = time.time()
        logger.info(f"📄 Splitting into pages...")
        pages = self._split_pages(content, file_path.suffix.lower())
        elapsed = time.time() - start
        logger.info(f"✅ Split into {len(pages)} pages in {elapsed:.1f}s")
        
        # Process each page
        for page_num, page_image in enumerate(pages, start=1):
            start = time.time()
            logger.info(f"📝 Processing page {page_num}/{len(pages)}...")
            
            # Preprocess
            processed_image = self._preprocess_page(page_image)
            
            # Save page
            img_bytes = self._image_to_bytes(processed_image)
            storage.save_page_image(
                job_id=job_id,
                tenant_id=tenant_id,
                page_num=page_num,
                image_bytes=img_bytes,
                extension=".png"
            )
            elapsed = time.time() - start
            logger.info(f"✅ Page {page_num} done in {elapsed:.1f}s")
        
        return len(pages)
    
    def _split_pages(self, content: bytes, file_ext: str) -> List[Image.Image]:
        """Split document into individual pages"""
        if file_ext == ".pdf":
            # Convert PDF to images using PyMuPDF (Fitz)
            pdf_document = fitz.open(stream=content, filetype="pdf")
            pages = []
            for page_num in range(len(pdf_document)):
                page = pdf_document[page_num]
                # Render page to image with target DPI
                zoom = self.target_dpi / 72.0  # 72 DPI is default
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_data = pix.tobytes("ppm")
                img = Image.open(BytesIO(img_data))
                pages.append(img.convert("RGB"))
            pdf_document.close()
            return pages
        
        elif file_ext in [".tiff", ".tif"]:
            # Handle multi-page TIFF
            img = Image.open(BytesIO(content))
            pages = []
            try:
                for i in range(img.n_frames):
                    img.seek(i)
                    pages.append(img.copy())
            except EOFError:
                pass
            return pages if pages else [img]
        
        else:
            # Single image file
            img = Image.open(BytesIO(content))
            return [img]
    
    def _preprocess_page(self, image: Image.Image) -> Image.Image:
        """
        Preprocess single page - OPTIMIZED for speed:
        - Convert to grayscale only (skip deskew/denoise/contrast - PaddleOCR handles these internally)
        - This saves ~1-2 seconds per page
        """
        # Convert PIL to OpenCV
        img_array = np.array(image)
        
        # Convert to grayscale if needed
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array
        
        # ⚡ OPTIMIZED: Skip deskew, denoise, and contrast enhancement
        # PaddleOCR v5 handles these internally and does a better job
        # This saves ~1-2 seconds per page (deskew+denoise were expensive)
        
        # Convert back to PIL
        result = Image.fromarray(gray)
        
        return result
    
    def _deskew_image(self, image: np.ndarray) -> np.ndarray:
        """Deskew image using projection profile"""
        # Detect edges
        edges = cv2.Canny(image, 50, 150, apertureSize=3)
        
        # Detect lines using Hough transform
        lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)
        
        if lines is None or len(lines) == 0:
            return image
        
        # Calculate median angle
        angles = []
        for rho, theta in lines[:, 0]:
            angle = np.rad2deg(theta) - 90
            angles.append(angle)
        
        median_angle = np.median(angles)
        
        # Rotate if skew is significant
        if abs(median_angle) > 0.5:
            (h, w) = image.shape
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
            rotated = cv2.warpAffine(
                image, M, (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE
            )
            return rotated
        
        return image
    
    def _image_to_bytes(self, image: Image.Image) -> bytes:
        """Convert PIL Image to bytes"""
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()


# Singleton instance
preprocessor = Preprocessor()
