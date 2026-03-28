"""
main.py - YouTube Shorts 자동화 파이프라인 메인 실행 파일

사용법:
    python main.py --topic "건강한 아침 루틴"
    python main.py --topic "파이썬 꿀팁 5가지" --output "my_shorts.mp4"
"""

import argparse
import logging
import shutil
import sys
import time
from pathlib import Path

import config
from src.script_generator import generate_script
from src.tts_generator import generate_tts
from src.video_downloader import download_background_video
from src.subtitle_generator import generate_subtitles
from src.video_composer import compose_video


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format=config.LOG_FORMAT,
        datefmt=config.LOG_DATE_FORMAT,
    )


def validate_env() -> None:
    """필수 환경변수 확인"""
    missing = []
    if not config.ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not config.PEXELS_API_KEY:
        missing.append("PEXELS_API_KEY")
    if missing:
        print(f"[오류] .env 파일에 다음 API 키를 설정하세요: {', '.join(missing)}")
        print("  .env.example 파일을 복사하여 .env 파일을 만들고 키를 입력하세요.")
        sys.exit(1)


def cleanup_temp(temp_dir: Path) -> None:
    """임시 파일 정리"""
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
        logging.getLogger(__name__).info("임시 파일 정리 완료")


def run_pipeline(topic: str, output_filename: str, keep_temp: bool = False) -> Path:
    """
    전체 YouTube Shorts 생성 파이프라인을 실행합니다.

    Args:
        topic: 영상 주제 (한국어)
        output_filename: 최종 출력 파일명
        keep_temp: True면 임시 파일 유지

    Returns:
        생성된 최종 영상 파일 경로
    """
    logger = logging.getLogger(__name__)
    start_time = time.time()

    print(f"\n{'='*55}")
    print(f"  YouTube Shorts 자동화 시작")
    print(f"  주제: {topic}")
    print(f"{'='*55}\n")

    # ── STEP 1: 대본 생성 ─────────────────────────────────────
    print("[1/5] Claude AI로 대본 생성 중...")
    script_result = generate_script(topic)
    print(f"  ✓ 제목: {script_result.title}")
    print(f"  ✓ 예상 시간: {script_result.estimated_duration}초")
    print(f"  ✓ 검색 키워드: {script_result.pexels_keywords}\n")

    # ── STEP 2: 음성 합성 ─────────────────────────────────────
    print("[2/5] Edge TTS로 음성 생성 중...")
    audio_path = generate_tts(
        text=script_result.script,
        output_filename="narration.mp3",
    )
    print(f"  ✓ 음성 파일: {audio_path.name}\n")

    # ── STEP 3: 배경 영상 다운로드 ────────────────────────────
    print("[3/5] Pexels에서 배경 영상 다운로드 중...")
    background_path = download_background_video(
        keywords=script_result.pexels_keywords,
        output_filename="background.mp4",
        target_duration=script_result.estimated_duration,
    )
    print(f"  ✓ 배경 영상: {background_path.name}\n")

    # ── STEP 4: 자막 생성 ─────────────────────────────────────
    print("[4/5] Whisper로 자막 생성 중...")
    subtitle_path = generate_subtitles(
        audio_path=audio_path,
        output_filename="subtitles.srt",
    )
    print(f"  ✓ 자막 파일: {subtitle_path.name}\n")

    # ── STEP 5: 영상 합성 ─────────────────────────────────────
    print("[5/5] FFmpeg으로 최종 영상 합성 중...")
    final_video = compose_video(
        background_path=background_path,
        audio_path=audio_path,
        subtitle_path=subtitle_path,
        output_filename=output_filename,
    )

    # 임시 파일 정리
    if not keep_temp:
        cleanup_temp(config.TEMP_DIR)

    elapsed = time.time() - start_time
    print(f"\n{'='*55}")
    print(f"  완성! 총 소요 시간: {elapsed:.1f}초")
    print(f"  출력 파일: {final_video}")
    print(f"{'='*55}\n")

    return final_video


def main() -> None:
    setup_logging()
    validate_env()

    parser = argparse.ArgumentParser(
        description="YouTube Shorts 영상 자동 생성기",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python main.py --topic "건강한 아침 루틴"
  python main.py --topic "파이썬 꿀팁 5가지" --output "python_tips.mp4"
  python main.py --topic "주식 투자 초보 가이드" --keep-temp
        """,
    )
    parser.add_argument(
        "--topic", "-t",
        required=True,
        help="영상 주제 (한국어로 입력)",
    )
    parser.add_argument(
        "--output", "-o",
        default="shorts_output.mp4",
        help="출력 파일명 (기본값: shorts_output.mp4)",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="임시 파일(음성, 자막 등) 유지",
    )

    args = parser.parse_args()

    try:
        run_pipeline(
            topic=args.topic,
            output_filename=args.output,
            keep_temp=args.keep_temp,
        )
    except KeyboardInterrupt:
        print("\n\n사용자에 의해 중단되었습니다.")
        sys.exit(0)
    except Exception as e:
        logging.getLogger(__name__).error(f"파이프라인 실행 중 오류: {e}", exc_info=True)
        print(f"\n[오류] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
