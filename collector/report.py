"""사람이 훑어보기 위한 일일 Markdown 보고서 (AI 요약 없음).

data/papers/YYYY-MM-DD.jsonl → data/reports/YYYY-MM-DD.md
GitHub에서 열면 표와 접이식 초록으로 보기 좋게 표시됩니다.
"""
from __future__ import annotations

from collections import Counter

from .models import Paper, clean_abstract

CANCER_KO = {"HCC": "간세포암", "biliary_tract": "담도암", "pancreatic": "췌장암"}
TOPIC_KO = {
    "organoid": "오가노이드", "single_cell": "single-cell", "spatial": "spatial",
    "tumor_microenvironment": "종양미세환경", "drug_resistance": "약물내성", "drug_screening": "약물스크리닝",
}
SOURCE_KO = {"pubmed": "PubMed", "biorxiv": "bioRxiv", "medrxiv": "medRxiv"}
EXCERPT = 400


def _cell(s: str) -> str:
    return " ".join((s or "").split()).replace("|", "\\|")


def _counts(c: Counter, names: dict) -> str:
    return ", ".join(f"{names.get(k, k)} {v}" for k, v in c.most_common()) or "-"


def _sort_key(p: Paper):
    # 주제가 여러 개 걸린 논문을 위로, 같으면 출판 논문 → 프리프린트
    return (-len(p.matched_topics), p.is_preprint, p.title.lower())


def build_daily_report(papers: list[Paper], batch_date: str) -> str:
    papers = sorted(papers, key=_sort_key)
    src = Counter(p.source for p in papers)
    can = Counter(c for p in papers for c in p.matched_cancer)
    top = Counter(t for p in papers for t in p.matched_topics)
    done = sum(1 for p in papers if p.classification)

    out = [
        f"# 간담췌암 논문 수집 – {batch_date}",
        "",
        "> 키워드로 1차 수집한 목록입니다. AI 분류 전이라 관련 없는 논문이 섞여 있을 수 있습니다.",
        "",
        f"- **총 {len(papers)}편** (분류 완료 {done}편)",
        f"- 출처: {_counts(src, SOURCE_KO)}",
        f"- 암종: {_counts(can, CANCER_KO)}",
        f"- 주제: {_counts(top, TOPIC_KO)}",
        "",
    ]
    if not papers:
        out.append("오늘은 조건에 맞는 새 논문이 없습니다.")
        return "\n".join(out) + "\n"

    out += ["## 목록", "", "| # | 제목 | 출처 | 암종 | 주제 |", "|---|---|---|---|---|"]
    for i, p in enumerate(papers, 1):
        src_label = SOURCE_KO.get(p.source, p.source) + (" (프리프린트)" if p.is_preprint else "")
        out.append(
            f"| {i} | [{_cell(p.title)}]({p.url}) | {src_label} | "
            f"{', '.join(CANCER_KO.get(c, c) for c in p.matched_cancer)} | "
            f"{', '.join(TOPIC_KO.get(t, t) for t in p.matched_topics)} |"
        )

    out += ["", "## 초록 미리보기", ""]
    for i, p in enumerate(papers, 1):
        venue = p.journal or SOURCE_KO.get(p.source, p.source)
        abstract = " ".join(clean_abstract(p.abstract).split())
        excerpt = abstract[:EXCERPT] + ("…" if len(abstract) > EXCERPT else "")
        out += [
            "<details>",
            f"<summary><b>{i}. {_cell(p.title)}</b></summary>",
            "",
            f"- {venue} · {p.date} · [원문 링크]({p.url})",
            f"- 걸린 키워드: {', '.join(p.matched_keywords) or '-'}",
            "",
            excerpt or "_초록 없음_",
            "",
            "</details>",
            "",
        ]
    return "\n".join(out)
