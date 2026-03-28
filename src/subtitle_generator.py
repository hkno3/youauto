"""
subtitle_generator.py - Whisper를 사용한 자막 생성 모듈

로컬에서 Whisper를 실행하여 음성 파일로부터 한국어 자막(.srt)을 생성합니다.
완전 무료, 인터넷 연결 불필요 (모델 최초 다운로드 제외).
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = logging.getLogger(__name__)


def _format_timestamp(seconds: float) -> str:
    """
    초 단위 시간을 SRT 타임스탬프 형식으로 변환합니다.

    Args:
        seconds: 초 단위 시간 (float)

    Returns:
        SRT 형식 타임스탬프 (예: "00:01:23,456")
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _segments_to_srt(segments: list) -> str:
    """
    Whisper 세그먼트 목록을 SRT 형식 문자열로 변환합니다.

    Args:
        segments: Whisper 결과의 segments 목록

    Returns:
        SRT 형식 문자열
    """
    srt_lines = []
    for i, segment in enumerate(segments, start=1):
        start = _format_timestamp(segment["start"])
        end = _format_timestamp(segment["end"])
        text = segment["text"].strip()
        srt_lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(srt_lines)


def generate_subtitles(
    audio_path: Path,
    output_filename: str,
    model_size: Optional[str] = None,
    language: Optional[str] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    """
    음성 파일로부터 Whisper를 사용해 한국어 자막(.srt)을 생성합니다.

    Args:
        audio_path: 음성 파일 경로 (.mp3, .wav 등)
        output_filename: 출력 파일명 (예: "subtitles.srt")
        model_size: Whisper 모델 크기 (tiny/base/small/medium/large)
        language: 언어 코드 (기본: "ko")
        output_dir: 출력 디렉토리 (기본: config.TEMP_DIR)

    Returns:
        생성된 SRT 파일 경로

    Raises:
        FileNotFoundError: 음성 파일이 없을 경우
        RuntimeError: 자막 생성 실패 시
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"음성 파일을 찾을 수 없습니다: {audio_path}")

    model_size = model_size or config.WHISPER_MODEL
    language = language or config.WHISPER_LANGUAGE
    save_dir = output_dir or config.TEMP_DIR
    save_dir.mkdir(parents=True, exist_ok=True)
    output_path = save_dir / output_filename

    logger.info(f"자막 생성 시작 - 모델: {model_size}, 언어: {language}")
    logger.debug(f"입력 파일: {audio_path}")

    try:
        import whisper
    except ImportError:
        raise RuntimeError(
            "whisper 패키지가 설치되지 않았습니다. "
            "'pip install openai-whisper' 로 설치하세요."
        )

    try:
        logger.info(f"Whisper 모델 로드 중: {model_size}")
        model = whisper.load_model(model_size)

        logger.info("음성 인식 중...")
        result = model.transcribe(
            str(audio_path),
            language=language,
            task=config.WHISPER_TASK,
            verbose=False,
        )

        segments = result.get("segments", [])
        if not segments:
            raise RuntimeError("Whisper가 음성을 인식하지 못했습니다.")

        srt_content = _segments_to_srt(segments)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        logger.info(
            f"자막 생성 완료 - {len(segments)}개 세그먼트, 경로: {output_path}"
        )
        return output_path

    except Exception as e:
        if output_path.exists():
            output_path.unlink()
        raise RuntimeError(f"자막 생성 중 오류: {e}") from e


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format=config.LOG_FORMAT)

    test_audio = config.OUTPUT_DIR / "test_narration.mp3"
    if test_audio.exists():
        srt_path = generate_subtitles(
            audio_path=test_audio,
            output_filename="test_subtitles.srt",
            output_dir=config.OUTPUT_DIR,
        )
        print(f"생성된 자막 파일: {srt_path}")
        print(srt_path.read_text(encoding="utf-8"))
    else:
        print(f"테스트 파일 없음: {test_audio}")
