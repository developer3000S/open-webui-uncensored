import logging
import os
import sys
from typing import Any

import pytesseract
from PIL import Image
from pdf2image import convert_from_path
from langchain_core.documents import Document
from open_webui.env import GLOBAL_LOG_LEVEL

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)


class TesseractLoader:
    """Uses pytesseract for OCR on scanned PDFs."""

    def __init__(self, file_path: str, lang: str | None = None):
        self.file_path = file_path
        # Проверить что tesseract доступен
        if not pytesseract.get_tesseract_version():
            raise RuntimeError('Tesseract OCR not found')
        self.lang = lang or os.getenv('TESSERACT_LANG', 'rus+eng')

    def load(self) -> list[Document]:
        documents = []
        try:
            # Конвертировать PDF в изображения
            images = convert_from_path(self.file_path, dpi=300)
            for i, image in enumerate(images):
                # OCR
                text = pytesseract.image_to_string(image, lang=self.lang).strip()
                if text:
                    documents.append(Document(
                        page_content=text,
                        metadata={
                            'source': self.file_path,
                            'page': i,
                            'is_ocr': True,
                            'engine': 'tesseract',
                        }
                    ))
                else:
                    # Пустая страница не добавляется
                    log.debug(f'Page {i} empty after OCR')
        except Exception as e:
            log.error(f'Tesseract OCR failed: {e}')
            raise

        return documents
