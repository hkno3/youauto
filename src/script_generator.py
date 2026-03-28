"""
script_generator.py - Google Gemini API를 사용한 YouTube Shorts 스크립트 생성 모듈
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
    script: str
    title: str
    pexels_keywords: list
    estimated_duration: int
    hook: str
    raw_response: str = ""


def generate_script(topic: str, api_key: Optional[str] = None) -> ScriptResult:
    key = api_key or config.GEMINI_API_KEY
    if not key:
        raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")

    logger.info(f"스크립트 생성 시작 - 주제: '{topic}'")

    system_prompt = """당신은 YouTube Shorts 전문 콘텐츠 크리에이터입니다.
주어진 주제로 한국어 쇼츠 스크립트를 작성합니다.

스크립트 작성 원칙:
- 총 낭독 시간: 30~40초 (한국어 기준 약 250~350음절, 절대 초과 금지)
- 최대 5~6문장 이내
- 첫 문장은 강렬한 후킹 문장
- 핵심 내용 2~3가지만 간결하게
- 이모지 절대 사용 금지
- 마지막에 짧은 행동 유도 1문장

반드시 아래 JSON 형식으로만 응답하세요. JSON 외 다른 텍스트 없이:
{
  "title": "유튜브 쇼츠 제목 (60자 이내, 이모지 없음)",
  "hook": "첫 3초 후킹 문장",
  "script": "전체 낭독 스크립트 (이모지 없이 순수 한국어 텍스트만)",
  "keywords": ["영어키워드1", "영어키워드2", "영어키워드3"]
}"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
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
    try:
        clean = re.sub(r"```(?:json)?|```", "", raw_text).strip()
        data = json.loads(clean)
    except json.JSONDecodeError:
        logger.warning("JSON 파싱 실패, 전체 텍스트를 스크립트로 사용")
        data = {"script": raw_text, "title": topic, "hook": "", "keywords": []}

    script   = data.get("script", "").strip()
    title    = data.get("title", f"{topic} 정보").strip()
    hook     = data.get("hook", "").strip()
    keywords = data.get("keywords", ["lifestyle", "nature", "health"])

    if not script:
        raise RuntimeError("Gemini가 스크립트를 생성하지 못했습니다.")

    char_count = len(script.replace(" ", "").replace("\n", ""))
    estimated_duration = max(10, int(char_count / (config.SCRIPT_WORDS_PER_MINUTE / 60)))

    return ScriptResult(
        topic=topic,
        script=script,
        title=title,
        pexels_keywords=keywords[:5],
        estimated_duration=estimated_duration,
        hook=hook,
        raw_response=raw_text,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format=config.LOG_FORMAT)
    result = generate_script("건강한 아침 루틴")
    print(f"제목: {result.title}")
    print(f"스크립트:\n{result.script}")
    print(f"키워드: {result.pexels_keywords}")
