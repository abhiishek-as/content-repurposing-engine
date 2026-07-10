import os
import sys
import json
import subprocess
import yt_dlp
from supabase import create_client, Client
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)

MAX_DURATION_SECONDS = 20 * 60  # 20-minute cap


def transcribe_audio(audio_path: str) -> dict:
    """
    Sends the audio file to Groq's Whisper API and returns the
    verbose JSON transcript. Requests WORD-level timestamps (not just
    segment-level) because segment boundaries are based on pauses/
    breathing, not grammar, and are often imprecise by a second or
    more — word-level timing lets us snap clip cuts to exact words
    and sentence-ending punctuation instead.
    """
    with open(audio_path, "rb") as audio_file:
        transcription = groq_client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-large-v3",
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
        )
    return transcription.model_dump()


def build_sentences_from_words(transcript: dict) -> list:
    """
    Reconstructs real sentence/phrase boundaries from word-level
    timestamps. Splits on sentence-ending punctuation (. ? ! and
    Devanagari ।/॥) AND on natural pauses in speech (a gap of 0.6s+
    between one word ending and the next starting). The pause-based
    fallback matters because Whisper often produces no punctuation at
    all for some languages (observed with Hindi) — relying on
    punctuation alone would treat an entire video as one sentence.
    """
    words = transcript.get("words", [])
    sentences = []
    current_words = []

    SENTENCE_END_CHARS = (".", "?", "!", "।", "॥")
    PAUSE_THRESHOLD_SECONDS = 0.6

    for idx, word_info in enumerate(words):
        current_words.append(word_info)
        text = word_info.get("word", "").strip()

        ends_with_punctuation = text.endswith(SENTENCE_END_CHARS)

        is_followed_by_pause = False
        if idx + 1 < len(words):
            gap = words[idx + 1]["start"] - word_info["end"]
            is_followed_by_pause = gap >= PAUSE_THRESHOLD_SECONDS

        if ends_with_punctuation or is_followed_by_pause:
            sentence_text = " ".join(w["word"].strip() for w in current_words)
            sentences.append(
                {
                    "start": current_words[0]["start"],
                    "end": current_words[-1]["end"],
                    "text": sentence_text,
                }
            )
            current_words = []

    if current_words:
        sentence_text = " ".join(w["word"].strip() for w in current_words)
        sentences.append(
            {
                "start": current_words[0]["start"],
                "end": current_words[-1]["end"],
                "text": sentence_text,
            }
        )

    return sentences


def analyze_transcript(transcript: dict, video_duration: int) -> list:
    """
    Sends sentence-boundary timestamps (built from word-level Whisper
    data, not Whisper's own imprecise segments) to Llama 3.3 and gets
    back structured JSON defining clip timeframes. Also snaps the
    LLM's chosen start/end to the nearest real sentence boundary as a
    safety net against small drift.
    """
    sentences = build_sentences_from_words(transcript)
    print(f"Built {len(sentences)} sentence boundaries from word timestamps")


    lines = []
    for s in sentences:
        start = round(s["start"], 2)
        end = round(s["end"], 2)
        lines.append(f"[{start}s - {end}s] {s['text']}")
    timestamped_transcript = "\n".join(lines)

    system_prompt = (
        "You are a short-form video editor. You are given a transcript "
        "broken into SENTENCES, each with an exact start and end "
        "timestamp. Identify 2-4 self-contained, high-impact moments "
        "suitable for standalone short vertical clips (like YouTube "
        "Shorts or Reels).\n\n"
        "CRITICAL RULES:\n"
        "1. Each clip's (end_time - start_time) MUST be between 15 and "
        "60 seconds. Combine multiple consecutive sentences to reach "
        "at least 15 seconds.\n"
        "2. start_time MUST exactly equal the start timestamp of some "
        "sentence in the list below, and end_time MUST exactly equal "
        "the end timestamp of some sentence in the list below. Never "
        "invent a timestamp that isn't one of the given sentence "
        "boundaries.\n"
        "3. Clips must not exceed the video's total duration of "
        f"{video_duration} seconds.\n\n"
        "Respond with ONLY valid JSON, no other text, no markdown fences, "
        "in exactly this shape:\n"
        '{"clips": [{"start_time": <number>, "end_time": <number>, '
        '"title": "<short punchy title>", "reason": "<one sentence>"}]}'
    )

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": timestamped_transcript},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )

    raw_content = response.choices[0].message.content
    parsed = json.loads(raw_content)
    clips = parsed.get("clips", [])

    sentence_starts = [s["start"] for s in sentences]
    sentence_ends = [s["end"] for s in sentences]

    def snap(value, options):
        return min(options, key=lambda o: abs(o - value)) if options else value

    valid_clips = []
    for clip in clips:
        start = clip.get("start_time")
        end = clip.get("end_time")
        if not (isinstance(start, (int, float)) and isinstance(end, (int, float))):
            continue

        # Safety net: snap to the nearest real sentence boundary in
        # case the LLM drifted slightly from the given options.
        start = snap(start, sentence_starts)
        end = snap(end, sentence_ends)

        clip_length = end - start
        if 0 <= start < end <= video_duration and 15 <= clip_length <= 60:
            clip["start_time"] = start
            clip["end_time"] = end
            valid_clips.append(clip)

    return valid_clips



