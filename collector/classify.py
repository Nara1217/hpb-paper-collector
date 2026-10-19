"""분류 에이전트(LLM)용 도구: 작은 묶음으로 꺼내 주고, 결과 JSON만 받아 저장합니다.

LLM이 분류 결과를 쓰다가 응답이 안전 필터에 걸려 끊기는 일을 막기 위한 장치입니다.
주된 원인은 응답 안에 초록 원문을 길게 옮겨 적는 것(저작권 보호 텍스트 재현)과
한 번에 너무 많은 논문을 처리해 응답이 길어지는 것입니다. 그래서 이 도구는

  1. 한 번에 몇 편씩만 꺼내 줍니다 (기본 5편).
  2. 에이전트는 jsonl 파일을 직접 고쳐 쓰지 않고, 아래처럼 짧은 결과 JSON만 씁니다.
       [{"id": "...", "relevance": 7, "labels": [...], "model_systems": [...],
         "validation": [...], "summary": "한두 문장, 자기 말로"}]
  3. apply가 결과를 검사합니다. summary가 너무 길거나 초록 문장을 그대로 옮겼으면
     summary만 비우고 나머지는 저장합니다.
  4. 묶음마다 바로 저장하므로 중간에 끊겨도 그 묶음만 다시 하면 됩니다.
  5. 계속 끊기는 논문은 skip으로 표시해 다음 묶음을 막지 않게 합니다.

사용 예:
  python -m collector.classify status
  python -m collector.classify next --size 5            # 다음 묶음 (JSON, 표준출력)
  python -m collector.classify apply results.json       # 결과 저장 (파일 또는 - 로 표준입력)
  python -m collector.classify skip <id> --reason "응답 중단 반복"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import clean_abstract
from .storage import LocalJSONStorage

MAX_SUMMARY_CHARS = 300
MAX_LIST_ITEMS = 10
MAX_ITEM_CHARS = 60
COPY_RUN_WORDS = 8          # 초록과 연속 8단어 이상 같으면 '옮겨 적기'로 봄
DEFAULT_ABSTRACT_CHARS = 2000

AGENT_RULES = (
    "결과는 JSON 배열만 출력하세요. 초록·제목 원문을 옮겨 적지 말고, "
    f"summary는 한국어 1~2문장({MAX_SUMMARY_CHARS}자 이내)으로 연구 대상과 방법만 자기 말로 쓰세요. "
    "실험 절차·용량·제조법 같은 세부 내용은 쓰지 마세요. 판단이 어려우면 summary를 비워 두세요."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_done(c: Any) -> bool:
    return bool(c)


# ---------- next ----------
def next_batch(store: LocalJSONStorage, size: int = 5, abstract_chars: int = DEFAULT_ABSTRACT_CHARS) -> dict:
    items = []
    for p in store.iter_papers(only_unclassified=True):
        ab = clean_abstract(p.abstract)
        if len(ab) > abstract_chars:
            ab = ab[:abstract_chars] + "…"
        items.append({
            "id": p.id,
            "title": p.title,
            "publication_types": p.publication_types,
            "is_preprint": p.is_preprint,
            "matched_cancer": p.matched_cancer,
            "matched_topics": p.matched_topics,
            "abstract": ab,
        })
        if len(items) >= size:
            break
    return {
        "rules": AGENT_RULES,
        "output_format": [{"id": "<그대로>", "relevance": "0~10", "labels": ["..."],
                           "model_systems": ["..."], "validation": ["..."], "summary": "..."}],
        "remaining_after_this": max(0, count_unclassified(store) - len(items)),
        "papers": items,
    }


def count_unclassified(store: LocalJSONStorage) -> int:
    return sum(1 for _ in store.iter_papers(only_unclassified=True))


# ---------- apply ----------
def parse_results(text: str) -> list[dict]:
    """LLM 출력에서 JSON 배열을 관대하게 읽습니다 (```json 코드 블록, 앞뒤 설명 문장 허용)."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("["), text.rfind("]")
        if s == -1 or e <= s:
            raise ValueError("결과에서 JSON 배열을 찾지 못했습니다")
        data = json.loads(text[s:e + 1])
    if isinstance(data, dict):
        data = data.get("results") or data.get("papers") or [data]
    if not isinstance(data, list):
        raise ValueError("결과는 JSON 배열이어야 합니다")
    return [d for d in data if isinstance(d, dict)]


def _words(s: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9가-힣]+", s.lower())


def copies_source(summary: str, source: str, run: int = COPY_RUN_WORDS) -> bool:
    """summary가 원문(초록·제목)과 연속 run단어 이상 겹치면 True."""
    sw, aw = _words(summary), _words(source)
    if len(sw) < run or len(aw) < run:
        return False
    grams = {tuple(aw[i:i + run]) for i in range(len(aw) - run + 1)}
    return any(tuple(sw[i:i + run]) in grams for i in range(len(sw) - run + 1))


def _str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        x = " ".join(str(x).split())[:MAX_ITEM_CHARS]
        if x and x not in out:
            out.append(x)
    return out[:MAX_LIST_ITEMS]


def sanitize(result: dict, source_text: str, agent: str) -> tuple[dict, list[str]]:
    """결과 한 건을 저장 가능한 형태로 정리하고 경고 목록을 함께 돌려줍니다."""
    warn = []
    rel = result.get("relevance")
    try:
        rel = None if rel in (None, "") else max(0.0, min(10.0, float(rel)))
    except (TypeError, ValueError):
        warn.append(f"relevance 값이 숫자가 아님: {rel!r}")
        rel = None
    if isinstance(rel, float) and rel.is_integer():
        rel = int(rel)

    summary = " ".join(str(result.get("summary") or "").split())
    if copies_source(summary, source_text):
        warn.append("summary가 초록 원문을 옮겨 적어 비웠습니다")
        summary = ""
    elif len(summary) > MAX_SUMMARY_CHARS:
        warn.append(f"summary가 {MAX_SUMMARY_CHARS}자를 넘어 잘랐습니다")
        summary = summary[:MAX_SUMMARY_CHARS].rstrip() + "…"

    c = {
        "status": "done",
        "classified_by": str(result.get("classified_by") or agent),
        "classified_at": _now(),
        "relevance": rel,
        "labels": _str_list(result.get("labels")),
        "model_systems": _str_list(result.get("model_systems")),
        "validation": _str_list(result.get("validation")),
        "summary": summary,
    }
    if warn:
        c["warnings"] = warn
    return c, warn


def apply_results(store: LocalJSONStorage, results: list[dict], agent: str = "llm-agent",
                  overwrite: bool = False) -> dict:
    by_id = {p.id: p for p in store.iter_papers()}
    saved, errors, warnings = 0, [], {}
    updates = {}
    for r in results:
        pid = str(r.get("id") or "").strip()
        p = by_id.get(pid)
        if p is None:
            errors.append(f"모르는 id: {pid or '(비어 있음)'}")
            continue
        if _is_done(p.classification) and not overwrite:
            errors.append(f"이미 분류됨(덮어쓰려면 --overwrite): {pid}")
            continue
        c, w = sanitize(r, f"{p.title}\n{p.abstract}", agent)
        updates[pid] = c
        if w:
            warnings[pid] = w
    if updates:
        saved = store.set_classifications(updates)
    return {"saved": saved, "errors": errors, "warnings": warnings,
            "remaining": count_unclassified(store)}


def skip(store: LocalJSONStorage, paper_id: str, reason: str) -> None:
    store.set_classification(paper_id, {
        "status": "skipped", "classified_at": _now(), "reason": reason,
        "relevance": None, "labels": [], "model_systems": [], "validation": [], "summary": "",
    })


# ---------- CLI ----------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="분류 에이전트용 묶음 처리 도구")
    ap.add_argument("--data", default="data")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    n = sub.add_parser("next")
    n.add_argument("--size", type=int, default=5)
    n.add_argument("--abstract-chars", type=int, default=DEFAULT_ABSTRACT_CHARS)
    a = sub.add_parser("apply")
    a.add_argument("file", help="결과 JSON 파일 경로, 또는 - (표준입력)")
    a.add_argument("--agent", default="llm-agent")
    a.add_argument("--overwrite", action="store_true")
    s = sub.add_parser("skip")
    s.add_argument("id")
    s.add_argument("--reason", default="분류 응답이 반복해서 중단됨")
    args = ap.parse_args(argv)

    store = LocalJSONStorage(args.data)
    out: Any
    if args.cmd == "status":
        papers = list(store.iter_papers())
        st = [(p.classification or {}).get("status", "done") if p.classification else "todo" for p in papers]
        out = {"total": len(papers), "todo": st.count("todo"), "done": st.count("done"),
               "skipped": st.count("skipped")}
    elif args.cmd == "next":
        out = next_batch(store, args.size, args.abstract_chars)
    elif args.cmd == "apply":
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text("utf-8")
        out = apply_results(store, parse_results(text), args.agent, args.overwrite)
    else:
        skip(store, args.id, args.reason)
        out = {"skipped": args.id}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 1 if isinstance(out, dict) and out.get("errors") and not out.get("saved") else 0


if __name__ == "__main__":
    sys.exit(main())
