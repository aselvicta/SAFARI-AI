"""Knowledge records for documents, chunks, parks, and fees."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


AUTHORITY_SCORES = {
    "official": 1.0,
    "curated": 0.85,
    "expert": 0.80,
    "operator": 0.60,
    "unverified": 0.50,
    "system": 0.45,
    "blog": 0.30,
    "sample": 0.20,
}


def authority_score(authority: str, document_type: str = "", explicit: float | None = None) -> float:
    if explicit is not None:
        return float(explicit)
    if authority == "official" and document_type in {"brochure", "newsletter"}:
        return 0.95
    return AUTHORITY_SCORES.get(authority, 0.50)


@dataclass
class FeeRecord:
    park_slug: str
    name: str
    visitor_category: str
    age_band: str
    amount: float
    currency: str
    unit: str = "per_person_per_day"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FeeRecord":
        return cls(
            park_slug=raw["park_slug"],
            name=raw["name"],
            visitor_category=raw["visitor_category"],
            age_band=raw["age_band"],
            amount=float(raw["amount"]),
            currency=raw["currency"],
            unit=raw.get("unit", "per_person_per_day"),
        )


@dataclass
class Document:
    document_id: str
    title: str
    organization: str
    document_type: str
    text: str
    language: str = "en"
    authority: str = "curated"
    authority_score: float = 0.85
    status: str = "current"
    version: int = 1
    published_date: str | None = None
    effective_from: str | None = None
    effective_until: str | None = None
    retrieved_at: str | None = None
    source_url: str | None = None
    park_slug: str | None = None
    fees: list[FeeRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fees"] = [fee.to_dict() for fee in self.fees]
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Document":
        fees = [FeeRecord.from_dict(item) for item in raw.get("fees", [])]
        return cls(
            document_id=raw["document_id"],
            title=raw["title"],
            organization=raw.get("organization", ""),
            document_type=raw.get("document_type", "publication"),
            text=raw.get("text", ""),
            language=raw.get("language", "en"),
            authority=raw.get("authority", "curated"),
            authority_score=float(raw.get("authority_score", 0.85)),
            status=raw.get("status", "current"),
            version=int(raw.get("version", 1)),
            published_date=raw.get("published_date"),
            effective_from=raw.get("effective_from"),
            effective_until=raw.get("effective_until"),
            retrieved_at=raw.get("retrieved_at"),
            source_url=raw.get("source_url"),
            park_slug=raw.get("park_slug"),
            fees=fees,
        )


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    text: str
    position: int
    embedding: list[float] = field(default_factory=list)
    title: str = ""
    organization: str = ""
    document_type: str = ""
    language: str = "en"
    authority: str = "curated"
    authority_score: float = 0.85
    status: str = "current"
    version: int = 1
    published_date: str | None = None
    effective_from: str | None = None
    effective_until: str | None = None
    retrieved_at: str | None = None
    source_url: str | None = None
    park_slug: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Chunk":
        return cls(**raw)


@dataclass
class Park:
    slug: str
    name: str
    area_km2: float | None
    established_year: int | None
    gazette: str | None
    circuit: str
    interests: list[str]
    beach: bool = False
    mountain_climb: bool = False
    aliases: list[str] = field(default_factory=list)
    strict_aliases: list[str] = field(default_factory=list)
    source_url: str = ""
    source_title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Park":
        return cls(
            slug=raw["slug"],
            name=raw["name"],
            area_km2=raw.get("area_km2"),
            established_year=raw.get("established_year"),
            gazette=raw.get("gazette"),
            circuit=raw["circuit"],
            interests=list(raw.get("interests", [])),
            beach=bool(raw.get("beach", False)),
            mountain_climb=bool(raw.get("mountain_climb", False)),
            aliases=list(raw.get("aliases", [])),
            strict_aliases=list(raw.get("strict_aliases", [])),
            source_url=raw.get("source_url", ""),
            source_title=raw.get("source_title", ""),
        )


@dataclass
class Record:
    """A structured row from a live source: a tariff item, a park profile, an activity, a contact."""

    kind: str
    key: str
    payload: dict[str, Any]
    source_id: str
    source_url: str
    retrieved_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Record":
        return cls(**raw)


@dataclass
class ScoredChunk:
    chunk: Chunk
    semantic: float
    keyword: float
    reranker: float
    authority: float
    freshness: float
    score: float
    version_penalized: bool = False

    def components(self) -> dict[str, float | bool]:
        return {
            "semantic": round(self.semantic, 4),
            "keyword": round(self.keyword, 4),
            "reranker": round(self.reranker, 4),
            "authority": round(self.authority, 4),
            "freshness": round(self.freshness, 4),
            "score": round(self.score, 4),
            "version_penalized": self.version_penalized,
        }
