"""
app.py - YouTube Shorts 자동화 웹 UI
실행: python app.py
"""

import os
import sys
import shutil
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
    """영상 설정을 config에 반영합니다."""
    config.WHISPER_MODEL = whisper_model
    config.TTS_VOICE = tts_voice
    config.TTS_RATE = tts_rate
    config.VIDEO_MAX_DURATION = int(max_duration)
    return (
        f"✅ 설정 저장됨 "
        f"(Whisper: {whisper_model}, 음성: {tts_voice}, 최대길이: {max_duration}초)"
    )


# ── 파이프라인 실행 ──────────────────────────────────────────────────────────

def run_pipeline_ui(topic: str, output_name: str, keep_temp: bool, bgm_file, progress=gr.Progress()):
    """
    Gradio UI에서 파이프라인을 단계별로 실행합니다.

    파이프라인 순서:
      STEP 1: Gemini 대본 생성 (sentences 포함)
      STEP 2: gTTS 음성 합성
      STEP 3: 문장별 Pexels 클립 다운로드
      STEP 4: 클립 이어붙이기 → background.mp4
      STEP 5: Whisper 단어별 자막 생성 (ASS 포맷)
      STEP 6: FFmpeg 영상 합성 (배경 + 음성 + ASS 자막 + 선택적 BGM)
      STEP 7: 썸네일 추출 (compose_video 내부에서 자동)
    """
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

    # BGM 파일 경로 처리 (Gradio File 컴포넌트는 임시 경로 문자열 반환)
    bgm_path = None
    if bgm_file is not None:
        bgm_path = Path(bgm_file) if isinstance(bgm_file, str) else Path(bgm_file.name)
        if not bgm_path.exists():
            bgm_path = None

    # temp 디렉토리 초기화
    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)

    log_lines = []

    def log(msg):
        log_lines.append(msg)
        return "\n".join(log_lines)

    try:
        # ── STEP 1: 대본 생성
        progress(0.05, desc="대본 생성 중...")
        yield log("🤖 [1/6] Gemini AI로 대본 생성 중..."), None

        from src.script_generator import generate_script
        script_result = generate_script(topic)

        sentence_summary = ""
        if script_result.sentences:
            sentence_summary = "\n\n[문장별 키워드]\n"
            for i, s in enumerate(script_result.sentences, 1):
                sentence_summary += f"  [{i}] {s['text'][:30]} → {s.get('keyword', '')}\n"

        yield log(
            f"✅ 대본 완성!\n"
            f"   제목: {script_result.title}\n"
            f"   예상 시간: {script_result.estimated_duration}초\n"
            f"   문장 수: {len(script_result.sentences)}개\n"
            f"\n[Gemini 원본 응답]\n{script_result.raw_response}\n"
            f"\n[TTS에 전달할 스크립트]\n{script_result.script}\n"
            f"{sentence_summary}"
        ), None

        # ── STEP 2: 음성 합성
        progress(0.15, desc="음성 합성 중...")
        yield log("🔊 [2/6] Google TTS로 음성 생성 중..."), None

        from src.tts_generator import generate_tts
        audio_path = generate_tts(
            text=script_result.script,
            output_filename="narration.mp3",
        )

        from src.video_composer import _get_audio_duration
        audio_dur = _get_audio_duration(audio_path)
        audio_size_kb = audio_path.stat().st_size / 1024
        yield log(
            f"✅ 음성 생성 완료: {audio_path.name} "
            f"({audio_size_kb:.1f}KB, 실제길이: {audio_dur:.1f}초)\n"
        ), None

        # ── STEP 3: 문장별 클립 다운로드
        progress(0.30, desc="배경 영상 다운로드 중...")

        if script_result.sentences:
            clip_count = len(script_result.sentences)
            yield log(
                f"🎞️ [3/6] 문장별 클립 {clip_count}개 다운로드 중...\n"
                f"   (각 문장에 맞는 영상을 Pexels에서 검색합니다)\n"
            ), None

            from src.video_downloader import download_clips_per_sentence
            clip_duration = max(5, int(audio_dur / max(clip_count, 1)) + 2)
            clip_paths = download_clips_per_sentence(
                sentences=script_result.sentences,
                output_dir=config.TEMP_DIR,
                clip_duration=clip_duration,
            )
        else:
            kw_count = len(script_result.pexels_keywords) or 1
            yield log(
                f"🎞️ [3/6] 키워드별 클립 {kw_count}개 다운로드 중 (폴백)...\n"
            ), None

            from src.video_downloader import download_multiple_videos
            clip_duration = max(5, script_result.estimated_duration // kw_count)
            clip_paths = download_multiple_videos(
                keywords=script_result.pexels_keywords,
                output_dir=config.TEMP_DIR,
                clip_duration=clip_duration,
            )

        yield log(f"✅ 클립 {len(clip_paths)}개 다운로드 완료\n"), None

        # ── STEP 4: 클립 이어붙이기
        progress(0.50, desc="클립 이어붙이는 중...")
        yield log("🔗 [4/6] 클립 이어붙이는 중..."), None

        from src.video_composer import concatenate_clips
        concat_path = config.TEMP_DIR / "background_concat.mp4"
        background_path = concatenate_clips(clip_paths, concat_path, audio_dur)
        yield log(f"✅ 클립 이어붙이기 완료 → {background_path.name}\n"), None

        # ── STEP 5: Whisper 단어별 자막 생성
        progress(0.65, desc="자막 생성 중...")
        yield log(
            f"📝 [5/6] Whisper({config.WHISPER_MODEL})로 단어별 자막 생성 중...\n"
            f"   (ASS 포맷, 단어 하나씩 팝업)\n"
        ), None

        from src.subtitle_generator import generate_subtitles
        subtitle_path = generate_subtitles(
            audio_path=audio_path,
            output_dir=config.TEMP_DIR,
        )
        yield log(f"✅ 자막 생성 완료: {subtitle_path.name}\n"), None

        # ── STEP 6: FFmpeg 영상 합성
        progress(0.80, desc="영상 합성 중...")
        bgm_info = f" + BGM({bgm_path.name})" if bgm_path else ""
        yield log(f"🎬 [6/6] FFmpeg으로 최종 영상 합성 중{bgm_info}..."), None

        from src.video_composer import compose_video
        final_video = compose_video(
            background_path=background_path,
            audio_path=audio_path,
            subtitle_path=subtitle_path,
            output_filename=output_name,
            bgm_path=bgm_path,
        )

        if not keep_temp:
            shutil.rmtree(config.TEMP_DIR, ignore_errors=True)
            config.TEMP_DIR.mkdir(exist_ok=True)

        progress(1.0, desc="완료!")

        thumbnail = config.OUTPUT_DIR / (Path(output_name).stem + "_thumbnail.jpg")
        thumb_info = f"\n   썸네일: {thumbnail.name}" if thumbnail.exists() else ""

        file_size_mb = final_video.stat().st_size / (1024 * 1024)
        yield log(
            f"\n🎉 완성!\n"
            f"   파일: {final_video}\n"
            f"   크기: {file_size_mb:.1f}MB\n"
            f"   음성 길이: {audio_dur:.1f}초\n"
            f"   클립 수: {len(clip_paths)}개"
            f"{thumb_info}"
        ), str(final_video)

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        yield log(f"\n❌ 오류 발생: {e}\n\n{tb}"), None


# ── UI 구성 ──────────────────────────────────────────────────────────────────

def build_ui():
    gemini_key, pexels_key = load_env_values()

    with gr.Blocks(title="YouAuto - YouTube Shorts 자동화") as demo:

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
                        bgm_upload = gr.File(
                            label="배경음악 파일 (선택사항, MP3)",
                            file_types=[".mp3"],
                        )
                        keep_temp_check = gr.Checkbox(
                            label="임시 파일 유지 (클립, 음성, 자막 파일)",
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
                            lines=18,
                            interactive=False,
                            placeholder="생성 버튼을 누르면 여기에 진행 상황이 표시됩니다...",
                        )
                        video_output = gr.Video(
                            label="완성된 영상 미리보기",
                            visible=True,
                        )

                generate_btn.click(
                    fn=run_pipeline_ui,
                    inputs=[topic_input, output_name_input, keep_temp_check, bgm_upload],
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
                        gr.Markdown("#### 🎙️ 음성 설정 (Google TTS)")
                        tts_voice = gr.Dropdown(
                            label="말하기 속도",
                            choices=["보통", "느리게"],
                            value="보통",
                            info="보통: 일반 속도, 느리게: 천천히",
                        )
                        tts_rate = gr.Slider(
                            label="말하기 속도 (미사용)",
                            minimum=-50,
                            maximum=50,
                            value=0,
                            step=5,
                            info="gTTS는 slow 옵션만 지원합니다",
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
- **🔑 API 키 설정** 탭에서 Gemini, Pexels 키 입력 후 저장

#### 2단계: FFmpeg 설치 (필수)
```bash
# Windows: https://ffmpeg.org/download.html 에서 다운로드
# 환경변수 PATH에 ffmpeg/bin 추가 후 재시작
ffmpeg -version  # 확인
```

#### 3단계: 영상 생성
- **🎬 영상 생성** 탭에서 주제 입력 후 `영상 생성 시작` 클릭
- 배경음악(MP3) 파일을 올리면 BGM이 15% 볼륨으로 자동 믹싱됩니다

---

### ⚙️ 자동화 파이프라인
```
주제 입력
  ↓ Gemini AI    → 한국어 쇼츠 대본 + 문장별 키워드 생성
  ↓ gTTS         → 한국어 음성 (.mp3)
  ↓ Pexels API   → 문장별 배경 영상 클립 다운로드
  ↓ FFmpeg       → 클립 이어붙이기
  ↓ Whisper      → 단어별 팝업 자막 생성 (ASS 포맷)
  ↓ FFmpeg       → 영상 + 음성 + ASS자막 + BGM(선택) 합성
  ↓ FFmpeg       → 썸네일 자동 추출
  ↓
완성된 Shorts 영상 (1080x1920, MP4)
```

---

### 📁 출력 파일 위치
- 완성 영상: `output/shorts_output.mp4`
- 썸네일: `output/shorts_output_thumbnail.jpg`
- 임시 파일: `output/temp/` (자동 삭제됨)

---

### ❓ 자주 묻는 질문

**Q: Whisper 모델은 뭘 써야 하나요?**
- `tiny`: 빠름, 정확도 낮음
- `base`: 균형 잡힘 (권장)
- `small` ~ `large`: 느리지만 정확

**Q: ASS 자막이란?**
- 각 단어가 하나씩 나타나는 팝업 방식의 자막입니다.
- Whisper의 word_timestamps 기능으로 정확한 타이밍을 추출합니다.

**Q: BGM 볼륨 조절은?**
- 현재 기본 15% 볼륨으로 믹싱됩니다.
- `config.py`의 `BGM_VOLUME` 값을 수정하면 조절 가능합니다.
                """)

    return demo


if __name__ == "__main__":
    demo = build_ui()
    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        inbrowser=True,
        show_error=True,
        theme=gr.themes.Soft(primary_hue="red"),
        css="""
        .title-text { text-align: center; margin-bottom: 0.5rem; }
        .subtitle-text { text-align: center; color: #888; margin-bottom: 1.5rem; }
        footer { display: none !important; }
        """,
    )
