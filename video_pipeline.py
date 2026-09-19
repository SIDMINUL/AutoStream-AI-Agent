import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq

load_dotenv()

HIGHLIGHT_MODEL = "openai/gpt-oss-20b"
WHISPER_MODEL = "whisper-large-v3-turbo"


def _run(cmd, timeout=900):
    try:
        return subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        tail = stderr[-2500:] if stderr else "FFmpeg returned a non-zero exit code without stderr output."
        raise RuntimeError(f"Command failed: {tail}") from exc


def _duration(path: str) -> float:
    result = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path
    ], timeout=60)
    return max(0.1, float(result.stdout.strip()))


def _extract_audio(source: str, destination: str):
    _run([
        "ffmpeg", "-y", "-i", source, "-vn", "-ac", "1", "-ar", "16000",
        "-b:a", "32k", destination
    ], timeout=900)


def _transcribe(audio_path: str):
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    with open(audio_path, "rb") as audio:
        response = client.audio.transcriptions.create(
            file=(Path(audio_path).name, audio.read()),
            model=WHISPER_MODEL,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
            temperature=0.0,
        )

    segments = []
    for segment in getattr(response, "segments", []) or []:
        text = getattr(segment, "text", "") or ""
        start = float(getattr(segment, "start", 0.0) or 0.0)
        end = float(getattr(segment, "end", start + 1.0) or start + 1.0)
        if text.strip():
            segments.append({"start": start, "end": end, "text": text.strip()})

    return getattr(response, "text", "") or "", segments


def _choose_highlight(transcript: str, segments: list[dict], duration: float) -> dict:
    if not transcript.strip() or not segments:
        return {"start": 0.0, "end": min(duration, 60.0), "reason": "No speech timestamps available."}

    compact = "\n".join(
        f"[{s['start']:.2f}-{s['end']:.2f}] {s['text']}" for s in segments
    )
    # Keep the prompt bounded for long recordings while retaining timestamps.
    compact = compact[:50000]

    llm = ChatGroq(model=HIGHLIGHT_MODEL, temperature=0.1, max_tokens=300)
    prompt = f"""You are the highlight editor for an AI video editing platform.
Choose ONE compelling short-form highlight from this transcript.

Rules:
- Prefer a strong hook, insight, punchline, surprising statement, story beat, or useful takeaway.
- Target 20-60 seconds.
- start must be before end.
- Keep timestamps inside the source duration ({duration:.2f} seconds).
- Return ONLY valid JSON:
{{"start": 12.5, "end": 48.2, "reason": "short reason"}}

Timestamped transcript:
{compact}
"""
    response = llm.invoke([HumanMessage(content=prompt)])
    raw = response.content.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {"start": segments[0]["start"], "end": min(segments[0]["start"] + 45, duration), "reason": "Fallback highlight."}

    try:
        data = json.loads(match.group())
        start = max(0.0, min(float(data["start"]), max(0.0, duration - 1.0)))
        end = min(float(data["end"]), duration)
        if end <= start:
            end = min(duration, start + 1.0)
        if end - start < 8:
            if duration <= 8:
                start, end = 0.0, duration
            else:
                end = min(duration, start + 20)
                if end - start < 1.0:
                    start, end = 0.0, duration
        return {"start": start, "end": end, "reason": str(data.get("reason", "AI-selected highlight"))[:240]}
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {"start": segments[0]["start"], "end": min(segments[0]["start"] + 45, duration), "reason": "Fallback highlight."}


def _srt_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:
        secs += 1
        millis = 0
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _write_srt(segments: list[dict], start: float, end: float, path: str):
    rows = []
    index = 1
    for segment in segments:
        s = max(float(segment["start"]), start)
        e = min(float(segment["end"]), end)
        if e <= s:
            continue
        rows.append(
            f"{index}\n{_srt_timestamp(s - start)} --> {_srt_timestamp(e - start)}\n"
            f"{segment['text']}\n"
        )
        index += 1
    Path(path).write_text("\n".join(rows), encoding="utf-8")


def _format_filter(platform: str) -> str:
    sizes = {
        "TikTok": (1080, 1920),
        "Instagram": (1080, 1920),
        "YouTube": (1920, 1080),
        "LinkedIn": (1920, 1080),
        "Twitter/X": (1280, 720),
    }
    width, height = sizes.get(platform, (1920, 1080))
    return f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"


def _subtitle_filter(path: str) -> str:
    escaped = path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return f"subtitles='{escaped}':force_style='FontName=Arial,FontSize=20,Outline=2,Shadow=1,MarginV=48'"


def render(source: str, output: str, platform: str, start: float, end: float, srt_path: str):
    vf = _format_filter(platform)
    filters = [vf]
    if Path(srt_path).exists() and Path(srt_path).read_text(encoding="utf-8").strip():
        filters.append(_subtitle_filter(srt_path))

    duration = max(0.1, end - start)
    _run([
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", source,
        "-t", f"{duration:.3f}",
        "-vf", ",".join(filters),
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart", output
    ], timeout=900)


def process_video(source: str, output: str, platform: str, work_dir: str):
    if not os.environ.get("GROQ_API_KEY"):
        raise RuntimeError("GROQ_API_KEY is not configured.")

    duration = _duration(source)
    audio = str(Path(work_dir) / "audio.mp3")
    srt = str(Path(work_dir) / "captions.srt")

    _extract_audio(source, audio)
    transcript, segments = _transcribe(audio)
    if duration <= 12:
        highlight = {
            "start": 0.0,
            "end": duration,
            "reason": "Short source video; using the full clip.",
        }
    else:
        highlight = _choose_highlight(transcript, segments, duration)


    _write_srt(segments, highlight["start"], highlight["end"], srt)
    render(source, output, platform, highlight["start"], highlight["end"], srt)

    return {
        "duration": round(duration, 2),
        "transcript": transcript[:20000],
        "highlight": highlight,
        "caption_count": sum(
            1 for s in segments
            if float(s["end"]) > highlight["start"] and float(s["start"]) < highlight["end"]
        ),
    }
