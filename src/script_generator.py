"""
script_generator.py - Google Gemini API를 사용한 YouTube Shorts 스크립트 생성 모듈
"""

import json
import logging
import re
import requests
from dataclasses import dataclass
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
    pexels_keywords: list[str]
    estimated_duration: int
    hook: str


def generate_script(topic: str, api_key: Optional[str] = None) -> ScriptResult:
    key = api_key or config.GEMINI_API_KEY
    if not key:
        raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")

    logger.info(f"스크립트 생성 시작 - 주제: '{topic}'")

    system_prompt = """당신은 YouTube Shorts 전문 콘텐츠 크리에이터입니다.
주어진 주제로 한국어 쇼츠 스크립트를 작성합니다.

스크립트 작성 원칙:
- 총 낭독 시간: 30~40초 (한국어 기준 약 250~350음절, 절대 초과 금지)
- 스크립트는 최대 5~6문장 이내로 짧게 작성
- 첫 문장은 강렬한 후킹 문장
- 핵심 내용 2~3가지만 간결하게
- 친근한 대화체, 이모지 사용 금지
- 마지막에 짧은 행동 유도 1문장

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요:
{
  "title": "유튜브 쇼츠 제목 (60자 이내)",
  "hook": "첫 3초 후킹 문장",
  "script": "전체 낭독 스크립트 (이모지 없이 순수 텍스트만)",
  "keywords": ["영어키워드1", "영어키워드2", "영어키워드3"]
}"""

    user_prompt = f"주제: {topic}"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "maxOutputTokens": config.GEMINI_MAX_TOKENS,
            "temperature": config.GEMINI_TEMPERATURE,
            "responseMimeType": "application/json",
        },
    }

    logger.debug("Gemini REST API 호출 중...")
    resp = requests.post(url, json=payload, params={"key": key}, timeout=60)

    if resp.status_code != 200:
        raise RuntimeError(f"Gemini API 오류 {resp.status_code}: {resp.text}")

    raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    logger.info(f"Gemini 원본 응답:\n{raw_text}")

    # JSON 파싱
    try:
        # 마크다운 코드블록 제거 후 파싱
        clean = re.sub(r"```(?:json)?|```", "", raw_text).strip()
        data = json.loads(clean)
    except json.JSONDecodeError:
        logger.warning("JSON 파싱 실패, 텍스트 전체를 스크립트로 사용")
        data = {"script": raw_text, "title": topic, "hook": "", "keywords": []}

    script   = data.get("script", "").strip()
    title    = data.get("title", f"{topic} 정보").strip()
    hook     = data.get("hook", "").strip()
    keywords = data.get("keywords", ["lifestyle", "nature", "health"])

    if not script:
        raise RuntimeError("Gemini가 스크립트를 생성하지 못했습니다.")

    char_count = len(script.replace(" ", "").replace("\n", ""))
    estimated_duration = max(10, int(char_count / (config.SCRIPT_WORDS_PER_MINUTE / 60)))

    result = ScriptResult(
        topic=topic,
        script=script,
        title=title,
        pexels_keywords=keywords[:5],
        estimated_duration=estimated_duration,
        hook=hook,
    )

    logger.info(
        f"스크립트 생성 완료 - 제목: '{result.title}', "
        f"예상 시간: {result.estimated_duration}초, "
        f"키워드: {result.pexels_keywords}"
    )
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format=config.LOG_FORMAT)
    result = generate_script("건강한 아침 루틴")
    print(f"제목: {result.title}")
    print(f"후킹: {result.hook}")
    print(f"\n스크립트:\n{result.script}")
    print(f"\nPexels 키워드: {result.pexels_keywords}")
    print(f"예상 낭독 시간: {result.estimated_duration}초")


logger = logging.getLogger(__name__)


@dataclass
class ScriptResult:
    """스크립트 생성 결과를 담는 데이터 클래스"""
    topic: str
    script: str
    title: str
    pexels_keywords: list[str]
    estimated_duration: int
    hook: str


def _strip_markdown(line: str) -> str:
    """마크다운 볼드/이탤릭 마커 제거 (**text** → text)"""
    return re.sub(r"\*+", "", line).strip()


