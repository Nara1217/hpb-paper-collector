"""분류 에이전트가 이 저장소를 쓰는 방법 예시 (LLM 호출 부분은 비워 둠).

핵심: 한 번에 몇 편씩만 처리하고, LLM에게는 짧은 결과 JSON만 받습니다.
초록 원문을 응답에 옮겨 적게 하면 응답이 저작권 필터에 걸려 끊길 수 있습니다.

실행: python examples/classify_agent_example.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collector import LocalJSONStorage  # noqa: E402
from collector.classify import apply_results, next_batch, parse_results, skip  # noqa: E402

BATCH = 5


def call_llm(batch: dict) -> str:
    """TODO: 원하는 LLM을 호출하세요. batch["rules"]를 지시문에 그대로 넣고,
    batch["papers"]를 입력으로 주고, JSON 배열 문자열을 돌려받으면 됩니다."""
    return json.dumps([{"id": p["id"], "relevance": None, "labels": p["matched_topics"],
                        "model_systems": [], "validation": [], "summary": ""}
                       for p in batch["papers"]], ensure_ascii=False)


if __name__ == "__main__":
    store = LocalJSONStorage("data")
    while True:
        batch = next_batch(store, size=BATCH)
        if not batch["papers"]:
            break
        try:
            res = apply_results(store, parse_results(call_llm(batch)), agent="example-agent")
        except Exception as e:  # 응답이 끊기거나 형식이 깨지면: 한 편씩 다시, 그래도 안 되면 skip
            print(f"묶음 실패({e}) → 한 편씩 재시도")
            for p in batch["papers"]:
                one = dict(batch, papers=[p])
                try:
                    apply_results(store, parse_results(call_llm(one)), agent="example-agent")
                except Exception as e2:
                    skip(store, p["id"], f"분류 실패: {e2}")
            continue
        print(f"저장 {res['saved']}편, 남은 {res['remaining']}편", res["warnings"] or "")
