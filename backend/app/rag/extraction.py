import asyncio
import json
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from app.rag.chunks import TextBlock

MAX_IMAGE_PIXELS = 40_000_000
MAX_PAGE_OCR_SECONDS = 60
MAX_DOCUMENT_OCR_SECONDS = 600
OCR_CONCURRENCY = 1
MIN_PAGE_CHARACTERS = 40


@dataclass(frozen=True)
class ExtractionResult:
    blocks: list[TextBlock]
    ocr_pages: tuple[int, ...]
    page_count: int
    unreadable_pages: tuple[int, ...] = ()


_ocr_slots: asyncio.Semaphore | None = None


def _get_ocr_slots() -> asyncio.Semaphore:
    global _ocr_slots
    if _ocr_slots is None:
        _ocr_slots = asyncio.Semaphore(OCR_CONCURRENCY)
    return _ocr_slots


def _paragraph_blocks(text: str, page: int, section: str) -> list[TextBlock]:
    blocks = []
    for paragraph in re.split(r"\n\s*\n", text):
        normalized = " ".join(paragraph.split())
        if not normalized:
            continue
        if len(normalized) < 100 and normalized.isupper():
            section = normalized
            blocks.append(TextBlock(normalized, section=section, page=page, kind="heading"))
        else:
            blocks.append(TextBlock(normalized, section=section, page=page))
    return blocks


