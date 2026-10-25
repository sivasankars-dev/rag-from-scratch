
"""Render PDF pages as PNG images for vision processing."""

from pathlib import Path

import pymupdf


class PDFPageRenderer:
    """Render individual PDF pages into PNG files."""

    def __init__(self, scale: float = 1.5):
        if scale <= 0:
            raise ValueError("Scale must be greater than zero.")

        self.scale = scale

    def render_page(
        self,
        pdf_path: str | Path,
        page_number: int,
        output_dir: str | Path,
    ) -> Path:
        """Render a 1-based PDF page number and return its image path."""
        path = Path(pdf_path)
        destination = Path(output_dir)

        if not path.is_file():
            raise FileNotFoundError(f"PDF not found: {path}")

        if page_number < 1:
            raise ValueError("Page number must be 1 or greater.")

        destination.mkdir(parents=True, exist_ok=True)

        with pymupdf.open(path) as pdf:
            if page_number > len(pdf):
                raise ValueError(
                    f"Page {page_number} does not exist in this PDF."
                )

            page = pdf[page_number - 1]
            pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(self.scale, self.scale),
                alpha=False,
            )

            image_path = (
                destination / f"{path.stem}_page_{page_number}.png"
            )
            pixmap.save(image_path)

        return image_path
