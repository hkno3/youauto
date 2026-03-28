"""
video_downloader.py - Pexels API를 사용한 배경 영상 다운로드 모듈

주어진 키워드로 Pexels에서 배경 영상을 검색하고 다운로드합니다.
문장별 키워드를 사용해 각 문장마다 다른 배경 클립을 다운로드합니다.
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
    """Pexels 비디오 파일 정보를 담는 데이터 클래스."""
    video_id: int
    url: str
    width: int
    height: int
    quality: str
    duration: int
    keyword: str


def _get_headers(api_key: str) -> dict:
    """Pexels API 요청 헤더를 반환합니다."""
    return {
        "Authorization": api_key,
        "User-Agent": "YouAutoShorts/1.0",
    }


def _select_best_video_file(video_files: list, preferred_quality: str) -> Optional[dict]:
    """
    영상 파일 목록에서 최적의 파일을 선택합니다.

    선택 우선순위:
    1. 선호 화질과 일치하는 파일
    2. 세로형(portrait) 비율에 가까운 파일
    3. 너비가 config.PEXELS_VIDEO_MIN_WIDTH 이상인 파일
    """
    if not video_files:
        return None

    quality_order = {"uhd": 3, "hd": 2, "sd": 1}

    valid_files = [
        f for f in video_files
        if f.get("width", 0) >= config.PEXELS_VIDEO_MIN_WIDTH
    ]
    if not valid_files:
        valid_files = video_files

    preferred_files = [f for f in valid_files if f.get("quality") == preferred_quality]
    if preferred_files:
        portrait_files = [
            f for f in preferred_files
            if f.get("height", 0) > f.get("width", 0)
        ]
        return portrait_files[0] if portrait_files else preferred_files[0]

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
) -> list:
    """
    Pexels API로 키워드 기반 영상을 검색합니다.

    Args:
        keyword: 검색 키워드 (영어 권장)
        api_key: Pexels API 키
        per_page: 페이지당 결과 수
        orientation: 영상 방향 ('portrait', 'landscape', 'square')

    Returns:
        Pexels 영상 데이터 딕셔너리 목록
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


def _filter_videos_by_duration(videos: list, min_dur: int, max_dur: int) -> list:
    """영상 길이 조건에 맞는 영상들을 필터링합니다."""
    return [v for v in videos if min_dur <= v.get("duration", 0) <= max_dur]


def download_video(video_info: VideoFile, output_path: Path, chunk_size: int = 1024 * 1024) -> Path:
    """
    단일 영상 파일을 다운로드합니다.

    Args:
        video_info: 다운로드할 영상 정보
        output_path: 저장할 파일 경로
        chunk_size: 다운로드 청크 크기 (bytes)

    Returns:
        다운로드된 파일 경로
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

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)

    except Exception as e:
        if output_path.exists():
            try:
                output_path.unlink()
            except Exception:
                pass
        raise RuntimeError(f"영상 다운로드 실패: {e}") from e

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info(f"영상 다운로드 완료 - {file_size_mb:.1f}MB: {output_path}")
    return output_path


def download_background_video(
    keywords: list,
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
        output_filename: 저장할 파일명
        api_key: Pexels API 키
        output_dir: 저장 디렉토리
        target_duration: 목표 영상 길이 (초)

    Returns:
        다운로드된 영상 파일 경로
    """
    key = api_key or config.PEXELS_API_KEY
    if not key:
        raise ValueError("PEXELS_API_KEY가 설정되지 않았습니다.")

    save_dir = output_dir or config.TEMP_DIR
    save_dir.mkdir(parents=True, exist_ok=True)
    output_path = save_dir / output_filename

    target_dur = target_duration or config.VIDEO_MAX_DURATION
    min_dur = config.PEXELS_VIDEO_MIN_DURATION
    max_dur = config.PEXELS_VIDEO_MAX_DURATION

    logger.info(f"배경 영상 검색 - 키워드: {keywords}")

    for i, keyword in enumerate(keywords):
        logger.info(f"키워드 [{i+1}/{len(keywords)}] '{keyword}' 검색 중...")

        try:
            # 세로형 우선 검색
            videos = search_videos(keyword, key, orientation="portrait")
            filtered = _filter_videos_by_duration(videos, min_dur, max_dur)

            if not filtered:
                # 가로형 포함 재검색
                videos = search_videos(keyword, key, orientation="landscape")
                filtered = _filter_videos_by_duration(videos, min_dur, max_dur)

            if not filtered:
                # 필터 없이 전체 검색
                filtered = _filter_videos_by_duration(videos, 3, max_dur)

            if not filtered:
                logger.warning(f"'{keyword}': 조건에 맞는 영상 없음")
                continue

            long_enough = [v for v in filtered if v.get("duration", 0) >= target_dur]
            candidates = long_enough if long_enough else filtered

            selected_video = random.choice(candidates[:min(5, len(candidates))])
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

            return download_video(video_info, output_path)

        except requests.HTTPError as e:
            logger.error(f"Pexels API 오류 ('{keyword}'): {e}")
            if e.response is not None and e.response.status_code == 429:
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


