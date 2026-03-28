"""
app.py - YouTube Shorts 자동화 웹 UI
실행: python app.py
"""

import os
import sys
import time
import threading
from pathlib import Path
from dotenv import load_dotenv, set_key, dotenv_values

import gradio as gr

# .env 로드
ENV_PATH = Path(__file__).parent / ".env"
if not ENV_PATH.exists():
    ENV_PATH.write_text("")
load_dotenv(ENV_PATH, override=True)

sys.path.insert(0, str(Path(__file__).parent))
import config


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def load_env_values():
    vals = dotenv_values(ENV_PATH)
    return vals.get("GEMINI_API_KEY", ""), vals.get("PEXELS_API_KEY", "")


def save_api_keys(gemini_key: str, pexels_key: str):
    """API 키를 .env 파일에 저장"""
    gemini_key = gemini_key.strip()
    pexels_key = pexels_key.strip()

    if not ENV_PATH.exists():
        ENV_PATH.write_text("")

    set_key(str(ENV_PATH), "GEMINI_API_KEY", gemini_key)
    set_key(str(ENV_PATH), "PEXELS_API_KEY", pexels_key)

    os.environ["GEMINI_API_KEY"] = gemini_key
    os.environ["PEXELS_API_KEY"] = pexels_key

    config.GEMINI_API_KEY = gemini_key
    config.PEXELS_API_KEY = pexels_key

    status = []
    status.append("✅ GEMINI_API_KEY " + ("저장됨" if gemini_key else "⚠️ 비어있음"))
    status.append("✅ PEXELS_API_KEY " + ("저장됨" if pexels_key else "⚠️ 비어있음"))
    return "\n".join(status)


def save_video_settings(whisper_model, tts_voice, tts_rate, max_duration):
    """영상 설정을 config에 반영"""
    config.WHISPER_MODEL = whisper_model
    config.TTS_VOICE = tts_voice
    config.TTS_RATE = tts_rate
    config.VIDEO_MAX_DURATION = int(max_duration)
    return f"✅ 설정 저장됨 (Whisper: {whisper_model}, 음성: {tts_voice}, 최대길이: {max_duration}초)"


# ── 파이프라인 실행 ──────────────────────────────────────────────────────────

def run_pipeline_ui(topic: str, output_name: str, keep_temp: bool, progress=gr.Progress()):
    """Gradio UI에서 파이프라인을 단계별로 실행"""

    if not topic.strip():
        yield "❌ 주제를 입력하세요.", None
        return

    if not config.GEMINI_API_KEY:
        yield "❌ GEMINI_API_KEY가 설정되지 않았습니다.\n'API 키 설정' 탭에서 키를 입력하세요.", None
        return

    if not config.PEXELS_API_KEY:
        yield "❌ PEXELS_API_KEY가 설정되지 않았습니다.\n'API 키 설정' 탭에서 키를 입력하세요.", None
        return

    if not output_name.strip():
        output_name = "shorts_output.mp4"
    if not output_name.endswith(".mp4"):
        output_name += ".mp4"

    log_lines = []

    def log(msg):
        log_lines.append(msg)
        return "\n".join(log_lines)

    try:
        # ── STEP 1: 대본 생성
        progress(0.1, desc="대본 생성 중...")
        yield log("🤖 [1/5] Gemini AI로 대본 생성 중..."), None

        from src.script_generator import generate_script
        script_result = generate_script(topic)

        yield log(
            f"✅ 대본 완성!\n"
            f"   제목: {script_result.title}\n"
            f"   예상 시간: {script_result.estimated_duration}초\n"
            f"   검색 키워드: {script_result.pexels_keywords}\n"
            f"\n--- 생성된 스크립트 ---\n{script_result.script}\n---\n"
        ), None

        # ── STEP 2: 음성 합성
        progress(0.3, desc="음성 합성 중...")
        yield log("🔊 [2/5] Edge TTS로 음성 생성 중..."), None

        from src.tts_generator import generate_tts
        audio_path = generate_tts(
            text=script_result.script,
            output_filename="narration.mp3",
        )
        yield log(f"✅ 음성 생성 완료: {audio_path.name}\n"), None

        # ── STEP 3: 배경 영상 다운로드
        progress(0.5, desc="배경 영상 다운로드 중...")
        yield log("🎞️ [3/5] Pexels에서 배경 영상 다운로드 중..."), None

        from src.video_downloader import download_background_video
        background_path = download_background_video(
            keywords=script_result.pexels_keywords,
            output_filename="background.mp4",
            target_duration=script_result.estimated_duration,
        )
        yield log(f"✅ 배경 영상 다운로드 완료: {background_path.name}\n"), None

        # ── STEP 4: 자막 생성
        progress(0.7, desc="자막 생성 중...")
        yield log(f"📝 [4/5] Whisper({config.WHISPER_MODEL})로 자막 생성 중..."), None

        from src.subtitle_generator import generate_subtitles
        subtitle_path = generate_subtitles(
            audio_path=audio_path,
            output_filename="subtitles.srt",
        )
        yield log(f"✅ 자막 생성 완료: {subtitle_path.name}\n"), None

        # ── STEP 5: 영상 합성
        progress(0.9, desc="영상 합성 중...")
        yield log("🎬 [5/5] FFmpeg으로 최종 영상 합성 중..."), None

        from src.video_composer import compose_video
        import shutil
        final_video = compose_video(
            background_path=background_path,
            audio_path=audio_path,
            subtitle_path=subtitle_path,
            output_filename=output_name,
        )

        if not keep_temp:
            shutil.rmtree(config.TEMP_DIR, ignore_errors=True)

        progress(1.0, desc="완료!")
        yield log(
            f"\n🎉 완성!\n"
            f"   파일: {final_video}\n"
            f"   크기: {final_video.stat().st_size / (1024*1024):.1f}MB"
        ), str(final_video)

    except Exception as e:
        yield log(f"\n❌ 오류 발생: {e}"), None


