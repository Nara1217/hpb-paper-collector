# 분류 에이전트 작업 규칙

이 저장소의 논문을 분류할 때는 아래 순서를 지켜 주세요. 분류 결과를 쓰다가 응답이 안전 필터에 걸려 끊기는 일을 막기 위한 규칙입니다.

1. `data/papers/*.jsonl`을 직접 고쳐 쓰거나 통째로 다시 출력하지 마세요. 파일 안의 초록 원문이 응답에 그대로 들어가면 저작권 필터에 걸립니다.
2. `python -m collector.classify next --size 5`로 5편씩만 꺼내세요.
3. 결과는 아래 형식의 JSON 배열만 파일에 쓰고 `python -m collector.classify apply <파일>`로 저장하세요.

   ```json
   [{"id": "...", "relevance": 7, "labels": ["spatial"], "model_systems": ["PDO"],
     "validation": ["scRNA-seq→mIF"], "summary": "한국어 1~2문장"}]
   ```

4. `summary`는 연구 대상과 방법을 자기 말로 1~2문장(300자 이내)만 쓰세요. 초록·제목 문장을 옮기지 말고, 실험 절차·용량·제조법 같은 세부 내용은 쓰지 마세요. 따옴표로 원문을 인용하지 마세요.
5. 채팅 응답에는 결과 표나 초록을 다시 적지 말고, `apply`가 돌려준 저장 건수와 경고만 짧게 알려 주세요.
6. 한 묶음이 끊기면 `--size 1`로 한 편씩 다시 하세요. 같은 논문에서 또 끊기면 `python -m collector.classify skip <id> --reason "..."`로 건너뛰고 다음으로 넘어가세요.
7. `python -m collector.classify status`가 `todo: 0`이 될 때까지 2~6을 반복하세요.