def create_and_upload_clips(video_path: str, clips: list, job_id: str, work_dir: str) -> list:
    """
    Cuts each clip from the source video using ffmpeg stream-copy
    (no re-encoding), uploads each to Supabase Storage, and returns
    the clip metadata enriched with public URLs.
    """
    bucket = os.environ.get("SUPABASE_STORAGE_BUCKET", "clips")
    enriched_clips = []

    for i, clip in enumerate(clips):
        start = clip["start_time"]
        end = clip["end_time"]
        clip_filename = f"{job_id}_clip{i+1}.mp4"
        clip_path = os.path.join(work_dir, clip_filename)

        # Re-encode (not stream-copy) for frame-accurate cuts. Stream-copy
        # can only cut at keyframes, which caused clips to start/end
        # mid-word — re-encoding trades a few seconds of CPU time for
        # exact timestamp accuracy, worthwhile at this clip length.
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", video_path,
                "-ss", str(start),
                "-to", str(end),
                "-c:v", "libx264",
                "-c:a", "aac",
                "-preset", "veryfast",
                clip_path,
            ],
            check=True,
            capture_output=True,
        )

        with open(clip_path, "rb") as f:
            supabase.storage.from_(bucket).upload(
                path=clip_filename,
                file=f,
                file_options={"content-type": "video/mp4", "upsert": "true"},
            )

        public_url = supabase.storage.from_(bucket).get_public_url(clip_filename)

        enriched_clips.append(
            {
                **clip,
                "filename": clip_filename,
                "url": public_url,
            }
        )

    return enriched_clips


COOKIES_PATH = os.path.join(os.path.dirname(__file__), "cookies.txt")


def _yt_dlp_base_opts() -> dict:
    """
    Shared yt-dlp options. Adds cookiefile only if one actually exists
    (e.g. written by the GitHub Actions workflow) — locally, no
    cookies.txt exists, so this is silently skipped and yt-dlp runs
    unauthenticated, which is fine on a residential IP.

    remote_components enables yt-dlp's EJS challenge solver, needed
    to decode YouTube's obfuscated video URLs ("n challenge"). This
    downloads a small solver script from GitHub at runtime — yt-dlp
    requires this explicit opt-in rather than silently fetching
    remote code.
    """
    opts = {"quiet": True, "remote_components": ["ejs:github"]}
    if os.path.exists(COOKIES_PATH):
        opts["cookiefile"] = COOKIES_PATH
    return opts


def get_video_duration(youtube_url: str) -> int:
    """
    Fetches only metadata (no download) to check duration before
    committing to a full download.
    """
    ydl_opts = {**_yt_dlp_base_opts(), "skip_download": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=False)
        return int(info.get("duration", 0))


def download_video_and_extract_audio(youtube_url: str, job_id: str, work_dir: str):
    """
    Downloads the source video and produces a compressed 16kHz mono
    audio track for transcription, matching the brief's pipeline.
    Returns (video_path, audio_path).
    """
    video_path = os.path.join(work_dir, f"{job_id}.mp4")
    audio_path = os.path.join(work_dir, f"{job_id}.mp3")

    ydl_opts = {
        **_yt_dlp_base_opts(),
        "format": "best[ext=mp4]/best",
        "outtmpl": video_path,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([youtube_url])


    # Extract compressed mono 16kHz audio via ffmpeg — small enough
    # to stay well under Whisper API's upload size limits.
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video_path,
            "-ac", "1",
            "-ar", "16000",
            "-b:a", "64k",
            audio_path,
        ],
        check=True,
        capture_output=True,
    )

    return video_path, audio_path


