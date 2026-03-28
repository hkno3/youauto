"""
video_composer.py - FFmpeg을 사용한 최종 영상 합성 모듈

배경 영상 + 음성 + ASS 자막 + BGM(선택)을 합성하여
YouTube Shorts용 세로형(9:16, 1080x1920) MP4를 생성합니다.
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
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise RuntimeError(
            "FFmpeg이 설치되지 않았거나 PATH에 없습니다. "
            "https://ffmpeg.org/download.html 에서 설치하세요."
        )


def _get_audio_duration(audio_path: Path) -> float:
    """
    FFprobe로 오디오/영상 파일의 재생 시간을 초 단위로 반환합니다.

    Args:
        audio_path: 오디오 또는 영상 파일 경로

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


def trim_clip(input_path: Path, output_path: Path, duration: float) -> Path:
    """
    영상 클립을 지정한 길이로 트림합니다.

    Args:
        input_path: 입력 영상 경로
        output_path: 출력 영상 경로
        duration: 목표 길이 (초)

    Returns:
        트림된 영상 파일 경로
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-t", str(duration),
        "-c:v", config.VIDEO_CODEC,
        "-pix_fmt", config.PIXEL_FORMAT,
        "-r", str(config.VIDEO_FPS),
        "-an",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"클립 트림 실패: {result.stderr[-300:]}")

    return output_path


def concatenate_clips(clip_paths: list, output_path: Path, audio_duration: float = None) -> Path:
    """
    여러 영상 클립을 이어붙여 하나의 배경 영상을 만듭니다.

    Args:
        clip_paths: 클립 파일 경로 목록
        output_path: 출력 파일 경로
        audio_duration: (미사용, 호환성 유지용) 목표 길이

    Returns:
        이어붙인 영상 파일 경로
    """
    if not clip_paths:
        raise ValueError("이어붙일 클립이 없습니다.")

    # 클립이 1개면 그냥 반환
    if len(clip_paths) == 1:
        return clip_paths[0]

    # FFmpeg concat demuxer용 목록 파일 생성
    list_file = output_path.parent / "concat_list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in clip_paths:
            # Windows 경로 호환성: 역슬래시를 슬래시로 변환
            safe_path = str(p).replace("\\", "/")
            f.write(f"file '{safe_path}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c:v", config.VIDEO_CODEC,
        "-pix_fmt", config.PIXEL_FORMAT,
        "-r", str(config.VIDEO_FPS),
        "-an",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    # concat 목록 파일 삭제 (Windows 파일 잠금 무시)
    try:
        list_file.unlink(missing_ok=True)
    except Exception:
        pass

    if result.returncode != 0:
        raise RuntimeError(f"클립 이어붙이기 실패: {result.stderr[-500:]}")

    return output_path


def mix_bgm(
    video_path: Path,
    bgm_path: Path,
    output_path: Path,
    bgm_volume: float = None,
) -> Path:
    """
    영상의 오디오에 BGM을 낮은 볼륨으로 믹싱합니다.

    Args:
        video_path: 입력 영상 파일 경로 (오디오 포함)
        bgm_path: BGM 파일 경로 (.mp3 등)
        output_path: 출력 파일 경로
        bgm_volume: BGM 볼륨 비율 (기본: config.BGM_VOLUME = 0.15)

    Returns:
        BGM이 믹싱된 영상 파일 경로
    """
    vol = bgm_volume if bgm_volume is not None else config.BGM_VOLUME
    main_weight = 1.0
    bgm_weight = vol

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),        # 입력 1: 메인 영상 (음성 포함)
        "-stream_loop", "-1",
        "-i", str(bgm_path),          # 입력 2: BGM (반복)
        "-filter_complex",
        f"[0:a][1:a]amix=inputs=2:duration=first:weights={main_weight} {bgm_weight}[aout]",
        "-map", "0:v:0",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", config.AUDIO_CODEC,
        "-b:a", config.AUDIO_BITRATE,
        str(output_path),
    ]

    logger.info(f"BGM 믹싱 중 (볼륨: {vol*100:.0f}%)...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"BGM 믹싱 실패: {result.stderr[-500:]}")

    return output_path


def extract_thumbnail(
    video_path: Path,
    output_path: Path,
    timestamp: float = None,
) -> Path:
    """
    영상에서 특정 시점의 프레임을 썸네일로 추출합니다.

    Args:
        video_path: 입력 영상 파일 경로
        output_path: 출력 이미지 파일 경로 (.jpg)
        timestamp: 추출할 시점 (초, 기본: config.THUMBNAIL_TIMESTAMP = 1.0)

    Returns:
        생성된 썸네일 파일 경로
    """
    ts = timestamp if timestamp is not None else config.THUMBNAIL_TIMESTAMP

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(ts),
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",           # JPEG 품질 (2 = 높은 품질)
        str(output_path),
    ]

    logger.info(f"썸네일 추출 중 (t={ts}s)...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        logger.warning(f"썸네일 추출 실패: {result.stderr[-200:]}")
        return output_path  # 실패해도 경로 반환 (파이프라인 중단 방지)

    if output_path.exists():
        logger.info(f"썸네일 저장 완료: {output_path}")
    return output_path


def compose_video(
    background_path: Path,
    audio_path: Path,
    subtitle_path: Path,
    output_filename: str,
    output_dir: Optional[Path] = None,
    bgm_path: Optional[Path] = None,
) -> Path:
    """
    배경 영상 + 음성 + ASS 자막 + 선택적 BGM을 합성하여
    YouTube Shorts 영상(1080x1920)을 생성하고 썸네일을 추출합니다.

    처리 과정:
    1. 배경 영상을 9:16(1080x1920)으로 스케일 + 크롭
    2. 음성 길이에 맞춰 배경 영상 스트림 루프
    3. ASS 자막 오버레이 (단어별 팝업)
    4. 최종 MP4 인코딩
    5. BGM 제공 시 오디오 믹싱
    6. 썸네일 추출

    Args:
        background_path: 배경 영상 파일 경로
        audio_path: 음성 파일 경로 (.mp3)
        subtitle_path: ASS 자막 파일 경로 (.ass) 또는 SRT (.srt)
        output_filename: 출력 파일명 (예: "shorts_output.mp4")
        output_dir: 출력 디렉토리 (기본: config.OUTPUT_DIR)
        bgm_path: BGM 파일 경로 (선택사항, .mp3)

    Returns:
        생성된 최종 영상 파일 경로
    """
    for path, name in [
        (background_path, "배경 영상"),
        (audio_path, "음성"),
        (subtitle_path, "자막"),
    ]:
        if not path.exists():
            raise FileNotFoundError(f"{name} 파일을 찾을 수 없습니다: {path}")

    _check_ffmpeg()

    save_dir = output_dir or config.OUTPUT_DIR
    save_dir.mkdir(parents=True, exist_ok=True)

    # BGM 적용 여부에 따라 중간 파일 또는 최종 파일로 출력
    if bgm_path and bgm_path.exists():
        compose_output = save_dir / f"_tmp_{output_filename}"
    else:
        compose_output = save_dir / output_filename

    # 음성 재생 시간 확인 및 제한
    audio_duration = _get_audio_duration(audio_path)
    audio_duration = min(audio_duration, config.VIDEO_MAX_DURATION)
    logger.info(f"음성 재생 시간: {audio_duration:.1f}초")

    # ASS 파일 경로 처리
    # Linux/Mac: 그대로, Windows: 콜론 이스케이프
    subtitle_str = str(subtitle_path).replace("\\", "/")
    if os.name == "nt":
        # Windows에서는 드라이브 문자의 콜론을 이스케이프
        subtitle_str = subtitle_str.replace(":", "\\:")

    # 자막 필터 선택: ASS 포맷이면 ass= 필터, SRT이면 subtitles= 필터
    suffix = subtitle_path.suffix.lower()
    if suffix == ".ass":
        subtitle_filter = f"ass='{subtitle_str}'"
    else:
        subtitle_style = (
            f"FontName={config.SUBTITLE_FONT},"
            f"FontSize={config.SUBTITLE_FONT_SIZE},"
            f"PrimaryColour=&H00FFFFFF,"
            f"OutlineColour=&H00000000,"
            f"Outline={config.SUBTITLE_OUTLINE_WIDTH},"
            f"Shadow=1,"
            f"Alignment={config.SUBTITLE_ALIGNMENT},"
            f"MarginV={config.SUBTITLE_MARGIN_V}"
        )
        subtitle_filter = f"subtitles='{subtitle_str}':force_style='{subtitle_style}'"

    # FFmpeg 필터: 스케일 → 크롭 → 자막
    vf_filter = (
        f"scale={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT}"
        f":force_original_aspect_ratio=increase,"
        f"crop={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT},"
        f"{subtitle_filter}"
    )

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",           # 배경 영상 무한 루프 (음성 길이에 맞춤)
        "-i", str(background_path),     # 입력 0: 배경 영상
        "-i", str(audio_path),          # 입력 1: 음성
        "-t", str(audio_duration),      # 전체 영상 길이 = 음성 길이
        "-vf", vf_filter,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", config.VIDEO_CODEC,
        "-c:a", config.AUDIO_CODEC,
        "-b:v", config.VIDEO_BITRATE,
        "-b:a", config.AUDIO_BITRATE,
        "-r", str(config.VIDEO_FPS),
        "-pix_fmt", config.PIXEL_FORMAT,
        "-movflags", "+faststart",
        str(compose_output),
    ]

    logger.info("FFmpeg 영상 합성 시작...")
    logger.debug(f"FFmpeg 명령어: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error(f"FFmpeg 오류:\n{result.stderr}")
            raise RuntimeError(f"FFmpeg 실행 실패 (코드 {result.returncode})")
    except subprocess.TimeoutExpired:
        raise RuntimeError("FFmpeg 실행 시간 초과 (5분)")

    if not compose_output.exists() or compose_output.stat().st_size == 0:
        raise RuntimeError(f"출력 파일이 생성되지 않았습니다: {compose_output}")

    # BGM 믹싱 (제공된 경우)
    final_output = save_dir / output_filename
    if bgm_path and bgm_path.exists():
        try:
            mix_bgm(
                video_path=compose_output,
                bgm_path=bgm_path,
                output_path=final_output,
                bgm_volume=config.BGM_VOLUME,
            )
            # 중간 파일 삭제
            try:
                compose_output.unlink(missing_ok=True)
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"BGM 믹싱 실패 (BGM 없이 진행): {e}")
            # BGM 없이 compose 결과물을 최종 파일로 사용
            try:
                compose_output.rename(final_output)
            except Exception:
                final_output = compose_output
    else:
        final_output = compose_output  # bgm 없을 때 이미 final 경로로 저장됨

    file_size_mb = final_output.stat().st_size / (1024 * 1024)
    logger.info(
        f"영상 합성 완료 - {file_size_mb:.1f}MB, "
        f"{audio_duration:.1f}초: {final_output}"
    )

    # 썸네일 추출
    thumbnail_path = save_dir / (Path(output_filename).stem + "_thumbnail.jpg")
    try:
        extract_thumbnail(final_output, thumbnail_path)
    except Exception as e:
        logger.warning(f"썸네일 추출 실패 (무시): {e}")

    return final_output


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format=config.LOG_FORMAT)
    print("video_composer 모듈 로드 완료.")
