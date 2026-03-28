"""
tts_generator.py - gTTS를 사용한 한국어 음성 합성 모듈
Google Text-to-Speech 사용 (안정적, 완전 무료)
"""

import logging
import re
import os
import sys
from pathlib import Path
from typing import Optional

from gtts import gTTS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = logging.getLogger(__name__)


def _preprocess_text(text: str) -> str:
    """이모지 및 특수문자 제거"""
    # 이모지 제거
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "]+",
        flags=re.UNICODE,
    )
    text = emoji_pattern.sub("", text)
    text = re.sub(r"[#*_`~>|]", "", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def generate_tts(
    text: str,
    output_filename: str,
    output_dir: Optional[Path] = None,
    **kwargs,  # 호환성을 위해 나머지 인자 무시
) -> Path:
    """
    gTTS로 한국어 텍스트를 MP3로 변환합니다.
    """
    if not text or not text.strip():
        raise ValueError("합성할 텍스트가 비어있습니다.")

    save_dir = output_dir or config.TEMP_DIR
    save_dir.mkdir(parents=True, exist_ok=True)
    output_path = save_dir / output_filename

    cleaned_text = _preprocess_text(text)
    logger.info(f"TTS 시작 - 텍스트 길이: {len(cleaned_text)}자")

    try:
        tts = gTTS(text=cleaned_text, lang="ko", slow=False)
        tts.save(str(output_path))
    except Exception as e:
        raise RuntimeError(f"TTS 합성 실패: {e}") from e

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("TTS 파일이 생성되지 않았습니다.")

    logger.info(f"TTS 완료 - {output_path.stat().st_size/1024:.1f}KB")
    return output_path
