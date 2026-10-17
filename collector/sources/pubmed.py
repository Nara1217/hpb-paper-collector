"""PubMed (NCBI E-utilities) 수집기.

esearch로 기간 내 새로 등록된(Entrez date) 논문 PMID를 찾고, efetch로 상세 정보를 가져옵니다.
"""
from __future__ import annotations

import logging
import os
import time
import xml.etree.ElementTree as ET
from datetime import date

import requests

from ..models import Paper, make_id

log = logging.getLogger(__name__)

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL = "hpb-paper-collector"


def _or_block(terms: list[str]) -> str:
    return "(" + " OR ".join(f'"{t}"[tiab]' for t in terms) + ")"


def build_query(cancer_terms: list[str]) -> str:
    # 주제 키워드는 PubMed 문구 검색에서 부분 일치(예: "spatial transcriptom")가 안 되므로
    # 서버에서는 암종으로만 넓게 찾고, 주제 필터는 로컬 KeywordFilter가 담당합니다.
    return _or_block(cancer_terms)


class PubMedSource:
    name = "pubmed"

    def __init__(self, cfg: dict, session: requests.Session | None = None):
        self.email = cfg.get("email") or os.environ.get("NCBI_EMAIL", "")
        self.api_key = os.environ.get("NCBI_API_KEY", "")
        self.max_results = int(cfg.get("max_results", 5000))
        self.s = session or requests.Session()
        self.delay = 0.12 if self.api_key else 0.4  # NCBI 제한: 키 없으면 초당 3회

    def _params(self, **kw) -> dict:
        p = {"tool": TOOL, **kw}
        if self.email:
            p["email"] = self.email
        if self.api_key:
            p["api_key"] = self.api_key
        return p

    def _get(self, endpoint: str, params: dict) -> requests.Response:
        for attempt in range(4):
            time.sleep(self.delay)
            r = self.s.post(f"{BASE}/{endpoint}", data=params, timeout=60)
            if r.status_code == 200:
                return r
            log.warning("PubMed %s HTTP %s, 재시도 %d", endpoint, r.status_code, attempt + 1)
            time.sleep(2 ** attempt)
        r.raise_for_status()
        return r

    def search(self, query: str, start: date, end: date) -> list[str]:
        r = self._get("esearch.fcgi", self._params(
            db="pubmed", term=query, retmode="json", retmax=self.max_results,
            datetype="edat", mindate=start.strftime("%Y/%m/%d"), maxdate=end.strftime("%Y/%m/%d"),
        ))
        res = r.json()["esearchresult"]
        ids = res.get("idlist", [])
        total = int(res.get("count", 0))
        if total > len(ids):
            log.warning("PubMed 결과 %d건 중 %d건만 가져옴 (max_results를 늘리세요)", total, len(ids))
        return ids

    def fetch(self, pmids: list[str]) -> list[Paper]:
        papers: list[Paper] = []
        for i in range(0, len(pmids), 200):
            r = self._get("efetch.fcgi", self._params(
                db="pubmed", id=",".join(pmids[i:i + 200]), retmode="xml"))
            root = ET.fromstring(r.content)
            for art in root.findall("PubmedArticle"):
                p = parse_article(art)
                if p:
                    papers.append(p)
        return papers

    def collect(self, start: date, end: date, cancer_terms: list[str], topic_terms: list[str]) -> list[Paper]:
        q = build_query(cancer_terms)
        ids = self.search(q, start, end)
        log.info("PubMed: %d건 검색됨", len(ids))
        return self.fetch(ids) if ids else []


def _text(el) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def _entrez_date(art) -> str:
    for d in art.findall("PubmedData/History/PubMedPubDate"):
        if d.get("PubStatus") in ("entrez", "pubmed"):
            y, m, dd = d.findtext("Year"), d.findtext("Month"), d.findtext("Day")
            if y and m and dd:
                return f"{int(y):04d}-{int(m):02d}-{int(dd):02d}"
    return ""


def parse_article(art) -> Paper | None:
    mc = art.find("MedlineCitation")
    if mc is None:
        return None
    pmid = mc.findtext("PMID")
    a = mc.find("Article")
    title = _text(a.find("ArticleTitle")) if a is not None else ""

    parts = []
    for ab in (a.findall("Abstract/AbstractText") if a is not None else []):
        label = ab.get("Label")
        txt = _text(ab)
        parts.append(f"{label}: {txt}" if label else txt)
    abstract = "\n".join(p for p in parts if p)

    authors = []
    for au in (a.findall("AuthorList/Author") if a is not None else []):
        if au.findtext("CollectiveName"):
            authors.append(au.findtext("CollectiveName"))
        else:
            name = " ".join(x for x in (au.findtext("ForeName"), au.findtext("LastName")) if x)
            if name:
                authors.append(name)

    doi = None
    for aid in art.findall("PubmedData/ArticleIdList/ArticleId"):
        if aid.get("IdType") == "doi" and aid.text:
            doi = aid.text.strip()
    pub_types = [_text(t) for t in (a.findall("PublicationTypeList/PublicationType") if a is not None else [])]

    return Paper(
        id=make_id(doi, pmid),
        source="pubmed",
        title=title,
        abstract=abstract,
        authors=authors,
        date=_entrez_date(art),
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        doi=doi,
        pmid=pmid,
        journal=a.findtext("Journal/Title") if a is not None else None,
        is_preprint="Preprint" in pub_types,
        publication_types=pub_types,
    )
