"""
tts_generator.py - Edge TTS를 사용한 한국어 음성 합성 모듈

Microsoft Edge TTS를 통해 한국어 텍스트를 고품질 음성 파일로 변환합니다.
ko-KR-SunHiNeural 음성을 기본으로 사용합니다.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import edge_tts

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = logging.getLogger(__name__)


async def _synthesize_async(
    text: str,
    output_path: Path,
    voice: str,
    rate: str,
    volume: str,
    pitch: str,
) -> None:
    """
    비동기 TTS 합성 내부 함수.

    Args:
        text: 합성할 텍스트
        output_path: 출력 파일 경로 (.mp3)
        voice: 사용할 음성 이름
        rate: 말하기 속도 (예: "+0%", "+20%", "-10%")
        volume: 볼륨 (예: "+0%", "+50%")
        pitch: 음높이 (예: "+0Hz", "+5Hz")
    """
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        volume=volume,
        pitch=pitch,
    )
    await communicate.save(str(output_path))


def generate_tts(
    text: str,
    output_filename: str,
    voice: Optional[str] = None,
    rate: Optional[str] = None,
    volume: Optional[str] = None,
    pitch: Optional[str] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    """
    텍스트를 한국어 음성으로 변환하여 MP3 파일로 저장합니다.

    Args:
        text: 합성할 한국어 텍스트
        output_filename: 출력 파일명 (확장자 포함, 예: "narration.mp3")
        voice: 사용할 Edge TTS 음성 (기본: config.TTS_VOICE)
        rate: 말하기 속도 (기본: config.TTS_RATE)
        volume: 볼륨 (기본: config.TTS_VOLUME)
        pitch: 음높이 (기본: config.TTS_PITCH)
        output_dir: 출력 디렉토리 (기본: config.TEMP_DIR)

    Returns:
        생성된 오디오 파일의 절대 경로

    Raises:
        ValueError: 텍스트가 비어있을 경우
        RuntimeError: TTS 합성 실패 시
    """
    if not text or not text.strip():
        raise ValueError("합성할 텍스트가 비어있습니다.")

    # 설정 기본값 적용
    voice = voice or config.TTS_VOICE
    rate = rate or config.TTS_RATE
    volume = volume or config.TTS_VOLUME
    pitch = pitch or config.TTS_PITCH
    save_dir = output_dir or config.TEMP_DIR

    save_dir.mkdir(parents=True, exist_ok=True)
    output_path = save_dir / output_filename

    logger.info(f"TTS 합성 시작 - 음성: {voice}, 텍스트 길이: {len(text)}자")
    logger.debug(f"출력 경로: {output_path}")

    # 텍스트 전처리: 자막 생성에 방해되는 특수문자 정리
    cleaned_text = _preprocess_text(text)

    # 디버그: TTS에 전달되는 텍스트 파일에 저장
    debug_path = save_dir / "tts_debug.txt"
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(cleaned_text)
    logger.info(f"TTS 입력 텍스트 ({len(cleaned_text)}자):\n{cleaned_text}")

    # 재시도 로직 (Edge TTS 서버 간헐적 오류 대응)
    last_error = None
    for attempt in range(1, 4):
        try:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError("루프가 닫혔습니다.")
                loop.run_until_complete(
                    _synthesize_async(cleaned_text, output_path, voice, rate, volume, pitch)
                )
            except RuntimeError:
                asyncio.run(
                    _synthesize_async(cleaned_text, output_path, voice, rate, volume, pitch)
                )

            if output_path.exists() and output_path.stat().st_size > 0:
                break  # 성공
            raise RuntimeError("생성된 파일이 비어있습니다.")

        except Exception as e:
            last_error = e
            logger.warning(f"TTS 시도 {attempt}/3 실패: {e}")
            if attempt < 3:
                import time
                time.sleep(2 * attempt)
    else:
        raise RuntimeError(f"TTS 합성 중 오류 발생: {last_error}") from last_error

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"TTS 파일이 생성되지 않았습니다: {output_path}")

    file_size_kb = output_path.stat().st_size / 1024
    logger.info(f"TTS 합성 완료 - 파일 크기: {file_size_kb:.1f}KB, 경로: {output_path}")

    return output_path


def _preprocess_text(text: str) -> str:
    """
    TTS 합성 전 텍스트를 정제합니다.

    - 과도한 공백 제거
    - TTS에 방해되는 특수기호 처리
    - 이모지 제거 (TTS가 읽지 못하는 경우 방지)

    Args:
        text: 원본 텍스트

    Returns:
        정제된 텍스트
    """
    import re

    # 연속 공백을 단일 공백으로
    text = re.sub(r" {2,}", " ", text)

    # 연속 줄바꿈을 최대 2개로 제한
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 이모지 제거 (유니코드 이모지 범위)
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "]+",
        flags=re.UNICODE,
    )
    text = emoji_pattern.sub("", text)

    # 마크다운 기호 제거
    text = re.sub(r"[#*_`~>|]", "", text)

    return text.strip()


async def list_korean_voices() -> list[dict]:
    """
    사용 가능한 한국어 Edge TTS 음성 목록을 반환합니다.

    Returns:
        한국어 음성 정보 딕셔너리 목록
    """
    voices = await edge_tts.list_voices()
    korean_voices = [v for v in voices if v.get("Locale", "").startswith("ko-")]
    return korean_voices


if __name__ == "__main__":
    # 단독 실행 테스트
    logging.basicConfig(level=logging.DEBUG, format=config.LOG_FORMAT)

    test_text = """안녕하세요! 오늘은 건강한 아침 루틴에 대해 알아볼게요.
아침에 일어나자마자 물 한 잔을 마시면 신진대사가 활발해집니다.
이 영상이 도움이 됐다면 좋아요와 팔로우 부탁드려요!"""

    output_path = generate_tts(
        text=test_text,
        output_filename="test_narration.mp3",
        output_dir=config.OUTPUT_DIR,
    )
    print(f"생성된 파일: {output_path}")
