"""bioRxiv / medRxiv 수집기 (https://api.biorxiv.org).

API는 키워드 검색을 지원하지 않으므로 기간 내 전체 프리프린트를 받아온 뒤 키워드 필터로 거릅니다.
같은 DOI의 여러 버전은 최신 버전 하나만 남깁니다.
"""
from __future__ import annotations

import logging
import time
from datetime import date

import requests

from ..models import Paper, clean_abstract, make_id

log = logging.getLogger(__name__)

API = "https://api.biorxiv.org/details"


class PreprintSource:
    def __init__(self, server: str, cfg: dict, session: requests.Session | None = None):
        assert server in ("biorxiv", "medrxiv")
        self.name = server
        self.server = server
        self.categories = {c.strip().lower() for c in (cfg.get("categories") or [])}
        self.s = session or requests.Session()

    def _page(self, start: date, end: date, cursor: int) -> dict:
        url = f"{API}/{self.server}/{start.isoformat()}/{end.isoformat()}/{cursor}/json"
        for attempt in range(4):
            try:
                r = self.s.get(url, timeout=60)
                if r.status_code == 200:
                    return r.json()
                log.warning("%s HTTP %s, 재시도 %d", self.server, r.status_code, attempt + 1)
            except requests.RequestException as e:
                log.warning("%s 요청 오류 %s, 재시도 %d", self.server, e, attempt + 1)
            time.sleep(2 ** attempt)
        raise RuntimeError(f"{self.server} API 요청 실패: {url}")

    def fetch_raw(self, start: date, end: date) -> list[dict]:
        items, cursor = [], 0
        while True:
            data = self._page(start, end, cursor)
            coll = data.get("collection") or []
            items.extend(coll)
            msg = (data.get("messages") or [{}])[0]
            total = int(msg.get("total", 0) or 0)
            cursor += len(coll)
            if not coll or cursor >= total:
                break
            time.sleep(0.5)
        log.info("%s: 기간 내 %d건(버전 포함)", self.server, len(items))
        return items

    def collect(self, start: date, end: date, *_args) -> list[Paper]:
        latest: dict[str, dict] = {}
        for it in self.fetch_raw(start, end):
            if self.categories and (it.get("category") or "").strip().lower() not in self.categories:
                continue
            doi = it.get("doi")
            if not doi:
                continue
            prev = latest.get(doi)
            if prev is None or int(it.get("version", 0)) > int(prev.get("version", 0)):
                latest[doi] = it
        return [to_paper(it, self.server) for it in latest.values()]


def to_paper(it: dict, server: str) -> Paper:
    doi = it["doi"].strip()
    ver = str(it.get("version", "1"))
    published = it.get("published")
    authors = [a.strip() for a in (it.get("authors") or "").split(";") if a.strip()]
    return Paper(
        id=make_id(doi, None),
        source=server,
        title=" ".join((it.get("title") or "").split()),
        abstract=clean_abstract(" ".join((it.get("abstract") or "").split())),
        authors=authors,
        date=it.get("date", ""),
        url=f"https://www.{server}.org/content/{doi}v{ver}",
        doi=doi,
        journal=server,
        is_preprint=True,
        category=it.get("category"),
        version=ver,
        published_doi=None if not published or published == "NA" else published,
    )
