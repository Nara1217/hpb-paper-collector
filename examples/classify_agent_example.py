"""분류 에이전트가 이 저장소를 쓰는 방법 예시 (LLM 호출 부분은 비워 둠).

실행: python examples/classify_agent_example.py
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collector import LocalJSONStorage  # noqa: E402


def classify(paper) -> dict:
    # TODO: 여기서 원하는 LLM/에이전트를 호출해 paper.title, paper.abstract를 분석하세요.
    return {
        "classified_by": "example-agent",
        "classified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "relevance": None,
        "labels": paper.matched_topics,
        "model_systems": [],
        "validation": [],
        "summary": "",
    }


if __name__ == "__main__":
    store = LocalJSONStorage("data")
    todo = list(store.iter_papers(only_unclassified=True))
    print(f"분류 대기 {len(todo)}편")
    for p in todo:
        store.set_classification(p.id, classify(p))
