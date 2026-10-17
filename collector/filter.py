"""config.yaml의 키워드로 논문을 거르고 어떤 암종/주제에 걸렸는지 태그를 붙입니다."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Paper


def _compile(term: str) -> re.Pattern:
    # 공백과 하이픈은 서로 바꿔 써도 매칭 ("single cell" = "single-cell" = "singlecell")
    esc = "".join(r"[\s\-]?" if c in " -" else re.escape(c) for c in term)
    if " " not in term and (term.isupper() or any(c.isupper() for c in term[1:])):
        # 한 단어짜리 약어(HCC, scRNA-seq, CosMx): 대소문자 구분, 복수형 s만 허용
        return re.compile(rf"(?<![A-Za-z0-9]){esc}s?(?![A-Za-z0-9])")
    # 일반 단어: 대소문자 무시, 접미사 허용 (organoid → organoids)
    return re.compile(rf"(?<![A-Za-z0-9]){esc}", re.IGNORECASE)


@dataclass
class KeywordFilter:
    cancers: dict[str, list[tuple[str, re.Pattern]]]
    topics: dict[str, list[tuple[str, re.Pattern]]]

    @classmethod
    def from_config(cls, cfg: dict) -> "KeywordFilter":
        def build(groups: dict[str, list[str]]):
            return {g: [(t, _compile(t)) for t in terms] for g, terms in groups.items()}
        return cls(cancers=build(cfg["cancers"]), topics=build(cfg["topics"]))

    @staticmethod
    def _match(text: str, groups) -> tuple[list[str], list[str]]:
        hit_groups, hit_terms = [], []
        for g, pats in groups.items():
            terms = [t for t, p in pats if p.search(text)]
            if terms:
                hit_groups.append(g)
                hit_terms.extend(terms)
        return hit_groups, hit_terms

    def apply(self, paper: Paper) -> bool:
        """조건을 만족하면 태그를 채우고 True를 돌려줍니다."""
        text = f"{paper.title}\n{paper.abstract}"
        cancer, ck = self._match(text, self.cancers)
        if not cancer:
            return False
        topics, tk = self._match(text, self.topics)
        if not topics:
            return False
        paper.matched_cancer = cancer
        paper.matched_topics = topics
        paper.matched_keywords = sorted(set(ck + tk))
        return True

    def all_terms(self, which: str) -> list[str]:
        groups = self.cancers if which == "cancers" else self.topics
        return [t for pats in groups.values() for t, _ in pats]