def claim_next_job():
    """
    Finds the oldest PENDING job and atomically claims it by
    flipping its status to DOWNLOADING. Returns the job dict, or
    None if there's nothing to do.
    """
    result = (
        supabase.table("jobs")
        .select("*")
        .eq("status", "PENDING")
        .order("created_at", desc=False)
        .limit(1)
        .execute()
    )

    if not result.data:
        return None

    job = result.data[0]

    # Flip status immediately so a second worker run (e.g. two GitHub
    # Actions runs overlapping) won't grab the same job.
    update_result = (
        supabase.table("jobs")
        .update({"status": "DOWNLOADING"})
        .eq("id", job["id"])
        .eq("status", "PENDING")  # only succeeds if still PENDING
        .execute()
    )

    if not update_result.data:
        # Someone else claimed it between our select and update.
        return None

    return update_result.data[0]


def mark_failed(job_id: str, error_message: str):
    supabase.table("jobs").update(
        {"status": "FAILED", "error_message": error_message}
    ).eq("id", job_id).execute()


def main():
    job = claim_next_job()

    if job is None:
        print("No pending jobs. Exiting.")
        sys.exit(0)

    job_id = job["id"]
    youtube_url = job["youtube_url"]
    print(f"Claimed job {job_id} — {youtube_url}")

    # Check duration BEFORE downloading anything.
    try:
        duration = get_video_duration(youtube_url)
    except Exception as e:
        print(f"Failed to fetch video metadata: {e}")
        mark_failed(job_id, f"Could not fetch video metadata: {e}")
        sys.exit(1)

    print(f"Video duration: {duration} seconds")

    if duration > MAX_DURATION_SECONDS:
        msg = f"Video is {duration}s, exceeds {MAX_DURATION_SECONDS}s cap"
        print(msg)
        mark_failed(job_id, msg)
        sys.exit(1)

    # Save duration to the job row now that we know it.
    supabase.table("jobs").update(
        {"video_duration_seconds": duration}
    ).eq("id", job_id).execute()

    work_dir = os.path.join(os.path.dirname(__file__), "tmp")
    os.makedirs(work_dir, exist_ok=True)

    try:
        video_path, audio_path = download_video_and_extract_audio(
            youtube_url, job_id, work_dir
        )
    except Exception as e:
        print(f"Download/extraction failed: {e}")
        mark_failed(job_id, f"Download/extraction failed: {e}")
        sys.exit(1)

    print(f"Video downloaded to: {video_path}")
    print(f"Audio extracted to: {audio_path}")

    # Move to TRANSCRIBING before calling Groq.
    supabase.table("jobs").update(
        {"status": "TRANSCRIBING"}
    ).eq("id", job_id).execute()

    try:
        transcript = transcribe_audio(audio_path)
    except Exception as e:
        print(f"Transcription failed: {e}")
        mark_failed(job_id, f"Transcription failed: {e}")
        sys.exit(1)

    supabase.table("jobs").update(
        {"transcript": transcript}
    ).eq("id", job_id).execute()

    print("Transcription complete. First 200 chars:")
    print(transcript.get("text", "")[:200])

    # Move to ANALYZING before calling Llama.
    supabase.table("jobs").update(
        {"status": "ANALYZING"}
    ).eq("id", job_id).execute()

    try:
        clips = analyze_transcript(transcript, duration)
    except Exception as e:
        print(f"Analysis failed: {e}")
        mark_failed(job_id, f"Analysis failed: {e}")
        sys.exit(1)

    if not clips:
        print("LLM returned no valid clips.")
        mark_failed(job_id, "No valid clips identified by LLM")
        sys.exit(1)

    print(f"Identified {len(clips)} clip(s):")
    for c in clips:
        print(f"  {c['start_time']}s - {c['end_time']}s: {c.get('title')}")

    supabase.table("jobs").update(
        {"clip_metadata": {"clips": clips}}
    ).eq("id", job_id).execute()

    # Move to CLIPPING before running ffmpeg + uploads.
    supabase.table("jobs").update(
        {"status": "CLIPPING"}
    ).eq("id", job_id).execute()

    try:
        enriched_clips = create_and_upload_clips(video_path, clips, job_id, work_dir)
    except Exception as e:
        print(f"Clipping/upload failed: {e}")
        mark_failed(job_id, f"Clipping/upload failed: {e}")
        sys.exit(1)

    print("Uploaded clips:")
    for c in enriched_clips:
        print(f"  {c['title']}: {c['url']}")

    supabase.table("jobs").update(
        {
            "status": "COMPLETED",
            "clip_metadata": {"clips": enriched_clips},
        }
    ).eq("id", job_id).execute()

    print("Job COMPLETED.")


if __name__ == "__main__":
    main()