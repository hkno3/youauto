"""
video_downloader.py - Pexels API를 사용한 배경 영상 다운로드 모듈

주어진 키워드로 Pexels에서 배경 영상을 검색하고 다운로드합니다.
YouTube Shorts(세로형 9:16) 형식에 맞는 영상을 우선 선택합니다.
"""

import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = logging.getLogger(__name__)


@dataclass
class VideoFile:
    """Pexels 비디오 파일 정보를 담는 데이터 클래스"""
    video_id: int           # Pexels 영상 ID
    url: str                # 다운로드 URL
    width: int              # 영상 너비
    height: int             # 영상 높이
    quality: str            # 화질 (hd, sd, uhd)
    duration: int           # 영상 길이 (초)
    keyword: str            # 검색에 사용된 키워드


def _get_headers(api_key: str) -> dict:
    """Pexels API 요청 헤더를 반환합니다."""
    return {
        "Authorization": api_key,
        "User-Agent": "YouAutoShorts/1.0",
    }


def _select_best_video_file(video_files: list[dict], preferred_quality: str) -> Optional[dict]:
    """
    영상 파일 목록에서 최적의 파일을 선택합니다.

    선택 우선순위:
    1. 선호 화질(preferred_quality)과 일치하는 파일
    2. 세로형(portrait) 비율에 가까운 파일
    3. 너비가 config.PEXELS_VIDEO_MIN_WIDTH 이상인 파일

    Args:
        video_files: Pexels API에서 반환된 video_files 목록
        preferred_quality: 선호 화질 ('hd', 'sd', 'uhd')

    Returns:
        선택된 파일 딕셔너리, 없으면 None
    """
    if not video_files:
        return None

    # 화질 우선순위 정의
    quality_order = {"uhd": 3, "hd": 2, "sd": 1}
    preferred_rank = quality_order.get(preferred_quality, 2)

    # 최소 너비를 만족하는 파일들만 필터링
    valid_files = [
        f for f in video_files
        if f.get("width", 0) >= config.PEXELS_VIDEO_MIN_WIDTH
    ]

    if not valid_files:
        # 최소 너비 조건 없이 재시도
        valid_files = video_files

    # 선호 화질과 일치하는 파일 먼저 시도
    preferred_files = [f for f in valid_files if f.get("quality") == preferred_quality]
    if preferred_files:
        # 세로형에 가까운 파일 우선 선택 (height > width)
        portrait_files = [f for f in preferred_files if f.get("height", 0) > f.get("width", 0)]
        if portrait_files:
            return portrait_files[0]
        return preferred_files[0]

    # 화질 기준으로 내림차순 정렬하여 최선의 파일 반환
    sorted_files = sorted(
        valid_files,
        key=lambda f: quality_order.get(f.get("quality", "sd"), 1),
        reverse=True,
    )
    return sorted_files[0] if sorted_files else None


