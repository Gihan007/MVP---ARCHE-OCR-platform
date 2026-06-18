from paddleocr import PaddleOCR
import cv2
import numpy as np

class OCREngine:
    def __init__(self):
        self.ocr = PaddleOCR(use_angle_cls=True, lang='en')

    def extract_text(self, image_path: str) -> dict:
        # Mock implementation
        result = self.ocr.ocr(image_path, cls=True)
        tokens = []
        for line in result[0]:
            bbox, (text, confidence) = line
            tokens.append({
                'text': text,
                'bbox': bbox,
                'confidence': confidence
            })
        return {'tokens': tokens}

# Singleton
ocr_engine = OCREngine()