def _parse_script_response(raw_text: str, topic: str) -> ScriptResult:
    logger.info(f"Gemini 원본 응답:\n{raw_text}")  # 원본 응답 로깅

    lines = raw_text.strip().split("\n")

    title = ""
    script_lines = []
    pexels_keywords = []
    hook = ""
    in_script = False
    in_keywords = False

    for line in lines:
        line = line.strip()
        if not line:
            if in_script:
                script_lines.append("")
            continue

        # 마크다운 볼드 제거 후 섹션 헤더 확인 (**제목:** → 제목:)
        clean = _strip_markdown(line)

        if re.match(r"^(제목|TITLE)\s*:", clean):
            title = re.sub(r"^(제목|TITLE)\s*:\s*", "", clean).strip()
            in_script = False
            in_keywords = False

        elif re.match(r"^(후킹|HOOK)\s*:", clean):
            hook = re.sub(r"^(후킹|HOOK)\s*:\s*", "", clean).strip()
            in_script = False
            in_keywords = False

        elif re.match(r"^(스크립트|SCRIPT)\s*:", clean):
            in_script = True
            in_keywords = False
            remainder = re.sub(r"^(스크립트|SCRIPT)\s*:\s*", "", clean).strip()
            if remainder:
                script_lines.append(remainder)

        elif re.match(r"^(키워드|KEYWORDS?)\s*:", clean):
            in_script = False
            in_keywords = True
            remainder = re.sub(r"^(키워드|KEYWORDS?)\s*:\s*", "", clean).strip()
            if remainder:
                keywords = [k.strip() for k in re.split(r"[,，]", remainder) if k.strip()]
                pexels_keywords.extend(keywords)

        elif in_script:
            script_lines.append(clean)

        elif in_keywords:
            keywords = [k.strip() for k in re.split(r"[,，]", clean) if k.strip()]
            pexels_keywords.extend(keywords)

    script = "\n".join(script_lines).strip()

    if not script:
        logger.warning("스크립트 섹션을 찾지 못했습니다. 전체 응답을 스크립트로 사용합니다.")
        # 전체 응답에서 섹션 헤더 줄만 제외하고 본문만 추출
        body_lines = []
        for line in lines:
            clean = _strip_markdown(line.strip())
            if not clean:
                continue
            if re.match(r"^(제목|후킹|스크립트|키워드|TITLE|HOOK|SCRIPT|KEYWORDS?)\s*:", clean):
                continue
            body_lines.append(clean)
        script = "\n".join(body_lines).strip() or raw_text.strip()

    if not title:
        title = f"{topic}에 대한 유용한 정보"

    if not hook:
        first_sentence = script.split(".")[0].strip()
        hook = first_sentence if first_sentence else script[:50]

    if not pexels_keywords:
        pexels_keywords = ["lifestyle", "daily routine", "health"]

    char_count = len(script.replace(" ", "").replace("\n", ""))
    estimated_duration = max(10, int(char_count / (config.SCRIPT_WORDS_PER_MINUTE / 60)))

    return ScriptResult(
        topic=topic,
        script=script,
        title=title,
        pexels_keywords=pexels_keywords[:5],
        estimated_duration=estimated_duration,
        hook=hook,
    )


def generate_script(topic: str, api_key: Optional[str] = None) -> ScriptResult:
    """
    주어진 주제에 대해 YouTube Shorts용 한국어 스크립트를 생성합니다.

    Args:
        topic: 영상 주제 (한국어)
        api_key: Gemini API 키 (미제공 시 config에서 읽음)

    Returns:
        ScriptResult 데이터클래스 인스턴스
    """
    key = api_key or config.GEMINI_API_KEY
    if not key:
        raise ValueError(
            "GEMINI_API_KEY가 설정되지 않았습니다. "
            ".env 파일 또는 환경변수를 확인하세요."
        )

    logger.info(f"스크립트 생성 시작 - 주제: '{topic}'")

    system_prompt = """당신은 YouTube Shorts 전문 콘텐츠 크리에이터입니다.
주어진 주제로 시청자를 즉시 사로잡는 짧고 임팩트 있는 한국어 쇼츠 스크립트를 작성합니다.

스크립트 작성 원칙:
- 총 낭독 시간: 30~40초 (한국어 기준 약 250~350음절, 절대 초과 금지)
- 스크립트는 최대 5~6문장 이내로 짧게 작성
- 첫 3초 안에 시청자의 주목을 끌 강렬한 후킹 문장 포함
- 핵심 내용 2~3가지만 간결하게
- 친근하고 대화체로 작성 (격식체 지양)
- 마지막에 짧은 행동 유도 1문장

반드시 아래 형식으로 응답하세요:

제목: [유튜브 쇼츠 제목, 이모지 포함, 60자 이내]
후킹: [첫 3초 후킹 문장]
스크립트: [전체 낭독 스크립트, 자연스러운 구어체]
키워드: [Pexels 배경영상 검색용 영어 키워드 3~5개, 쉼표 구분]"""

    user_prompt = f"""주제: {topic}

위 주제로 YouTube Shorts 스크립트를 작성해주세요.
키워드는 반드시 영어로, 배경 영상으로 적합한 시각적 요소를 포함하도록 해주세요."""

    # Gemini REST API 직접 호출 (SDK 버전 문제 우회)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "maxOutputTokens": config.GEMINI_MAX_TOKENS,
            "temperature": config.GEMINI_TEMPERATURE,
        },
    }

    logger.debug("Gemini REST API 호출 중...")
    resp = requests.post(url, json=payload, params={"key": key}, timeout=60)

    if resp.status_code != 200:
        raise RuntimeError(f"Gemini API 오류 {resp.status_code}: {resp.text}")

    raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    logger.debug(f"Gemini 응답 수신 (길이: {len(raw_text)}자)")

    result = _parse_script_response(raw_text, topic)

    logger.info(
        f"스크립트 생성 완료 - 제목: '{result.title}', "
        f"예상 시간: {result.estimated_duration}초, "
        f"키워드: {result.pexels_keywords}"
    )

    return result


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.DEBUG, format=config.LOG_FORMAT)

    result = generate_script("건강한 아침 루틴")
    print(f"\n{'='*50}")
    print(f"제목: {result.title}")
    print(f"후킹: {result.hook}")
    print(f"\n스크립트:\n{result.script}")
    print(f"\nPexels 키워드: {result.pexels_keywords}")
    print(f"예상 낭독 시간: {result.estimated_duration}초")
