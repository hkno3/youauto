"""
script_generator.py - Claude API를 사용한 YouTube Shorts 스크립트 생성 모듈

주어진 주제에 대해 YouTube Shorts에 적합한 한국어 스크립트와
Pexels 검색에 사용할 영어 키워드를 생성합니다.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

import anthropic

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = logging.getLogger(__name__)


@dataclass
class ScriptResult:
    """스크립트 생성 결과를 담는 데이터 클래스"""
    topic: str                    # 원본 주제 (한국어)
    script: str                   # 생성된 스크립트 (한국어)
    title: str                    # 영상 제목 (한국어)
    pexels_keywords: list[str]    # Pexels 검색 키워드 (영어)
    estimated_duration: int       # 예상 낭독 시간 (초)
    hook: str                     # 첫 3초 후킹 문장


def _parse_script_response(raw_text: str, topic: str) -> ScriptResult:
    """
    Claude의 응답 텍스트를 파싱하여 ScriptResult 객체를 반환합니다.

    Args:
        raw_text: Claude API 응답 텍스트
        topic: 원본 주제

    Returns:
        파싱된 ScriptResult 객체
    """
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

        # 제목 파싱
        if line.startswith("제목:") or line.startswith("TITLE:"):
            title = re.sub(r"^(제목:|TITLE:)\s*", "", line).strip()
            in_script = False
            in_keywords = False

        # 후킹 문장 파싱
        elif line.startswith("후킹:") or line.startswith("HOOK:"):
            hook = re.sub(r"^(후킹:|HOOK:)\s*", "", line).strip()
            in_script = False
            in_keywords = False

        # 스크립트 섹션 시작
        elif line.startswith("스크립트:") or line.startswith("SCRIPT:"):
            in_script = True
            in_keywords = False
            remainder = re.sub(r"^(스크립트:|SCRIPT:)\s*", "", line).strip()
            if remainder:
                script_lines.append(remainder)

        # 키워드 섹션 시작
        elif line.startswith("키워드:") or line.startswith("KEYWORDS:"):
            in_script = False
            in_keywords = True
            remainder = re.sub(r"^(키워드:|KEYWORDS:)\s*", "", line).strip()
            if remainder:
                # 쉼표 또는 공백으로 구분된 키워드 파싱
                keywords = [k.strip() for k in re.split(r"[,，]", remainder) if k.strip()]
                pexels_keywords.extend(keywords)

        # 스크립트 내용 수집
        elif in_script:
            script_lines.append(line)

        # 키워드 수집
        elif in_keywords:
            keywords = [k.strip() for k in re.split(r"[,，]", line) if k.strip()]
            pexels_keywords.extend(keywords)

    script = "\n".join(script_lines).strip()

    # 파싱 실패 시 전체 텍스트를 스크립트로 사용
    if not script:
        logger.warning("스크립트 섹션을 찾지 못했습니다. 전체 응답을 스크립트로 사용합니다.")
        script = raw_text.strip()

    if not title:
        title = f"{topic}에 대한 유용한 정보"

    if not hook:
        # 스크립트 첫 문장을 후킹으로 사용
        first_sentence = script.split(".")[0].strip()
        hook = first_sentence if first_sentence else script[:50]

    if not pexels_keywords:
        # 주제를 영어로 직역한 기본 키워드 사용
        pexels_keywords = ["lifestyle", "daily routine", "health"]

    # 예상 낭독 시간 계산 (한국어: 분당 약 300음절)
    char_count = len(script.replace(" ", "").replace("\n", ""))
    estimated_duration = max(10, int(char_count / (config.SCRIPT_WORDS_PER_MINUTE / 60)))

    return ScriptResult(
        topic=topic,
        script=script,
        title=title,
        pexels_keywords=pexels_keywords[:5],  # 최대 5개 키워드
        estimated_duration=estimated_duration,
        hook=hook,
    )


def generate_script(topic: str, api_key: Optional[str] = None) -> ScriptResult:
    """
    주어진 주제에 대해 YouTube Shorts용 한국어 스크립트를 생성합니다.

    Args:
        topic: 영상 주제 (한국어)
        api_key: Anthropic API 키 (미제공 시 config에서 읽음)

    Returns:
        ScriptResult 데이터클래스 인스턴스

    Raises:
        ValueError: API 키가 없을 경우
        anthropic.APIError: API 호출 실패 시
    """
    key = api_key or config.ANTHROPIC_API_KEY
    if not key:
        raise ValueError(
            "ANTHROPIC_API_KEY가 설정되지 않았습니다. "
            ".env 파일 또는 환경변수를 확인하세요."
        )

    logger.info(f"스크립트 생성 시작 - 주제: '{topic}'")

    client = anthropic.Anthropic(api_key=key)

    # 프롬프트 작성
    system_prompt = """당신은 YouTube Shorts 전문 콘텐츠 크리에이터입니다.
주어진 주제로 시청자를 즉시 사로잡는 짧고 임팩트 있는 한국어 쇼츠 스크립트를 작성합니다.

스크립트 작성 원칙:
- 총 낭독 시간: 45~55초 (한국어 기준 약 450~600음절)
- 첫 3초 안에 시청자의 주목을 끌 강렬한 후킹 문장 포함
- 번호 목록, 놀라운 사실, 공감 가는 내용으로 구성
- 친근하고 대화체로 작성 (격식체 지양)
- 마지막에 시청자 행동 유도 (좋아요, 저장, 팔로우)

반드시 아래 형식으로 응답하세요:

제목: [유튜브 쇼츠 제목, 이모지 포함, 60자 이내]
후킹: [첫 3초 후킹 문장]
스크립트: [전체 낭독 스크립트, 자연스러운 구어체]
키워드: [Pexels 배경영상 검색용 영어 키워드 3~5개, 쉼표 구분]"""

    user_prompt = f"""주제: {topic}

위 주제로 YouTube Shorts 스크립트를 작성해주세요.
키워드는 반드시 영어로, 배경 영상으로 적합한 시각적 요소를 포함하도록 해주세요."""

    logger.debug("Claude API 호출 중...")
    message = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=config.CLAUDE_MAX_TOKENS,
        messages=[
            {"role": "user", "content": user_prompt}
        ],
        system=system_prompt,
    )

    raw_text = message.content[0].text
    logger.debug(f"Claude 응답 수신 (길이: {len(raw_text)}자)")

    result = _parse_script_response(raw_text, topic)

    logger.info(
        f"스크립트 생성 완료 - 제목: '{result.title}', "
        f"예상 시간: {result.estimated_duration}초, "
        f"키워드: {result.pexels_keywords}"
    )

    return result


if __name__ == "__main__":
    # 단독 실행 테스트
    logging.basicConfig(level=logging.DEBUG, format=config.LOG_FORMAT)

    result = generate_script("건강한 아침 루틴")
    print(f"\n{'='*50}")
    print(f"제목: {result.title}")
    print(f"후킹: {result.hook}")
    print(f"\n스크립트:\n{result.script}")
    print(f"\nPexels 키워드: {result.pexels_keywords}")
    print(f"예상 낭독 시간: {result.estimated_duration}초")
