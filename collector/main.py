"""수집 실행 진입점.

사용 예:
  python -m collector                     # 최근 2일치 수집 (겹치는 날은 자동 중복 제거)
  python -m collector --days 7            # 최근 7일
  python -m collector --start 2026-10-01 --end 2026-10-15
  python -m collector --dry-run           # 저장하지 않고 건수만 확인
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

from .filter import KeywordFilter
from .report import build_daily_report
from .sources import PreprintSource, PubMedSource
from .storage import LocalJSONStorage

log = logging.getLogger("collector")


def build_sources(cfg: dict, session: requests.Session):
    src_cfg = cfg.get("sources", {})
    out = []
    if src_cfg.get("pubmed", {}).get("enabled", True):
        out.append(PubMedSource(src_cfg.get("pubmed", {}), session))
    for server in ("biorxiv", "medrxiv"):
        if src_cfg.get(server, {}).get("enabled", True):
            out.append(PreprintSource(server, src_cfg.get(server, {}), session))
    return out


def run(cfg: dict, storage, start: date, end: date, dry_run: bool = False) -> dict:
    kf = KeywordFilter.from_config(cfg)
    session = requests.Session()
    session.headers["User-Agent"] = "hpb-paper-collector/1.0"
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    seen = storage.seen_ids()

    report = {"started_at": started, "start": start.isoformat(), "end": end.isoformat(),
              "sources": {}, "saved": 0, "errors": []}
    kept: dict[str, object] = {}
    for src in build_sources(cfg, session):
        try:
            raw = src.collect(start, end, kf.all_terms("cancers"), kf.all_terms("topics"))
        except Exception as e:  # 한 소스가 실패해도 나머지는 계속
            log.exception("%s 수집 실패", src.name)
            report["errors"].append(f"{src.name}: {e}")
            continue
        matched = [p for p in raw if kf.apply(p)]
        new = 0
        for p in matched:
            if p.id in seen or p.id in kept:
                continue
            kept[p.id] = p
            new += 1
        report["sources"][src.name] = {"fetched": len(raw), "matched": len(matched), "new": new}
        log.info("%s: 가져옴 %d → 키워드 일치 %d → 신규 %d", src.name, len(raw), len(matched), new)

    if not dry_run:
        today = datetime.now(timezone.utc).date().isoformat()
        report["saved"] = storage.save_papers(list(kept.values()), today)
        # 같은 날 여러 번 실행해도 그날 저장된 전체 논문으로 보고서를 다시 만듭니다.
        storage.save_report(today, build_daily_report(storage.papers_for_batch(today), today))
        report["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        storage.save_run_log(report)
    else:
        report["would_save"] = len(kept)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="간담췌암 논문 수집기")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--data", default="data", help="저장 폴더")
    ap.add_argument("--days", type=int, default=2, help="오늘부터 며칠 전까지 (기본 2)")
    ap.add_argument("--start", type=date.fromisoformat)
    ap.add_argument("--end", type=date.fromisoformat)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = yaml.safe_load(Path(a.config).read_text("utf-8"))
    end = a.end or datetime.now(timezone.utc).date()
    start = a.start or (end - timedelta(days=a.days))

    report = run(cfg, LocalJSONStorage(a.data), start, end, a.dry_run)
    print(yaml.safe_dump(report, allow_unicode=True, sort_keys=False))
    # 모든 소스가 실패했을 때만 실패 코드 (자동화 도구에서 알림 받기용)
    return 1 if report["errors"] and not report["sources"] else 0


if __name__ == "__main__":
    sys.exit(main())
