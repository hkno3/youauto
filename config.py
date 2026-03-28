"""
config.py - 프로젝트 전역 설정 파일
YouTube Shorts 자동화 파이프라인의 모든 설정값을 중앙 관리합니다.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# ─── 기본 경로 설정 ───────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = OUTPUT_DIR / "temp"

# 출력 디렉토리 자동 생성
OUTPUT_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

# ─── API 키 ───────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
PEXELS_API_KEY: str = os.getenv("PEXELS_API_KEY", "")

# ─── Gemini 설정 ──────────────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-2.5-flash-preview-04-17"
GEMINI_MAX_TOKENS = 2048
GEMINI_TEMPERATURE = 1.0

# ─── 영상 형식 설정 (YouTube Shorts: 세로형 9:16) ─────────────────────────────
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 30
VIDEO_MAX_DURATION = 58      # 초 (60초 제한에 여유분 2초 확보)
VIDEO_BITRATE = "4M"         # 영상 비트레이트
AUDIO_BITRATE = "192k"       # 오디오 비트레이트
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
PIXEL_FORMAT = "yuv420p"

# ─── TTS 설정 (Edge TTS - 한국어) ─────────────────────────────────────────────
TTS_VOICE = "ko-KR-SunHiNeural"   # 한국어 여성 음성
TTS_RATE = "+0%"                   # 말하기 속도 (기본값)
TTS_VOLUME = "+0%"                 # 볼륨 (기본값)
TTS_PITCH = "+0Hz"                 # 음높이 (기본값)

# ─── Pexels API 설정 ─────────────────────────────────────────────────────────
PEXELS_API_URL = "https://api.pexels.com/videos/search"
PEXELS_VIDEO_MIN_DURATION = 10     # 최소 영상 길이 (초)
PEXELS_VIDEO_MAX_DURATION = 120    # 최대 영상 길이 (초)
PEXELS_VIDEO_MIN_WIDTH = 1080      # 최소 영상 너비
PEXELS_PER_PAGE = 15               # 검색 결과 수
PEXELS_PREFERRED_QUALITY = "hd"   # 선호 화질 (hd, sd, uhd)

# ─── Whisper 설정 ─────────────────────────────────────────────────────────────
WHISPER_MODEL = "base"             # tiny, base, small, medium, large
WHISPER_LANGUAGE = "ko"           # 한국어
WHISPER_TASK = "transcribe"       # transcribe(원본 언어) 또는 translate(영어 번역)

# ─── 자막 스타일 설정 ─────────────────────────────────────────────────────────
SUBTITLE_FONT = "NanumGothic"     # 한국어 지원 폰트 (없으면 기본 폰트 사용)
SUBTITLE_FONT_SIZE = 52            # 폰트 크기
SUBTITLE_FONT_COLOR = "white"     # 글자 색상
SUBTITLE_OUTLINE_COLOR = "black"  # 테두리 색상
SUBTITLE_OUTLINE_WIDTH = 3         # 테두리 두께
SUBTITLE_MARGIN_V = 120           # 하단 여백 (세로)
SUBTITLE_MARGIN_H = 60            # 좌우 여백
SUBTITLE_ALIGNMENT = 2            # ASS 정렬: 2 = 하단 중앙

# ─── 스크립트 생성 설정 ───────────────────────────────────────────────────────
SCRIPT_LANGUAGE = "ko"            # 스크립트 생성 언어
SCRIPT_MAX_DURATION = 55          # 목표 낭독 시간 (초) - 영상 길이보다 짧게
SCRIPT_WORDS_PER_MINUTE = 300     # 한국어 평균 말하기 속도 (분당 단어 수)

# ─── 로그 설정 ────────────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
