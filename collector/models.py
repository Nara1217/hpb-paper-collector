"""논문 레코드 데이터 형식. schema/paper.schema.json과 같은 구조입니다."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Optional

SCHEMA_VERSION = "1.0"

# 초록 끝에 붙는 저작권·라이선스 문구. 분류 에이전트가 이를 옮겨 적으면
# 응답이 저작권 필터에 걸릴 수 있으므로 수집 단계에서 떼어 냅니다.
_COPYRIGHT_RE = re.compile(
    r"(?:\s|^)(?:©|\(c\)\s*\d{4}|copyright\b|all rights reserved|"
    r"this article is protected by copyright|published by elsevier|"
    r"this is an open access article|licensee\b|creative commons)[^\n]*$",
    re.IGNORECASE,
)


def clean_abstract(text: str) -> str:
    """줄마다 끝에 붙은 저작권/라이선스 문구를 지웁니다."""
    lines = []
    for line in (text or "").splitlines():
        m = _COPYRIGHT_RE.search(line)
        # 문장 중간의 우연한 단어를 지우지 않도록, 줄 끝 400자 안에서 시작할 때만 지움
        if m and len(line) - m.start() <= 400:
            line = line[:m.start()]
        line = line.rstrip()
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


def make_id(doi: Optional[str], pmid: Optional[str]) -> str:
    """출처가 달라도 같은 논문이면 같은 id가 되도록 DOI를 우선 사용합니다."""
    if doi:
        return "doi:" + doi.strip().lower()
    if pmid:
        return "pmid:" + pmid.strip()
    raise ValueError("DOI나 PMID 중 하나는 있어야 합니다")


@dataclass
class Paper:
    id: str
    source: str                      # pubmed | biorxiv | medrxiv
    title: str
    abstract: str
    authors: list[str]
    date: str                        # YYYY-MM-DD (PubMed 등록일 / 프리프린트 게시일)
    url: str
    doi: Optional[str] = None
    pmid: Optional[str] = None
    journal: Optional[str] = None    # 프리프린트는 서버 이름
    is_preprint: bool = False
    category: Optional[str] = None   # bioRxiv/medRxiv 카테고리
    version: Optional[str] = None    # 프리프린트 버전
    published_doi: Optional[str] = None  # 프리프린트가 저널에 출판된 경우 그 DOI
    publication_types: list[str] = field(default_factory=list)  # PubMed: Review, Journal Article 등
    matched_cancer: list[str] = field(default_factory=list)
    matched_topics: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    collected_at: str = ""
    schema_version: str = SCHEMA_VERSION
    # 분류 에이전트가 채우는 칸. 수집 단계에서는 항상 None.
    classification: Optional[dict[str, Any]] = None

    def __post_init__(self) -> None:
        if not self.collected_at:
            self.collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Paper":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
