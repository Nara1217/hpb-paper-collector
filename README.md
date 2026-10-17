# 간담췌암 논문 수집기 (paper_collector)

PubMed와 bioRxiv·medRxiv에서 **간세포암·담도암·췌장암** 논문 가운데 아래 주제에 해당하는 새 논문을 매일 모아, 정해진 JSON 형식으로 쌓아 두는 수집 단계입니다.

- 주제: 오가노이드, single-cell, spatial, 종양 미세환경, 약물 내성, 약물 스크리닝

다른 AI 에이전트는 쌓인 데이터를 읽어 다시 분류하고, 그 결과를 같은 레코드의 `classification` 칸에 기록합니다.

```
[PubMed]  ─┐
[bioRxiv] ─┼─► 키워드 1차 필터 ─► 중복 제거 ─► data/papers/YYYY-MM-DD.jsonl ─► 분류 에이전트
[medRxiv] ─┘   (암종 AND 주제)    (DOI 기준)     data/index.json                 (classification 채움)
```

## 설치와 실행

Python 3.9 이상이 필요합니다.

```bash
pip install -r requirements.txt
python -m collector --dry-run        # 저장 없이 건수만 확인
python -m collector                  # 최근 2일치 수집 → data/ 에 저장
python -m collector --days 30        # 처음 한 번은 지난 30일치를 채워 두면 좋습니다
python -m collector --start 2026-09-01 --end 2026-09-30
```

- 매일 실행하는 방법은 정하신 환경에 맞추면 됩니다. cron, 작업 스케줄러, GitHub Actions(`examples/github-actions-collect.yml`) 모두 가능합니다.
- 기간이 겹쳐도 같은 논문은 다시 저장되지 않습니다. 그래서 기본값을 2일로 넉넉하게 잡았습니다.
- NCBI API 키를 환경변수 `NCBI_API_KEY`로 넣으면 PubMed 요청이 빨라집니다. 키가 없어도 동작합니다.

## 관심 범위 바꾸기

`config.yaml`의 `cancers`와 `topics` 목록만 고치면 됩니다. 코드는 건드릴 필요가 없습니다.

- **수집 조건:** 제목이나 초록에 **암종 키워드 1개 이상 AND 주제 키워드 1개 이상**이 있어야 수집됩니다.
- **소문자 키워드:** 대소문자를 무시하고, 뒤에 글자가 붙어도 매칭합니다. 예: `organoid` → organoids
- **약어:** 띄어쓰기 없는 대문자 약어는 대소문자를 구분합니다. 예: `TAM`은 TAMs에는 걸리고 tamoxifen에는 걸리지 않습니다.
- **공백과 하이픈:** 같은 것으로 봅니다. 예: single cell = single-cell
- **PubMed 검색 방식:** 서버에는 암종 키워드로만 넓게 검색하고, 주제 필터는 로컬에서 적용합니다. 그래서 주제 키워드를 바꾼 뒤 다시 실행하면 바로 반영됩니다.

## 저장 형식 (`data/`)

| 경로 | 내용 |
|---|---|
| `papers/YYYY-MM-DD.jsonl` | 그날 수집한 논문. 한 줄이 한 편이고, 형식은 `schema/paper.schema.json`을 따릅니다. |
| `reports/YYYY-MM-DD.md` | 사람이 훑어보기 위한 일일 보고서입니다. 수집 건수, 논문 목록 표, 접어 둔 초록 미리보기가 들어 있고 AI 요약은 없습니다. GitHub에서 열면 보기 좋게 표시됩니다. |
| `index.json` | 논문 id → 파일 경로. 중복을 막고 빠르게 찾는 데 씁니다. |
| `runs/<시각>.json` | 실행 기록: 기간, 소스별로 가져온 수·키워드 일치 수·신규 수, 오류 |

레코드 예시는 아래와 같습니다. 핵심 칸만 보여줍니다.

```json
{"id": "doi:10.1101/2026.10.01.000001", "source": "biorxiv", "is_preprint": true,
 "title": "...", "abstract": "...", "date": "2026-10-14", "url": "...",
 "matched_cancer": ["pancreatic"], "matched_topics": ["spatial", "tumor_microenvironment"],
 "matched_keywords": ["CAF", "PDAC", "Visium", ...], "classification": null}
```

- `id`는 DOI를 우선으로 씁니다. 그래서 프리프린트와 PubMed에 같은 DOI로 올라온 논문은 한 번만 저장됩니다.
- 한 소스가 실패해도 나머지 소스는 계속 수집합니다. 실패 내용은 실행 기록의 `errors`에 남습니다.

## 분류 에이전트 연동

에이전트는 두 가지 방법 중 하나로 데이터를 다룹니다.

1. **파일을 직접 다루기:** `data/papers/*.jsonl`에서 `classification`이 `null`인 줄을 찾아 채웁니다.
2. **Python API 쓰기:**

```python
from collector import LocalJSONStorage
store = LocalJSONStorage("data")
for p in store.iter_papers(only_unclassified=True):
    store.set_classification(p.id, {"relevance": 8, "labels": [...], "model_systems": [...], "validation": [...]})
```

`classification` 안의 권장 칸은 스키마 파일에 있습니다. 예시 코드는 `examples/classify_agent_example.py`에 있습니다.

## 저장 위치 바꾸기

수집기와 에이전트는 `collector/storage.py`의 `Storage` 인터페이스만 사용합니다. GitHub, Google Drive, DB 등으로 옮길 때는 다음 메서드를 구현한 클래스를 하나 추가하고, `main.py`에서 그 클래스를 쓰도록 바꾸면 됩니다.

- `seen_ids`
- `save_papers`
- `save_run_log`
- `save_report`
- `papers_for_batch`
- `iter_papers`
- `set_classification`

## 테스트

```bash
pip install pytest && python -m pytest -q
```

테스트는 네트워크 없이 가짜 데이터로 돌아갑니다. 실제 API 응답 형식을 본떠 만든 데이터입니다.