def _run_ocr(input_path: Path, output_path: Path, *, image: bool) -> str:
    command = [
        "ocrmypdf", "--skip-text", "--rotate-pages", "--deskew", "--sidecar",
        str(output_path.with_suffix(".txt")), "--language", "ind+eng",
    ]
    if image:
        command.append("--image-dpi=300")
    command.extend([str(input_path), str(output_path)])
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=MAX_PAGE_OCR_SECONDS)
        text_path = output_path.with_suffix(".txt")
        if image and not text_path.exists():
            from pypdf import PdfReader

            return PdfReader(str(output_path)).pages[0].extract_text() or ""
        return text_path.read_text(encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as error:
        raise ValueError("OCR_TIMEOUT_PAGE") from error
    except subprocess.CalledProcessError as error:
        raise ValueError("OCR_FAILED_PAGE") from error


async def _run_process(command: list[str], *, timeout: int) -> None:
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    try:
        await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as error:
        process.kill()
        await process.wait()
        raise ValueError("OCR_TIMEOUT_PAGE") from error
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise ValueError("OCR_FAILED_PAGE")


async def extract_blocks(path: Path) -> ExtractionResult:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg"}:
        try:
            from PIL import Image

            with Image.open(path) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError("IMAGE_DIMENSIONS_EXCEEDED")
                image.verify()
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("IMAGE_UNREADABLE") from error
        started = time.monotonic()
        async with _get_ocr_slots():
            text = await _ocr_image_persistent(path)
        if time.monotonic() - started > MAX_DOCUMENT_OCR_SECONDS:
            raise ValueError("OCR_TIMEOUT_DOCUMENT")
        blocks = _paragraph_blocks(text, 1, "")
        if sum(len(block.text) for block in blocks) < MIN_PAGE_CHARACTERS:
            raise ValueError("OCR_QUALITY_INSUFFICIENT_PAGE_1")
        return ExtractionResult(blocks, (1,), 1)

    if suffix == ".pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                raise ValueError("PDF_ENCRYPTED")
            if not reader.pages:
                raise ValueError("PDF_PAGE_LIMIT_EXCEEDED")
            native = [(page.extract_text() or "") for page in reader.pages]
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("PDF_UNREADABLE") from error
        ocr_pages = tuple(
            index + 1 for index, text in enumerate(native)
            if len("".join(text.split())) < MIN_PAGE_CHARACTERS
        )
        if len(ocr_pages) > 100:
            raise ValueError("PDF_OCR_PAGE_LIMIT_EXCEEDED")
        blocks: list[TextBlock] = []
        section = ""
        unreadable_pages: list[int] = []
        if ocr_pages:
            started = time.monotonic()
            with tempfile.TemporaryDirectory(prefix="knowledge-ocr-") as temporary:
                page_texts = []
                unreadable_pages = []
                from pypdf import PdfWriter

                for page_number in ocr_pages:
                    if time.monotonic() - started > MAX_DOCUMENT_OCR_SECONDS:
                        raise ValueError("OCR_TIMEOUT_DOCUMENT")
                    page_pdf = Path(temporary) / f"page-{page_number}.pdf"
                    page_output = Path(temporary) / f"page-{page_number}-ocr.pdf"
                    writer = PdfWriter()
                    writer.add_page(reader.pages[page_number - 1])
                    with page_pdf.open("wb") as file:
                        writer.write(file)
                    command = [
                        "ocrmypdf", "--skip-text", "--rotate-pages", "--deskew", "--language", "ind+eng",
                        str(page_pdf), str(page_output),
                    ]
                    try:
                        async with _get_ocr_slots():
                            await _run_process(command, timeout=MAX_PAGE_OCR_SECONDS)
                    except ValueError as error:
                        if "TIMEOUT" in str(error):
                            raise ValueError(f"OCR_TIMEOUT_PAGE_{page_number}") from error
                        unreadable_pages.append(page_number)
                        continue
                    page_texts.append((page_number, PdfReader(str(page_output)).pages[0].extract_text() or ""))
                if time.monotonic() - started > MAX_DOCUMENT_OCR_SECONDS:
                    raise ValueError("OCR_TIMEOUT_DOCUMENT")
                for page_number, text in page_texts:
                    if len("".join(text.split())) < MIN_PAGE_CHARACTERS:
                        unreadable_pages.append(page_number)
                usable_native_pages = sum(
                    len("".join(text.split())) >= MIN_PAGE_CHARACTERS for text in native
                )
                if len(unreadable_pages) == len(ocr_pages) and usable_native_pages == 0:
                    raise ValueError("OCR_QUALITY_INSUFFICIENT_ALL_PAGES")
                replacements = {
                    page_number: text for page_number, text in page_texts
                    if page_number not in unreadable_pages
                }
                for page_number in unreadable_pages:
                    replacements[page_number] = ""
            for index, text in enumerate(native):
                page_number = index + 1
                page_text = replacements.get(page_number, text)
                blocks.extend(_paragraph_blocks(page_text, page_number, section))
                if blocks:
                    section = blocks[-1].section or section
        else:
            for page_number, text in enumerate(native, start=1):
                blocks.extend(_paragraph_blocks(text, page_number, section))
                if blocks:
                    section = blocks[-1].section or section
        if not blocks:
            raise ValueError("EXTRACTION_NO_USABLE_TEXT")
        return ExtractionResult(blocks, ocr_pages, len(reader.pages), tuple(sorted(set(unreadable_pages))) if ocr_pages else ())

    if suffix in {".docx", ".txt", ".md"}:
        blocks = await asyncio.to_thread(_extract_non_pdf_document_blocks, path)
    else:
        raise ValueError("UNSUPPORTED_FILE_TYPE")
    return ExtractionResult(blocks, (), 1)


def _extract_non_pdf_document_blocks(path: Path) -> list[TextBlock]:
    from app.rag.management import extract_document_blocks

    return extract_document_blocks(path)


async def _ocr_image_persistent(path: Path) -> str:
    temporary = tempfile.TemporaryDirectory(prefix="knowledge-ocr-")
    output = Path(temporary.name) / "image.pdf"
    command = [
        "ocrmypdf", "--skip-text", "--rotate-pages", "--deskew", "--sidecar",
        str(output.with_suffix(".txt")), "--language", "ind+eng", "--image-dpi=300",
        str(path), str(output),
    ]
    try:
        async with _get_ocr_slots():
            await _run_process(command, timeout=MAX_DOCUMENT_OCR_SECONDS)
        text_path = output.with_suffix(".txt")
        if text_path.exists():
            return text_path.read_text(encoding="utf-8", errors="replace")
        from pypdf import PdfReader

        return PdfReader(str(output)).pages[0].extract_text() or ""
    finally:
        temporary.cleanup()


def serialize_blocks(blocks: list[TextBlock]) -> str:
    return json.dumps([block.__dict__ for block in blocks], ensure_ascii=False)


def deserialize_blocks(value: str) -> list[TextBlock]:
    return [TextBlock(**block) for block in json.loads(value)]
