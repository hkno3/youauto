"""
script_generator.py - Google Gemini API를 사용한 YouTube Shorts 스크립트 생성 모듈

문장별 Pexels 검색 키워드를 포함한 구조화된 스크립트를 생성합니다.
"""

import json
import logging
import re
import requests
from dataclasses import dataclass, field
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = logging.getLogger(__name__)


@dataclass
class ScriptResult:
    topic: str
    title: str
    hook: str
    script: str
    pexels_keywords: list
    estimated_duration: int
    raw_response: str = ""
    sentences: list = field(default_factory=list)
    # sentences 형식: [{"text": "문장 텍스트", "keyword": "english keyword"}, ...]


def generate_script(topic: str, api_key: Optional[str] = None) -> ScriptResult:
    """
    Gemini API로 YouTube Shorts 스크립트를 생성합니다.

    Args:
        topic: 영상 주제 (한국어)
        api_key: Gemini API 키 (미제공 시 config에서 읽음)

    Returns:
        ScriptResult 인스턴스 (sentences 필드 포함)

    Raises:
        ValueError: API 키가 없을 경우
        RuntimeError: API 오류 또는 스크립트 생성 실패 시
    """
    key = api_key or config.GEMINI_API_KEY
    if not key:
        raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")

    logger.info(f"스크립트 생성 시작 - 주제: '{topic}'")

    system_prompt = """당신은 YouTube Shorts 전문 콘텐츠 크리에이터입니다.
주어진 주제로 한국어 쇼츠 스크립트를 작성합니다.

스크립트 작성 원칙:
- 총 낭독 시간: 30~45초 (한국어 기준 약 250~380음절, 절대 초과 금지)
- 최대 6~8문장 이내
- 첫 문장은 강렬한 후킹 문장
- 핵심 내용 3~5가지를 간결하게
- 이모지 절대 사용 금지
- 마지막에 짧은 행동 유도 1문장
- 각 문장마다 Pexels 영상 검색에 사용할 영어 키워드를 지정 (구체적이고 시각적인 단어)

반드시 아래 JSON 형식으로만 응답하세요. JSON 외 다른 텍스트 없이:
{
  "title": "유튜브 쇼츠 제목 (60자 이내, 이모지 없음)",
  "hook": "첫 3초 후킹 문장",
  "script": "전체 낭독 스크립트 (이모지 없이 순수 한국어 텍스트만, 문장을 이어붙인 전체 텍스트)",
  "sentences": [
    {"text": "문장1 텍스트", "keyword": "english keyword for pexels"},
    {"text": "문장2 텍스트", "keyword": "english keyword for pexels"}
  ]
}

sentences의 keyword는 반드시 영어로, Pexels에서 관련 영상이 잘 검색될 법한 구체적인 단어나 구문으로 작성하세요.
예: "drinking water morning", "meditation sunrise", "healthy breakfast food"
"""

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.GEMINI_MODEL}:generateContent"
    )
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": f"주제: {topic}"}]}],
        "generationConfig": {
            "maxOutputTokens": config.GEMINI_MAX_TOKENS,
            "temperature": config.GEMINI_TEMPERATURE,
        },
    }

    resp = requests.post(url, json=payload, params={"key": key}, timeout=60)

    if resp.status_code != 200:
        raise RuntimeError(f"Gemini API 오류 {resp.status_code}: {resp.text}")

    raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    logger.info(f"Gemini 원본 응답:\n{raw_text}")

    # JSON 파싱 (마크다운 코드블록 제거 후)
    clean = re.sub(r"```[\w]*", "", raw_text).replace("```", "").strip()
    data = None

    # 시도 1: 정상 JSON 파싱
    try:
        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
    except json.JSONDecodeError:
        pass

    # 시도 2: JSON이 잘린 경우 각 필드를 정규식으로 직접 추출
    if not data:
        logger.warning("JSON 파싱 실패, 정규식으로 필드 추출 시도")

        def extract_field(fname, text):
            m = re.search(rf'"{fname}"\s*:\s*"(.*?)(?<!\\)"', text, re.DOTALL)
            return m.group(1).strip() if m else ""

        def extract_list(fname, text):
            m = re.search(rf'"{fname}"\s*:\s*\[(.*?)\]', text, re.DOTALL)
            if m:
                return [k.strip().strip('"') for k in m.group(1).split(',') if k.strip()]
            return []

        # sentences 배열 추출 (복잡한 구조)
        sentences_raw = []
        sentences_match = re.search(
            r'"sentences"\s*:\s*\[(.*?)\]', clean, re.DOTALL
        )
        if sentences_match:
            sentence_items = re.findall(
                r'\{\s*"text"\s*:\s*"(.*?)"\s*,\s*"keyword"\s*:\s*"(.*?)"\s*\}',
                sentences_match.group(1),
                re.DOTALL,
            )
            sentences_raw = [
                {"text": t.strip(), "keyword": k.strip()}
                for t, k in sentence_items
            ]

        data = {
            "title": extract_field("title", clean) or topic,
            "hook": extract_field("hook", clean),
            "script": extract_field("script", clean),
            "sentences": sentences_raw,
        }

    script = data.get("script", "").strip()
    title = data.get("title", f"{topic} 정보").strip()
    hook = data.get("hook", "").strip()
    sentences = data.get("sentences", [])

    # sentences에서 pexels_keywords 추출 (fallback용)
    pexels_keywords = [s["keyword"] for s in sentences if s.get("keyword")]
    if not pexels_keywords:
        pexels_keywords = ["lifestyle", "nature", "health"]

    if not script:
        # script가 없으면 sentences에서 조합 시도
        if sentences:
            script = " ".join(s["text"] for s in sentences if s.get("text"))
        if not script:
            raise RuntimeError("Gemini가 스크립트를 생성하지 못했습니다.")

    char_count = len(script.replace(" ", "").replace("\n", ""))
    estimated_duration = max(10, int(char_count / (config.SCRIPT_WORDS_PER_MINUTE / 60)))

    return ScriptResult(
        topic=topic,
        title=title,
        hook=hook,
        script=script,
        pexels_keywords=pexels_keywords[:8],
        estimated_duration=estimated_duration,
        raw_response=raw_text,
        sentences=sentences,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format=config.LOG_FORMAT)
    result = generate_script("건강한 아침 루틴")
    print(f"제목: {result.title}")
    print(f"스크립트:\n{result.script}")
    print(f"키워드: {result.pexels_keywords}")
    print(f"문장 수: {len(result.sentences)}")
    for i, s in enumerate(result.sentences):
        print(f"  [{i+1}] {s['text']} → {s['keyword']}")
