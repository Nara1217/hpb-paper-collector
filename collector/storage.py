"""저장소 계층.

수집기와 분류 에이전트는 이 인터페이스(Storage)만 사용합니다.
나중에 GitHub, Google Drive, DB 등으로 옮길 때는 Storage를 상속한 클래스만 새로 만들면 됩니다.

로컬 폴더 구조 (LocalJSONStorage):
  data/
    papers/YYYY-MM-DD.jsonl   수집일별 논문 (한 줄 = 논문 1편, schema/paper.schema.json 형식)
    index.json                id → 파일 경로 (중복 방지 + 빠른 조회)
    reports/YYYY-MM-DD.md     사람이 훑어볼 일일 보고서 (AI 요약 없음)
    runs/<timestamp>.json     실행 기록 (기간, 소스별 건수, 오류)
"""
from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterator

from .models import Paper


class Storage(ABC):
    @abstractmethod
    def seen_ids(self) -> set[str]: ...

    @abstractmethod
    def save_papers(self, papers: list[Paper], batch_date: str) -> int:
        """새 논문만 저장하고 저장한 개수를 돌려줍니다."""

    @abstractmethod
    def save_run_log(self, log: dict[str, Any]) -> None: ...

    @abstractmethod
    def save_report(self, batch_date: str, markdown: str) -> None:
        """사람이 볼 일일 보고서를 저장합니다."""

    @abstractmethod
    def papers_for_batch(self, batch_date: str) -> list[Paper]:
        """해당 수집일에 저장된 논문 전체."""

    @abstractmethod
    def iter_papers(self, only_unclassified: bool = False) -> Iterator[Paper]: ...

    @abstractmethod
    def set_classification(self, paper_id: str, classification: dict[str, Any]) -> None:
        """분류 에이전트가 결과를 기록할 때 사용합니다."""

    def set_classifications(self, updates: dict[str, dict[str, Any]]) -> int:
        """여러 편을 한 번에 기록합니다. 기본 구현은 한 편씩 저장합니다."""
        for pid, c in updates.items():
            self.set_classification(pid, c)
        return len(updates)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


class LocalJSONStorage(Storage):
    def __init__(self, root: str | Path = "data"):
        self.root = Path(root)
        self.papers_dir = self.root / "papers"
        self.index_path = self.root / "index.json"
        self._index: dict[str, str] | None = None

    # --- index ---
    @property
    def index(self) -> dict[str, str]:
        if self._index is None:
            self._index = json.loads(self.index_path.read_text("utf-8")) if self.index_path.exists() else {}
        return self._index

    def _save_index(self) -> None:
        _atomic_write(self.index_path, json.dumps(self.index, ensure_ascii=False, indent=0, sort_keys=True))

    def seen_ids(self) -> set[str]:
        return set(self.index)

    # --- papers ---
    def _read_file(self, rel: str) -> list[dict]:
        p = self.root / rel
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text("utf-8").splitlines() if line.strip()]

    def _write_file(self, rel: str, rows: list[dict]) -> None:
        _atomic_write(self.root / rel, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))

    def save_papers(self, papers: list[Paper], batch_date: str) -> int:
        rel = f"papers/{batch_date}.jsonl"
        rows = self._read_file(rel)
        added = 0
        for p in papers:
            if p.id in self.index:
                continue
            rows.append(p.to_dict())
            self.index[p.id] = rel
            added += 1
        if added:
            self._write_file(rel, rows)
            self._save_index()
        return added

    def save_run_log(self, log: dict[str, Any]) -> None:
        name = log["started_at"].replace(":", "").replace("+", "_")
        _atomic_write(self.root / "runs" / f"{name}.json", json.dumps(log, ensure_ascii=False, indent=2))

    def save_report(self, batch_date: str, markdown: str) -> None:
        _atomic_write(self.root / "reports" / f"{batch_date}.md", markdown)

    def papers_for_batch(self, batch_date: str) -> list[Paper]:
        return [Paper.from_dict(d) for d in self._read_file(f"papers/{batch_date}.jsonl")]

    def iter_papers(self, only_unclassified: bool = False) -> Iterator[Paper]:
        for f in sorted(self.papers_dir.glob("*.jsonl")):
            for line in f.read_text("utf-8").splitlines():
                if not line.strip():
                    continue
                d = json.loads(line)
                if only_unclassified and d.get("classification"):
                    continue
                yield Paper.from_dict(d)

    def set_classification(self, paper_id: str, classification: dict[str, Any]) -> None:
        self.set_classifications({paper_id: classification})

    def set_classifications(self, updates: dict[str, dict[str, Any]]) -> int:
        """파일별로 한 번만 읽고 써서, 묶음 단위로 원자적으로 저장합니다."""
        by_file: dict[str, dict[str, dict[str, Any]]] = {}
        for pid, c in updates.items():
            rel = self.index.get(pid)
            if rel is None:
                raise KeyError(pid)
            by_file.setdefault(rel, {})[pid] = c
        saved = 0
        for rel, items in by_file.items():
            rows = self._read_file(rel)
            for r in rows:
                if r["id"] in items:
                    r["classification"] = items[r["id"]]
                    saved += 1
            self._write_file(rel, rows)
        return saved