# ── UI 구성 ──────────────────────────────────────────────────────────────────

def build_ui():
    gemini_key, pexels_key = load_env_values()

    with gr.Blocks(
        title="YouAuto - YouTube Shorts 자동화",
        theme=gr.themes.Soft(primary_hue="red"),
        css="""
        .title-text { text-align: center; margin-bottom: 0.5rem; }
        .subtitle-text { text-align: center; color: #888; margin-bottom: 1.5rem; }
        footer { display: none !important; }
        """
    ) as demo:

        gr.HTML('<h1 class="title-text">🎬 YouAuto</h1>')
        gr.HTML('<p class="subtitle-text">YouTube Shorts 영상 자동 생성기</p>')

        with gr.Tabs():

            # ── 탭 1: 영상 생성 ──────────────────────────────────────────
            with gr.Tab("🎬 영상 생성"):
                gr.Markdown("### 주제를 입력하고 Shorts 영상을 자동 생성하세요")

                with gr.Row():
                    with gr.Column(scale=2):
                        topic_input = gr.Textbox(
                            label="영상 주제",
                            placeholder="예: 건강한 아침 루틴 5가지",
                            lines=2,
                        )
                        output_name_input = gr.Textbox(
                            label="출력 파일명",
                            placeholder="shorts_output.mp4",
                            value="shorts_output.mp4",
                        )
                        keep_temp_check = gr.Checkbox(
                            label="임시 파일 유지 (음성, 자막 파일)",
                            value=False,
                        )
                        generate_btn = gr.Button(
                            "🚀 영상 생성 시작",
                            variant="primary",
                            size="lg",
                        )

                    with gr.Column(scale=3):
                        log_output = gr.Textbox(
                            label="진행 상황",
                            lines=15,
                            interactive=False,
                            placeholder="생성 버튼을 누르면 여기에 진행 상황이 표시됩니다...",
                        )
                        video_output = gr.Video(
                            label="완성된 영상 미리보기",
                            visible=True,
                        )

                generate_btn.click(
                    fn=run_pipeline_ui,
                    inputs=[topic_input, output_name_input, keep_temp_check],
                    outputs=[log_output, video_output],
                )

                gr.Examples(
                    examples=[
                        ["건강한 아침 루틴 5가지"],
                        ["파이썬 코딩 꿀팁"],
                        ["주식 투자 초보 가이드"],
                        ["다이어트 성공 비결"],
                        ["영어 공부 효과적으로 하는 법"],
                    ],
                    inputs=topic_input,
                    label="주제 예시 (클릭하면 입력됨)",
                )

            # ── 탭 2: API 키 설정 ────────────────────────────────────────
            with gr.Tab("🔑 API 키 설정"):
                gr.Markdown("""
### API 키 설정

API 키는 `.env` 파일에 안전하게 저장됩니다.

| 서비스 | 용도 | 무료 여부 | 발급 링크 |
|--------|------|-----------|-----------|
| **Google Gemini** | 대본 자동 생성 (gemini-2.5-flash) | ✅ 하루 20회 무료 | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| **Pexels** | 배경 영상 다운로드 | ✅ 완전 무료 | [pexels.com/api](https://www.pexels.com/api) |
                """)

                with gr.Row():
                    with gr.Column():
                        gemini_input = gr.Textbox(
                            label="Gemini API Key",
                            placeholder="AIza...",
                            value=gemini_key,
                            type="password",
                            info="Google AI Studio에서 무료 발급 (하루 20회 무료)",
                        )
                        pexels_input = gr.Textbox(
                            label="Pexels API Key",
                            placeholder="...",
                            value=pexels_key,
                            type="password",
                            info="배경 영상 다운로드에 사용됩니다 (완전 무료)",
                        )
                        save_keys_btn = gr.Button("💾 API 키 저장", variant="primary")
                        keys_status = gr.Textbox(
                            label="저장 상태",
                            interactive=False,
                            lines=2,
                        )

                save_keys_btn.click(
                    fn=save_api_keys,
                    inputs=[gemini_input, pexels_input],
                    outputs=keys_status,
                )

            # ── 탭 3: 고급 설정 ──────────────────────────────────────────
            with gr.Tab("⚙️ 고급 설정"):
                gr.Markdown("### 영상 생성 옵션 설정")

                with gr.Row():
                    with gr.Column():
                        gr.Markdown("#### 🎙️ 음성 설정 (Edge TTS)")
                        tts_voice = gr.Dropdown(
                            label="한국어 음성",
                            choices=[
                                "ko-KR-SunHiNeural",     # 여성 (기본)
                                "ko-KR-InJoonNeural",    # 남성
                                "ko-KR-HyunsuNeural",    # 남성 2
                            ],
                            value=config.TTS_VOICE,
                            info="SunHi: 여성, InJoon/Hyunsu: 남성",
                        )
                        tts_rate = gr.Slider(
                            label="말하기 속도",
                            minimum=-50,
                            maximum=50,
                            value=0,
                            step=5,
                            info="-50(느림) ~ +50(빠름), 0이 기본값",
                        )

                    with gr.Column():
                        gr.Markdown("#### 🤖 자막 설정 (Whisper)")
                        whisper_model = gr.Dropdown(
                            label="Whisper 모델",
                            choices=["tiny", "base", "small", "medium", "large"],
                            value=config.WHISPER_MODEL,
                            info="클수록 정확하지만 느림. base 권장",
                        )
                        max_duration = gr.Slider(
                            label="최대 영상 길이 (초)",
                            minimum=15,
                            maximum=60,
                            value=config.VIDEO_MAX_DURATION,
                            step=1,
                            info="YouTube Shorts 최대 60초",
                        )

                save_settings_btn = gr.Button("💾 설정 저장", variant="primary")
                settings_status = gr.Textbox(
                    label="저장 상태",
                    interactive=False,
                )

                def save_with_rate(wm, voice, rate, dur):
                    rate_str = f"+{rate}%" if rate >= 0 else f"{rate}%"
                    return save_video_settings(wm, voice, rate_str, dur)

                save_settings_btn.click(
                    fn=save_with_rate,
                    inputs=[whisper_model, tts_voice, tts_rate, max_duration],
                    outputs=settings_status,
                )

            # ── 탭 4: 사용 안내 ──────────────────────────────────────────
            with gr.Tab("📖 사용 안내"):
                gr.Markdown("""
### 🚀 빠른 시작 가이드

#### 1단계: API 키 설정
- **🔑 API 키 설정** 탭에서 Anthropic, Pexels 키 입력 후 저장

#### 2단계: FFmpeg 설치 (필수)
```bash
# Windows: https://ffmpeg.org/download.html 에서 다운로드
# 환경변수 PATH에 ffmpeg/bin 추가 후 재시작
ffmpeg -version  # 확인
```

#### 3단계: 영상 생성
- **🎬 영상 생성** 탭에서 주제 입력 후 `영상 생성 시작` 클릭

---

### ⚙️ 자동화 파이프라인
```
주제 입력
  ↓ Claude AI    → 한국어 쇼츠 대본 생성
  ↓ Edge TTS     → 자연스러운 한국어 음성 (.mp3)
  ↓ Pexels API   → 관련 배경 영상 자동 다운로드
  ↓ Whisper      → 자동 자막 생성 (.srt)
  ↓ FFmpeg       → 영상 + 음성 + 자막 합성
  ↓
완성된 Shorts 영상 (1080x1920, MP4)
```

---

### 📁 출력 파일 위치
- 완성 영상: `output/shorts_output.mp4`
- 임시 파일: `output/temp/` (자동 삭제됨)

---

### ❓ 자주 묻는 질문

**Q: Whisper 모델은 뭘 써야 하나요?**
- `tiny`: 빠름, 정확도 낮음
- `base`: 균형 잡힘 (권장)
- `small` ~ `large`: 느리지만 정확

**Q: 영상 생성이 너무 오래 걸려요**
- Whisper 모델을 `tiny`로 낮춰보세요
- 처음 실행 시 Whisper 모델 다운로드로 느릴 수 있습니다
                """)

    return demo


if __name__ == "__main__":
    demo = build_ui()
    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        inbrowser=True,       # 브라우저 자동 열기
        show_error=True,
        favicon_path=None,
    )
