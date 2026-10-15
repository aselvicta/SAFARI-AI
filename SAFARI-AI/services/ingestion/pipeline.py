"""Document cleaning, classification, chunking, and indexing."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from services.common.embeddings import HashEmbedder
from services.common.models import Chunk, Document, FeeRecord, authority_score
from services.common.store import JsonStore

_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")

CLASSIFIERS = (
    ("tariff", ("tariff", "conservation fee", "park fee", "park fees")),
    ("act", ("chapter", "an act", "cap.")),
    ("policy", ("national policy", "policy")),
    ("guideline", ("guideline", "guidelines")),
    ("procedure", ("procedure", "standard operating")),
    ("manual", ("manual", "handbook")),
    ("newsletter", ("newsletter", "tourism splash")),
    ("brochure", ("brochure",)),
    ("regulation", ("regulation", "regulations")),
)


def clean_text(text: str) -> str:
    cleaned = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _WHITESPACE.sub(" ", cleaned)
    cleaned = _BLANK_LINES.sub("\n\n", cleaned)
    return cleaned.strip()


def classify_document(text: str, filename: str = "") -> str:
    haystack = f"{filename}\n{text[:4000]}".lower()
    for label, needles in CLASSIFIERS:
        if any(needle in haystack for needle in needles):
            return label
    return "publication"


def chunk_text(text: str, size: int = 900, overlap: int = 140) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > size:
            if current:
                chunks.append(current.strip())
                current = ""
            start = 0
            while start < len(paragraph):
                piece = paragraph[start : start + size].strip()
                if piece:
                    chunks.append(piece)
                if start + size >= len(paragraph):
                    break
                start += size - overlap
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= size:
            current = candidate
            continue
        if current:
            chunks.append(current.strip())
        current = paragraph
    if current:
        chunks.append(current.strip())
    return [chunk for chunk in chunks if chunk]


def extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Install pypdf to ingest PDF files.") from exc
    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    return clean_text("\n\n".join(pages))


def read_document_file(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return extract_pdf(path)
    return clean_text(path.read_text(encoding="utf-8"))


def load_sidecar(path: Path) -> dict:
    for candidate in (Path(str(path) + ".json"), path.with_suffix(path.suffix + ".json")):
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    sibling = path.with_suffix(".json")
    if sibling.exists() and sibling != path:
        return json.loads(sibling.read_text(encoding="utf-8"))
    return {}


def build_document(text: str, metadata: dict, filename: str = "") -> Document:
    document_type = metadata.get("document_type") or classify_document(text, filename)
    authority = metadata.get("authority", "unverified")
    explicit = metadata.get("authority_score")
    fees = [FeeRecord.from_dict(item) for item in metadata.get("fees", [])]
    return Document(
        document_id=metadata.get("document_id") or _slug_id(metadata.get("title") or filename or "document"),
        title=metadata.get("title") or Path(filename).stem or "Untitled document",
        organization=metadata.get("organization", "Unknown"),
        document_type=document_type,
        text=text,
        language=metadata.get("language", "en"),
        authority=authority,
        authority_score=authority_score(authority, document_type, explicit),
        status=metadata.get("status", "current"),
        version=int(metadata.get("version", 1)),
        published_date=metadata.get("published_date"),
        effective_from=metadata.get("effective_from"),
        effective_until=metadata.get("effective_until"),
        retrieved_at=metadata.get("retrieved_at") or date.today().isoformat(),
        source_url=metadata.get("source_url"),
        park_slug=metadata.get("park_slug"),
        fees=fees,
    )


def index_document(store: JsonStore, document: Document, embedder: HashEmbedder | None = None) -> Document:
    encoder = embedder or HashEmbedder()
    pieces = chunk_text(document.text)
    chunks: list[Chunk] = []
    for position, piece in enumerate(pieces):
        chunks.append(
            Chunk(
                chunk_id=f"{document.document_id}:{position}",
                document_id=document.document_id,
                text=piece,
                position=position,
                embedding=encoder.embed(piece),
                title=document.title,
                organization=document.organization,
                document_type=document.document_type,
                language=document.language,
                authority=document.authority,
                authority_score=document.authority_score,
                status=document.status,
                version=document.version,
                published_date=document.published_date,
                effective_from=document.effective_from,
                effective_until=document.effective_until,
                retrieved_at=document.retrieved_at,
                source_url=document.source_url,
                park_slug=document.park_slug,
            )
        )
    store.upsert_document(document, chunks)
    return document


def ingest_text(store: JsonStore, text: str, metadata: dict, embedder: HashEmbedder | None = None) -> Document:
    document = build_document(clean_text(text), metadata, metadata.get("filename", ""))
    return index_document(store, document, embedder)


def ingest_file(store: JsonStore, path: Path, metadata: dict | None = None, embedder: HashEmbedder | None = None) -> Document:
    sidecar = load_sidecar(path)
    merged = {**sidecar, **(metadata or {})}
    merged.setdefault("filename", path.name)
    merged.setdefault("title", sidecar.get("title", path.stem.replace("_", " ")))
    text = read_document_file(path)
    return ingest_text(store, text, merged, embedder)


def _slug_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug[:80] or "document"