def search_videos(
    keyword: str,
    api_key: str,
    per_page: int = None,
    orientation: str = "portrait",
) -> list[dict]:
    """
    Pexels API로 키워드 기반 영상을 검색합니다.

    Args:
        keyword: 검색 키워드 (영어 권장)
        api_key: Pexels API 키
        per_page: 페이지당 결과 수 (기본: config.PEXELS_PER_PAGE)
        orientation: 영상 방향 ('portrait', 'landscape', 'square')

    Returns:
        Pexels 영상 데이터 딕셔너리 목록

    Raises:
        requests.HTTPError: API 요청 실패 시
    """
    per_page = per_page or config.PEXELS_PER_PAGE

    params = {
        "query": keyword,
        "per_page": per_page,
        "orientation": orientation,
    }

    logger.debug(f"Pexels 검색 요청 - 키워드: '{keyword}', 방향: {orientation}")

    response = requests.get(
        config.PEXELS_API_URL,
        headers=_get_headers(api_key),
        params=params,
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()
    videos = data.get("videos", [])

    logger.debug(f"Pexels 검색 결과: {len(videos)}개 영상")
    return videos


def _filter_videos_by_duration(videos: list[dict], min_dur: int, max_dur: int) -> list[dict]:
    """
    영상 길이 조건에 맞는 영상들을 필터링합니다.

    Args:
        videos: 영상 딕셔너리 목록
        min_dur: 최소 길이 (초)
        max_dur: 최대 길이 (초)

    Returns:
        조건에 맞는 영상 목록
    """
    return [
        v for v in videos
        if min_dur <= v.get("duration", 0) <= max_dur
    ]


def download_video(
    video_info: VideoFile,
    output_path: Path,
    chunk_size: int = 1024 * 1024,  # 1MB 청크
) -> Path:
    """
    단일 영상 파일을 다운로드합니다.

    Args:
        video_info: 다운로드할 영상 정보 (VideoFile 인스턴스)
        output_path: 저장할 파일 경로
        chunk_size: 다운로드 청크 크기 (bytes)

    Returns:
        다운로드된 파일 경로

    Raises:
        RuntimeError: 다운로드 실패 시
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        f"영상 다운로드 시작 - ID: {video_info.video_id}, "
        f"화질: {video_info.quality}, "
        f"크기: {video_info.width}x{video_info.height}"
    )

    try:
        response = requests.get(video_info.url, stream=True, timeout=60)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        logger.debug(f"다운로드 진행률: {progress:.1f}%")

    except Exception as e:
        # 실패한 파일 정리
        if output_path.exists():
            output_path.unlink()
        raise RuntimeError(f"영상 다운로드 실패: {e}") from e

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info(f"영상 다운로드 완료 - 크기: {file_size_mb:.1f}MB, 경로: {output_path}")

    return output_path


def download_background_video(
    keywords: list[str],
    output_filename: str,
    api_key: Optional[str] = None,
    output_dir: Optional[Path] = None,
    target_duration: Optional[int] = None,
) -> Path:
    """
    키워드 목록으로 Pexels에서 배경 영상을 검색하고 다운로드합니다.

    여러 키워드를 순서대로 시도하며, 적합한 영상을 찾으면 다운로드합니다.

    Args:
        keywords: 검색 키워드 목록 (영어, 우선순위 순)
        output_filename: 저장할 파일명 (예: "background.mp4")
        api_key: Pexels API 키 (미제공 시 config에서 읽음)
        output_dir: 저장 디렉토리 (기본: config.TEMP_DIR)
        target_duration: 목표 영상 길이 (초), 이 이상인 영상 우선 선택

    Returns:
        다운로드된 영상 파일 경로

    Raises:
        ValueError: API 키가 없거나 적합한 영상을 찾지 못한 경우
    """
    key = api_key or config.PEXELS_API_KEY
    if not key:
        raise ValueError(
            "PEXELS_API_KEY가 설정되지 않았습니다. "
            ".env 파일 또는 환경변수를 확인하세요."
        )

    save_dir = output_dir or config.TEMP_DIR
    save_dir.mkdir(parents=True, exist_ok=True)
    output_path = save_dir / output_filename

    target_dur = target_duration or config.VIDEO_MAX_DURATION
    min_dur = config.PEXELS_VIDEO_MIN_DURATION
    max_dur = config.PEXELS_VIDEO_MAX_DURATION

    logger.info(f"배경 영상 검색 시작 - 키워드: {keywords}")

    # 각 키워드로 순서대로 검색 시도
    for i, keyword in enumerate(keywords):
        logger.info(f"키워드 [{i+1}/{len(keywords)}] '{keyword}' 검색 중...")

        try:
            # 세로형 우선 검색
            videos = search_videos(keyword, key, orientation="portrait")

            # 길이 필터링
            filtered = _filter_videos_by_duration(videos, min_dur, max_dur)

            if not filtered:
                # 가로형도 포함하여 재검색
                logger.debug(f"세로형 영상 없음, 가로형 포함 재검색: '{keyword}'")
                videos = search_videos(keyword, key, orientation="landscape")
                filtered = _filter_videos_by_duration(videos, min_dur, max_dur)

            if not filtered:
                logger.warning(f"'{keyword}': 조건에 맞는 영상 없음, 다음 키워드 시도")
                continue

            # 목표 길이 이상인 영상 우선 선택
            long_enough = [v for v in filtered if v.get("duration", 0) >= target_dur]
            candidates = long_enough if long_enough else filtered

            # 무작위로 하나 선택 (다양성 확보)
            selected_video = random.choice(candidates[:min(5, len(candidates))])

            # 최적 파일 선택
            video_files = selected_video.get("video_files", [])
            best_file = _select_best_video_file(video_files, config.PEXELS_PREFERRED_QUALITY)

            if not best_file:
                logger.warning(f"'{keyword}': 적합한 파일 형식 없음")
                continue

            video_info = VideoFile(
                video_id=selected_video.get("id", 0),
                url=best_file.get("link", ""),
                width=best_file.get("width", 0),
                height=best_file.get("height", 0),
                quality=best_file.get("quality", "unknown"),
                duration=selected_video.get("duration", 0),
                keyword=keyword,
            )

            if not video_info.url:
                logger.warning(f"'{keyword}': 다운로드 URL 없음")
                continue

            # 다운로드 실행
            result_path = download_video(video_info, output_path)
            logger.info(f"배경 영상 다운로드 성공 - 키워드: '{keyword}'")
            return result_path

        except requests.HTTPError as e:
            logger.error(f"Pexels API 오류 ('{keyword}'): {e}")
            if e.response is not None and e.response.status_code == 429:
                # Rate limit - 잠시 대기
                logger.warning("API 속도 제한 도달, 5초 대기 후 재시도...")
                time.sleep(5)
            continue

        except Exception as e:
            logger.error(f"'{keyword}' 처리 중 예외 발생: {e}")
            continue

    raise ValueError(
        f"모든 키워드로 적합한 배경 영상을 찾지 못했습니다. "
        f"시도한 키워드: {keywords}"
    )


if __name__ == "__main__":
    # 단독 실행 테스트
    logging.basicConfig(level=logging.DEBUG, format=config.LOG_FORMAT)

    test_keywords = ["morning routine", "healthy breakfast", "lifestyle"]
    output_path = download_background_video(
        keywords=test_keywords,
        output_filename="test_background.mp4",
        output_dir=config.OUTPUT_DIR,
        target_duration=30,
    )
    print(f"다운로드된 파일: {output_path}")
