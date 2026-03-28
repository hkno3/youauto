"""
video_composer.py - FFmpeg을 사용한 최종 영상 합성 모듈

배경 영상 + 음성 + 자막을 합성하여 YouTube Shorts용 세로형(9:16) MP4를 생성합니다.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = logging.getLogger(__name__)


def _check_ffmpeg() -> None:
    """FFmpeg 설치 여부를 확인합니다."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise RuntimeError(
            "FFmpeg이 설치되지 않았거나 PATH에 없습니다. "
            "https://ffmpeg.org/download.html 에서 설치하세요."
        )


def _get_audio_duration(audio_path: Path) -> float:
    """
    FFprobe로 오디오 파일의 재생 시간을 초 단위로 반환합니다.

    Args:
        audio_path: 오디오 파일 경로

    Returns:
        재생 시간 (초, float)
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def concatenate_clips(clip_paths: list, output_path: Path, audio_duration: float) -> Path:
    """
    여러 영상 클립을 이어붙여 하나의 배경 영상을 만듭니다.

    Args:
        clip_paths: 클립 파일 경로 목록
        output_path: 출력 파일 경로
        audio_duration: 목표 길이 (음성 길이에 맞춤)

    Returns:
        이어붙인 영상 파일 경로
    """
    # 클립이 1개면 그냥 반환
    if len(clip_paths) == 1:
        return clip_paths[0]

    # FFmpeg concat demuxer용 목록 파일 생성
    list_file = output_path.parent / "concat_list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in clip_paths:
            f.write(f"file '{str(p).replace(chr(92), '/')}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c:v", config.VIDEO_CODEC,
        "-pix_fmt", config.PIXEL_FORMAT,
        "-r", str(config.VIDEO_FPS),
        "-an",  # 오디오 없음 (나중에 합성)
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    try:
        list_file.unlink(missing_ok=True)
    except Exception:
        pass  # Windows 파일 잠금 무시

    if result.returncode != 0:
        raise RuntimeError(f"클립 이어붙이기 실패: {result.stderr[-500:]}")

    return output_path


def compose_video(
    background_path: Path,
    audio_path: Path,
    subtitle_path: Path,
    output_filename: str,
    output_dir: Optional[Path] = None,
) -> Path:
    """
    배경 영상 + 음성 + 자막을 합성하여 YouTube Shorts 영상을 생성합니다.

    처리 과정:
    1. 배경 영상을 9:16(1080x1920)으로 크롭/스케일
    2. 음성 길이에 맞춰 영상 길이 조정 (루프 또는 트림)
    3. 자막 스타일 적용 (흰색 텍스트 + 검은 윤곽선)
    4. 최종 MP4 인코딩

    Args:
        background_path: 배경 영상 파일 경로
        audio_path: 음성 파일 경로 (.mp3)
        subtitle_path: 자막 파일 경로 (.srt)
        output_filename: 출력 파일명 (예: "shorts_output.mp4")
        output_dir: 출력 디렉토리 (기본: config.OUTPUT_DIR)

    Returns:
        생성된 최종 영상 파일 경로

    Raises:
        FileNotFoundError: 입력 파일이 없을 경우
        RuntimeError: FFmpeg 실행 실패 시
    """
    for path, name in [(background_path, "배경 영상"), (audio_path, "음성"), (subtitle_path, "자막")]:
        if not path.exists():
            raise FileNotFoundError(f"{name} 파일을 찾을 수 없습니다: {path}")

    _check_ffmpeg()

    save_dir = output_dir or config.OUTPUT_DIR
    save_dir.mkdir(parents=True, exist_ok=True)
    output_path = save_dir / output_filename

    # 음성 재생 시간 확인
    audio_duration = _get_audio_duration(audio_path)
    audio_duration = min(audio_duration, config.VIDEO_MAX_DURATION)
    logger.info(f"음성 재생 시간: {audio_duration:.1f}초")

    # 자막 경로 (FFmpeg는 경로에 콜론이 있으면 이스케이프 필요)
    srt_path_str = str(subtitle_path).replace("\\", "/").replace(":", "\\:")

    # 자막 스타일 설정 (ASS 스타일)
    subtitle_style = (
        f"FontName={config.SUBTITLE_FONT},"
        f"FontSize={config.SUBTITLE_FONT_SIZE},"
        f"PrimaryColour=&H00FFFFFF,"   # 흰색
        f"OutlineColour=&H00000000,"   # 검은 테두리
        f"Outline={config.SUBTITLE_OUTLINE_WIDTH},"
        f"Shadow=1,"
        f"Alignment={config.SUBTITLE_ALIGNMENT},"
        f"MarginV={config.SUBTITLE_MARGIN_V},"
        f"MarginL={config.SUBTITLE_MARGIN_H},"
        f"MarginR={config.SUBTITLE_MARGIN_H}"
    )

    # FFmpeg 필터 그래프:
    # 1. 배경 영상을 9:16으로 스케일 + 크롭
    # 2. 자막 오버레이
    vf_filter = (
        f"scale={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT},"
        f"subtitles='{srt_path_str}':force_style='{subtitle_style}'"
    )

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",          # 배경 영상 반복 (음성보다 짧을 경우)
        "-i", str(background_path),    # 입력 1: 배경 영상
        "-i", str(audio_path),         # 입력 2: 음성
        "-t", str(audio_duration),     # 음성 길이로 전체 영상 길이 제한
        "-vf", vf_filter,
        "-map", "0:v:0",               # 영상 트랙: 첫 번째 입력의 비디오
        "-map", "1:a:0",               # 오디오 트랙: 두 번째 입력의 오디오
        "-c:v", config.VIDEO_CODEC,
        "-c:a", config.AUDIO_CODEC,
        "-b:v", config.VIDEO_BITRATE,
        "-b:a", config.AUDIO_BITRATE,
        "-r", str(config.VIDEO_FPS),
        "-pix_fmt", config.PIXEL_FORMAT,
        "-movflags", "+faststart",     # 웹 스트리밍 최적화
        str(output_path),
    ]

    logger.info("FFmpeg 영상 합성 시작...")
    logger.debug(f"FFmpeg 명령어: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5분 타임아웃
        )
        if result.returncode != 0:
            logger.error(f"FFmpeg 오류:\n{result.stderr}")
            raise RuntimeError(f"FFmpeg 실행 실패 (코드 {result.returncode})")
    except subprocess.TimeoutExpired:
        raise RuntimeError("FFmpeg 실행 시간 초과 (5분)")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"출력 파일이 생성되지 않았습니다: {output_path}")

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info(
        f"영상 합성 완료 - 크기: {file_size_mb:.1f}MB, "
        f"길이: {audio_duration:.1f}초, 경로: {output_path}"
    )
    return output_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format=config.LOG_FORMAT)
    print("video_composer 모듈 로드 완료. main.py를 통해 실행하세요.")
