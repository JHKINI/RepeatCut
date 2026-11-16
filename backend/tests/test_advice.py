"""학습 추천(advice.py) 테스트. 실제 Gemini는 부르지 않고 가짜 함수로 바꿔서 확인한다.

실행 (프로젝트 루트에서):  pytest backend/tests -v
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from repeatcut import advice  # noqa: E402

GOOD_ANSWER = json.dumps({
    "summary": "농도 문제에서 계산실수가 많아요.",
    "weak_points": [{"title": "#농도", "why": "오답 5건 중 3건이에요.", "action": "농도 공식을 다시 정리해요."}],
    "plan": ["농도 오답을 다시 풀어요.", "풀이 과정을 적어요.", "3일 뒤에 다시 풀어요."],
    "today": "농도 오답 1개를 다시 풀어요.",
}, ensure_ascii=False)


def make_stats(total=5):
    """repository.get_stats()와 같은 모양의 통계."""
    return {
        "total": total,
        "keywords": [{"keyword_id": 1, "name": "농도", "count": 3}, {"keyword_id": 2, "name": "일률", "count": 2}],
        "reasons": [
            {"reason_type": "개념이해부족", "count": 1, "ratio": 0.2},
            {"reason_type": "계산실수", "count": 4, "ratio": 0.8},
            {"reason_type": "기타", "count": 0, "ratio": 0},
        ],
        "papers": [{"paper_id": 1, "display_title": "2025 지역농협 상반기", "mistake_count": 5, "total_questions": 60, "wrong_rate": 0.083}],
        "retry": {
            "attempts": 3, "correct": 1, "correct_rate": 0.333, "solved": 1, "still_wrong": 1, "not_retried": 3,
            "repeat_wrong": [{"mistake_id": 1, "paper_title": "2025 지역농협 상반기", "problem_no": "12", "keyword": "농도",
                              "attempt_count": 2, "wrong_count": 2, "wrong_total": 3, "wrong_answers": ["2", "3"],
                              "wrong_reasons": ["개념이해부족", "계산실수"], "correct_answer": "4"}],
        },
    }


class FakeGemini:
    """Gemini 대신 쓰는 가짜. 몇 번 불렸는지와 받은 프롬프트를 기억한다."""

    def __init__(self, answer=GOOD_ANSWER, error=None):
        self.answer, self.error, self.calls, self.prompts = answer, error, 0, []

    def __call__(self, api_key, model, prompt, timeout_seconds):
        self.calls += 1
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.answer


def run(stats, fake, cache=None, api_key="test-key"):
    return advice.make_advice(stats, api_key, "test-model", 5, {} if cache is None else cache, caller=fake)


def test_too_few_mistakes_does_not_call_ai():
    fake = FakeGemini()
    result = run(make_stats(total=2), fake)
    assert result["source"] == "none" and result["advice"] is None and fake.calls == 0


def test_no_api_key_gives_rule_based_advice():
    fake = FakeGemini()
    result = run(make_stats(), fake, api_key="")
    assert result["source"] == "rule" and fake.calls == 0 and "API 키" in result["notice"]
    assert result["advice"]["weak_points"][0]["title"] == "#농도"
    assert result["advice"]["weak_points"][1]["title"] == "계산실수"  # 가장 많은 이유
    assert len(result["advice"]["plan"]) >= 3 and result["advice"]["today"]


def test_success_uses_ai_answer():
    fake = FakeGemini()
    result = run(make_stats(), fake)
    assert result["source"] == "gemini" and result["cached"] is False and result["model"] == "test-model"
    assert result["advice"]["summary"] == "농도 문제에서 계산실수가 많아요." and len(result["advice"]["plan"]) == 3


def test_prompt_has_only_statistics():
    fake = FakeGemini()
    run(make_stats(), fake)
    prompt = fake.prompts[0]
    assert "농도" in prompt and "계산실수" in prompt and "2025 지역농협 상반기" in prompt
    assert "test-key" not in prompt  # API 키는 프롬프트에 들어가지 않는다
    assert "mistake_id" not in prompt and "problem_no" not in prompt  # 요약에 넣지 않은 값은 보내지 않는다


def test_same_statistics_use_cache():
    fake, cache = FakeGemini(), {}
    first = run(make_stats(), fake, cache)
    second = run(make_stats(), fake, cache)
    assert fake.calls == 1 and second["cached"] is True and second["advice"] == first["advice"]
    changed = make_stats()
    changed["keywords"][0]["count"] = 4  # 통계가 바뀌면 다시 부른다
    run(changed, fake, cache)
    assert fake.calls == 2


def test_errors_fall_back_to_rule_and_are_not_cached():
    for kind in ["rate_limit", "bad_request", "server", "network"]:
        fake, cache = FakeGemini(error=advice.GeminiError(kind)), {}
        result = run(make_stats(), fake, cache)
        assert result["source"] == "rule" and result["error_kind"] == kind and result["advice"]["plan"], kind
        assert result["notice"] == advice.ERROR_NOTICES[kind] and cache == {}
    # 실패 뒤에 다시 누르면 다시 시도한다
    fake, cache = FakeGemini(error=advice.GeminiError("rate_limit")), {}
    run(make_stats(), fake, cache)
    fake.error = None
    assert run(make_stats(), fake, cache)["source"] == "gemini" and fake.calls == 2


def test_broken_ai_answers_fall_back():
    broken = ["그냥 글", "[1, 2]", json.dumps({"summary": "", "plan": ["a"]}), json.dumps({"summary": "요약", "plan": []}),
              json.dumps({"summary": "요약"})]
    for answer in broken:
        result = run(make_stats(), FakeGemini(answer=answer))
        assert result["source"] == "rule" and result["error_kind"] == "bad_response", answer


def test_ai_answer_is_cleaned():
    messy = "```json\n" + json.dumps({
        "summary": "요약   입니다", "weak_points": [{"title": "가"}, "이상한 값", {"why": "제목 없음"}, {"title": "나"}, {"title": "다"}, {"title": "라"}],
        "plan": ["1", "", 3, "2", "3", "4", "5", "6"], "today": 123, "extra": "무시",
    }, ensure_ascii=False) + "\n```"
    parsed = advice.parse_advice(messy)
    assert parsed["summary"] == "요약 입니다" and parsed["today"] == ""
    assert [point["title"] for point in parsed["weak_points"]] == ["가"]  # 앞의 3개 중 모양이 맞는 것만
    assert parsed["plan"] == ["1", "2", "3", "4", "5"]
    long_text = advice.parse_advice(json.dumps({"summary": "가" * 1000, "plan": ["a"]}))
    assert len(long_text["summary"]) == advice.MAX_TEXT_LENGTH


def test_call_gemini_request_and_errors():
    """call_gemini가 보내는 요청 모양과 HTTP 오류 구분. (urlopen을 가짜로 바꿔서 실제로는 아무 데도 연결하지 않는다)"""
    import io
    import urllib.error
    import urllib.request

    seen = {}

    class FakeResponse(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): return False

    def fake_urlopen(request, timeout=None):
        seen["url"], seen["headers"], seen["body"], seen["timeout"] = request.full_url, dict(request.header_items()), json.loads(request.data), timeout
        return FakeResponse(json.dumps({"candidates": [{"content": {"parts": [{"text": "{\"a\""}, {"text": ": 1}"}]}}]}).encode())

    original = urllib.request.urlopen
    try:
        urllib.request.urlopen = fake_urlopen
        assert advice.call_gemini("secret-key", "my-model", "프롬프트", 7) == '{"a": 1}'
        assert seen["url"].endswith("/models/my-model:generateContent") and "secret-key" not in seen["url"]
        assert seen["headers"]["X-goog-api-key"] == "secret-key" and seen["timeout"] == 7
        assert seen["body"]["contents"][0]["parts"][0]["text"] == "프롬프트"
        assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"

        def raising(code):
            def opener(request, timeout=None):
                raise urllib.error.HTTPError(request.full_url, code, "error", {}, None)
            return opener

        for code, kind in [(429, "rate_limit"), (400, "bad_request"), (403, "bad_request"), (404, "bad_request"), (500, "server"), (503, "server")]:
            urllib.request.urlopen = raising(code)
            try:
                advice.call_gemini("k", "m", "p", 1)
                assert False, "오류가 나야 한다"
            except advice.GeminiError as error:
                assert error.kind == kind, (code, error.kind)

        def timing_out(request, timeout=None):
            raise TimeoutError("timed out")
        urllib.request.urlopen = timing_out
        try:
            advice.call_gemini("k", "m", "p", 1)
            assert False
        except advice.GeminiError as error:
            assert error.kind == "network"

        urllib.request.urlopen = lambda request, timeout=None: FakeResponse(json.dumps({"candidates": []}).encode())
        try:
            advice.call_gemini("k", "m", "p", 1)
            assert False
        except advice.GeminiError as error:
            assert error.kind == "bad_response"
    finally:
        urllib.request.urlopen = original


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in list(globals().items()) if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"통과  {name}")
        except Exception as error:  # noqa: BLE001
            failed += 1
            print(f"실패  {name}: {type(error).__name__}: {error}")
    print(f"\n{len(tests) - failed}/{len(tests)} 통과")
    sys.exit(1 if failed else 0)