def download_multiple_videos(
    keywords: list,
    api_key: Optional[str] = None,
    output_dir: Optional[Path] = None,
    clip_duration: int = 10,
) -> list:
    """
    키워드마다 영상 클립 1개씩 다운로드합니다.

    Args:
        keywords: 검색 키워드 목록 (키워드당 클립 1개)
        api_key: Pexels API 키
        output_dir: 저장 디렉토리
        clip_duration: 각 클립 목표 길이 (초)

    Returns:
        다운로드된 파일 경로 목록
    """
    key = api_key or config.PEXELS_API_KEY
    save_dir = output_dir or config.TEMP_DIR
    save_dir.mkdir(parents=True, exist_ok=True)

    downloaded = []
    for i, keyword in enumerate(keywords):
        output_filename = f"clip_{i:02d}.mp4"
        try:
            path = download_background_video(
                keywords=[keyword],
                output_filename=output_filename,
                api_key=key,
                output_dir=save_dir,
                target_duration=clip_duration,
            )
            downloaded.append(path)
            logger.info(f"클립 {i+1}/{len(keywords)} 완료: {keyword}")
        except Exception as e:
            logger.warning(f"클립 {i+1} 다운로드 실패 ({keyword}): {e}")

    if not downloaded:
        raise ValueError("다운로드된 클립이 없습니다.")

    return downloaded


def download_clips_per_sentence(
    sentences: list,
    api_key: Optional[str] = None,
    output_dir: Optional[Path] = None,
    clip_duration: int = 8,
) -> list:
    """
    sentences 목록의 각 문장마다 sentence["keyword"]로 클립을 1개씩 다운로드합니다.

    다운로드 실패 시 sentence["text"]를 영문 번역하지 않고 일반 영어 단어로 폴백합니다.

    Args:
        sentences: [{"text": "...", "keyword": "..."}, ...] 형식의 문장 목록
        api_key: Pexels API 키
        output_dir: 저장 디렉토리
        clip_duration: 각 클립 목표 길이 (초)

    Returns:
        다운로드된 파일 경로 목록 (실패한 항목은 제외)
    """
    key = api_key or config.PEXELS_API_KEY
    save_dir = output_dir or config.TEMP_DIR
    save_dir.mkdir(parents=True, exist_ok=True)

    fallback_keywords = ["lifestyle", "nature", "people", "city", "health", "motivation"]
    downloaded = []

    for i, sentence in enumerate(sentences):
        keyword = sentence.get("keyword", "").strip()
        text = sentence.get("text", "").strip()
        output_filename = f"clip_{i:02d}.mp4"

        if not keyword:
            keyword = fallback_keywords[i % len(fallback_keywords)]
            logger.warning(f"문장 {i+1}: keyword 없음, 폴백 사용: '{keyword}'")

        # 1차 시도: sentence keyword
        # 2차 시도: 단어 간소화 (키워드의 첫 단어만)
        # 3차 시도: fallback
        attempts = [keyword]
        if " " in keyword:
            attempts.append(keyword.split()[0])
        attempts.append(fallback_keywords[i % len(fallback_keywords)])

        success = False
        for attempt_keyword in attempts:
            try:
                path = download_background_video(
                    keywords=[attempt_keyword],
                    output_filename=output_filename,
                    api_key=key,
                    output_dir=save_dir,
                    target_duration=clip_duration,
                )
                downloaded.append(path)
                logger.info(
                    f"문장 {i+1}/{len(sentences)} 클립 완료: "
                    f"'{text[:20]}...' → '{attempt_keyword}'"
                )
                success = True
                break
            except Exception as e:
                logger.warning(
                    f"문장 {i+1} 키워드 '{attempt_keyword}' 실패: {e}"
                )
                continue

        if not success:
            logger.error(f"문장 {i+1} 클립 모든 시도 실패, 건너뜀")

    if not downloaded:
        raise ValueError("다운로드된 클립이 없습니다.")

    return downloaded


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format=config.LOG_FORMAT)

    test_sentences = [
        {"text": "물 한 잔으로 시작하세요", "keyword": "drinking water morning"},
        {"text": "짧은 스트레칭으로 몸을 깨우세요", "keyword": "morning stretching yoga"},
        {"text": "건강한 아침 식사를 준비하세요", "keyword": "healthy breakfast food"},
    ]
    clips = download_clips_per_sentence(
        sentences=test_sentences,
        output_dir=config.OUTPUT_DIR / "test_clips",
        clip_duration=10,
    )
    print(f"다운로드된 클립: {len(clips)}개")
    for p in clips:
        print(f"  {p}")
