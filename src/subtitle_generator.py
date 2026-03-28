"""
subtitle_generator.py - Whisper를 사용한 단어별 팝업 자막 생성 모듈

word_timestamps=True를 사용해 단어 단위 타임스탬프를 얻고,
각 단어가 하나씩 나타나는 ASS 포맷 자막 파일을 생성합니다.
1080x1920 YouTube Shorts 세로형 영상 최적화.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = logging.getLogger(__name__)


def _format_srt_timestamp(seconds: float) -> str:
    """초를 SRT 타임스탬프 형식으로 변환 (00:01:23,456)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_ass_timestamp(seconds: float) -> str:
    """초를 ASS 타임스탬프 형식으로 변환 (H:MM:SS.cs - 센티초 단위)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centisecs = int((seconds % 1) * 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"


def _segments_to_srt(segments: list) -> str:
    """Whisper 세그먼트를 SRT 포맷 문자열로 변환."""
    lines = []
    for i, seg in enumerate(segments, start=1):
        start = _format_srt_timestamp(seg["start"])
        end = _format_srt_timestamp(seg["end"])
        text = seg["text"].strip()
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def _build_ass_header() -> str:
    """ASS 파일 헤더와 스타일 섹션을 반환합니다."""
    font = config.SUBTITLE_FONT
    font_size = config.SUBTITLE_FONT_SIZE
    margin_v = config.SUBTITLE_MARGIN_V

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {config.VIDEO_WIDTH}
PlayResY: {config.VIDEO_HEIGHT}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    return header


def _words_from_segments(segments: list) -> list:
    """
    Whisper 세그먼트에서 단어별 타이밍 데이터를 추출합니다.

    word_timestamps=True로 생성된 결과에서 word-level 데이터를 가져오고,
    없으면 세그먼트 단위로 폴백합니다.

    Returns:
        [{"word": str, "start": float, "end": float}, ...]
    """
    words = []
    for seg in segments:
        seg_words = seg.get("words", [])
        if seg_words:
            for w in seg_words:
                word_text = w.get("word", "").strip()
                if word_text:
                    words.append({
                        "word": word_text,
                        "start": w.get("start", seg["start"]),
                        "end": w.get("end", seg["end"]),
                    })
        else:
            # word_timestamps 데이터가 없으면 세그먼트 전체를 하나의 단위로 처리
            text = seg["text"].strip()
            if text:
                words.append({
                    "word": text,
                    "start": seg["start"],
                    "end": seg["end"],
                })
    return words


def _build_ass_events(words: list) -> str:
    """각 단어별로 ASS Dialogue 라인을 생성합니다."""
    lines = []
    for w in words:
        start = _format_ass_timestamp(w["start"])
        end = _format_ass_timestamp(w["end"])
        text = w["word"]
        lines.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}"
        )
    return "\n".join(lines)


def generate_subtitles(
    audio_path: Path,
    output_dir: Optional[Path] = None,
    model_size: Optional[str] = None,
    language: Optional[str] = None,
) -> Path:
    """
    음성 파일로부터 Whisper word_timestamps를 사용해 ASS 자막을 생성합니다.

    SRT 파일 (fallback용)과 ASS 파일 (단어별 팝업) 두 가지를 생성하며,
    ASS 파일 경로를 반환합니다.

    Args:
        audio_path: 음성 파일 경로 (.mp3, .wav 등)
        output_dir: 출력 디렉토리 (기본: config.TEMP_DIR)
        model_size: Whisper 모델 크기 (tiny/base/small/medium/large)
        language: 언어 코드 (기본: "ko")

    Returns:
        생성된 ASS 파일 경로

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

    srt_path = save_dir / "subtitles.srt"
    ass_path = save_dir / "subtitles.ass"

    logger.info(f"자막 생성 시작 - 모델: {model_size}, 언어: {language}")

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

        logger.info("음성 인식 중 (word_timestamps=True)...")
        result = model.transcribe(
            str(audio_path),
            language=language,
            task=config.WHISPER_TASK,
            word_timestamps=True,
            verbose=False,
        )

        segments = result.get("segments", [])
        if not segments:
            raise RuntimeError("Whisper가 음성을 인식하지 못했습니다.")

        # SRT 파일 저장 (fallback용)
        srt_content = _segments_to_srt(segments)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)
        logger.info(f"SRT 저장 완료: {srt_path} ({len(segments)}개 세그먼트)")

        # 단어별 타이밍 추출
        words = _words_from_segments(segments)
        logger.info(f"단어 추출 완료: {len(words)}개")

        # ASS 파일 생성
        ass_content = _build_ass_header() + _build_ass_events(words)
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)
        logger.info(f"ASS 저장 완료: {ass_path} ({len(words)}개 단어)")

        return ass_path

    except Exception as e:
        # 실패한 파일 정리
        for p in (srt_path, ass_path):
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        raise RuntimeError(f"자막 생성 중 오류: {e}") from e


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format=config.LOG_FORMAT)

    test_audio = config.OUTPUT_DIR / "test_narration.mp3"
    if test_audio.exists():
        ass_path = generate_subtitles(
            audio_path=test_audio,
            output_dir=config.OUTPUT_DIR,
        )
        print(f"생성된 ASS 파일: {ass_path}")
        print(ass_path.read_text(encoding="utf-8")[:500])
    else:
        print(f"테스트 파일 없음: {test_audio}")
