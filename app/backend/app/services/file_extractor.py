import base64
import io
import logging
import os
from pathlib import Path
from typing import Optional

from ..core.config import settings

logger = logging.getLogger(__name__)


class FileExtractor:
    SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
    SUPPORTED_DOC_TYPES = {"application/pdf"}

    @staticmethod
    def classify_file(content_type: str) -> str:
        if content_type in FileExtractor.SUPPORTED_IMAGE_TYPES:
            return "image"
        if content_type in FileExtractor.SUPPORTED_DOC_TYPES:
            return "pdf"
        return "unsupported"

    @staticmethod
    def is_allowed(content_type: str) -> bool:
        allowed = {t.strip() for t in settings.allowed_file_types.split(",")}
        return content_type in allowed

    @staticmethod
    async def extract_pdf_pages(pdf_path: str, output_dir: str, dpi: int = 150) -> list[str]:
        try:
            import fitz
        except ImportError:
            logger.error("PyMuPDF not installed — cannot extract PDF pages")
            return []

        pages = []
        try:
            doc = fitz.open(pdf_path)
            for i, page in enumerate(doc):
                mat = fitz.Matrix(dpi / 72, dpi / 72)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                page_filename = f"page_{i + 1}.png"
                page_path = os.path.join(output_dir, page_filename)
                pix.save(page_path)
                pages.append(page_filename)
            doc.close()
        except Exception as e:
            logger.error("PDF extraction failed for %s: %s", pdf_path, e)
        return pages

    @staticmethod
    def image_to_base64(file_path: str) -> Optional[str]:
        try:
            with open(file_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            logger.error("Failed to read image %s: %s", file_path, e)
            return None

    @staticmethod
    def build_image_content_part(file_path: str, media_type: str) -> Optional[dict]:
        data = FileExtractor.image_to_base64(file_path)
        if not data:
            return None
        return {
            "type": "image",
            "image": {
                "type": "base64",
                "media_type": media_type,
                "data": data,
            },
        }

    @staticmethod
    async def file_to_content_parts(
        file_path: str,
        content_type: str,
        file_type: str,
        extracted_pages: Optional[list[str]] = None,
    ) -> list[dict]:
        parts = []
        file_dir = os.path.dirname(file_path)

        if file_type == "image":
            part = FileExtractor.build_image_content_part(file_path, content_type)
            if part:
                parts.append(part)

        elif file_type == "pdf" and extracted_pages:
            for page_file in extracted_pages:
                page_path = os.path.join(file_dir, page_file)
                part = FileExtractor.build_image_content_part(page_path, "image/png")
                if part:
                    parts.append(part)

        return parts

    @staticmethod
    def get_upload_dir(user_id: str, file_id: str) -> str:
        base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            settings.upload_dir,
            user_id,
            file_id,
        )
        os.makedirs(base, exist_ok=True)
        return base
