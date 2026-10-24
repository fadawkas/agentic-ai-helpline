import re
from dataclasses import dataclass

MAX_CHUNK_CHARACTERS = 1800
CHUNK_OVERLAP_CHARACTERS = 160
MAX_CONTENT_CHARACTERS = MAX_CHUNK_CHARACTERS - CHUNK_OVERLAP_CHARACTERS - 1


@dataclass(frozen=True)
class TextBlock:
    text: str
    section: str = ""
    page: int | None = None
    kind: str = "paragraph"


@dataclass(frozen=True)
class KnowledgeChunkData:
    index: int
    text: str
    section: str
    page: int | None
    embedding_text: str


def _split_long_text(text: str) -> list[str]:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    pieces: list[str] = []
    current = ""
    for sentence in sentences or [text]:
        while len(sentence) > MAX_CONTENT_CHARACTERS:
            boundary = sentence.rfind(" ", 0, MAX_CONTENT_CHARACTERS)
            if boundary < MAX_CONTENT_CHARACTERS // 2:
                boundary = MAX_CONTENT_CHARACTERS
            piece, sentence = sentence[:boundary].strip(), sentence[boundary:].strip()
            if current:
                pieces.append(current)
                current = ""
            pieces.append(piece)
        candidate = f"{current} {sentence}".strip()
        if len(candidate) <= MAX_CONTENT_CHARACTERS:
            current = candidate
        else:
            if current:
                pieces.append(current)
            current = sentence
    if current:
        pieces.append(current)
    return pieces


def _overlap(previous: str) -> str:
    if len(previous) < 250:
        return ""
    start = len(previous) - CHUNK_OVERLAP_CHARACTERS
    boundary = previous.find(". ", start)
    if boundary >= 0:
        start = boundary + 2
    else:
        whitespace = previous.find(" ", start)
        if whitespace >= 0:
            start = whitespace + 1
    return previous[start:].strip()


def chunk_blocks(
    blocks: list[TextBlock], *, title: str, publisher: str, category: str,
    region: str | None = None,
) -> list[KnowledgeChunkData]:
    chunks: list[KnowledgeChunkData] = []
    previous_text = ""

    def append_text(text: str, section: str, page: int | None) -> None:
        nonlocal previous_text
        for part in _split_long_text(text):
            overlap = _overlap(previous_text)
            if overlap and overlap not in part:
                part = f"{overlap} {part}".strip()
            metadata = [f"Title: {title}", f"Publisher: {publisher}", f"Category: {category}"]
            if section:
                metadata.append(f"Section: {section}")
            if region:
                metadata.append(f"Region: {region}")
            enriched = "\n".join([*metadata, f"Content: {part}"])
            chunks.append(KnowledgeChunkData(len(chunks), part, section, page, enriched))
            previous_text = part

    pending = ""
    pending_section = ""
    pending_page: int | None = None
    for block in blocks:
        text = " ".join(block.text.split())
        section = block.section.strip()
        if block.kind == "heading":
            if pending:
                append_text(pending, pending_section, pending_page)
                pending = ""
            pending_section = section or text
            pending_page = block.page
            continue
        if not text:
            continue
        if pending and (section != pending_section or block.page != pending_page):
            append_text(pending, pending_section, pending_page)
            pending = ""
        candidate = f"{pending}\n{text}".strip() if pending else text
        if pending and len(candidate) > MAX_CONTENT_CHARACTERS:
            append_text(pending, pending_section, pending_page)
            pending = ""
            candidate = text
        if not pending:
            pending_section = section or pending_section
            pending_page = block.page
        if len(candidate) > MAX_CONTENT_CHARACTERS:
            append_text(candidate, section or pending_section, block.page)
            pending = ""
        else:
            pending = candidate
    if pending:
        append_text(pending, pending_section, pending_page)
    return chunks
