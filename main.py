import json
import os
import platform
import re
import ssl
import subprocess
import sys
import certifi
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

WISTIA_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "referer": "https://massolit.io/",
    "sec-ch-ua": '"Chromium";v="152", "Not?A_Brand";v="24", "Google Chrome";v="152"',
    "sec-ch-ua-mobile": "?1",
    "sec-ch-ua-platform": '"Android"',
    "sec-fetch-dest": "script",
    "sec-fetch-mode": "no-cors",
    "sec-fetch-site": "cross-site",
    "sec-fetch-storage-access": "none",
    "user-agent": "Mozilla/5.0 (Linux; Android 16; Pixel 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Mobile Safari/537.36",
}

MASSOLIT_HEADERS = {
    "User-Agent": WISTIA_HEADERS["user-agent"],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class CourseParser(HTMLParser):
    """Parses course overview pages for all individual lesson URLs and media IDs."""
    def __init__(self) -> None:
        super().__init__()
        self.lessons: list[tuple[str, str]] = []  # [(slug, media_id)]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attributes = dict(attrs)
        href = attributes.get("href", "")
        media_id = attributes.get("data-hash")
        if media_id and href:
            slug = urlparse(href).path.rstrip("/").split("/")[-1]
            self.lessons.append((slug, media_id))


def send_desktop_notification(title: str, message: str) -> None:
    """Sends a native OS notification on macOS, Linux, or Windows."""
    system = platform.system()
    try:
        if system == "Darwin":  # macOS
            os.system(f"""osascript -e 'display notification "{message}" with title "{title}"'""")
        elif system == "Linux":
            subprocess.run(["notify-send", title, message], check=False)
        elif system == "Windows":
            ps_script = f'[reflection.assembly]::loadwithpartialname("System.Windows.Forms"); [System.Windows.Forms.MessageBox]::Show("{message}", "{title}")'
            subprocess.run(["powershell", "-Command", ps_script], check=False)
    except Exception:
        pass


def fetch_massolit_html(url: str) -> str:
    request = Request(url, headers=MASSOLIT_HEADERS)
    with urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_wistia_jsonp(media_id: str) -> str:
    endpoint = f"https://fast.wistia.com/embed/medias/{media_id}.jsonp"
    request = Request(endpoint, headers=WISTIA_HEADERS)
    with urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def download_and_clean_transcript(media_id: str, transcript_path: str) -> None:
    """Downloads the transcript VTT file from Massolit and saves it as clean text."""
    url = f"https://massolit.io/subtitles/{media_id}/download"
    request = Request(url, headers=MASSOLIT_HEADERS)
    try:
        with urlopen(request, timeout=15, context=SSL_CONTEXT) as response:
            content = response.read().decode("utf-8", errors="replace")

        # Strip VTT timestamps and header tags to format clean readable text
        lines = content.splitlines()
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("WEBVTT") or "-->" in line or line.isdigit():
                continue
            # Remove inline formatting tags like <v ...> or <b>
            clean_line = re.sub(r"<[^>]+>", "", line)
            if clean_line and (not cleaned_lines or cleaned_lines[-1] != clean_line):
                cleaned_lines.append(clean_line)

        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write("\n".join(cleaned_lines))
    except Exception:
        # Ignore transcript download errors if unavailable for a specific lesson
        pass


def parse_wistia_payload(jsonp_data: str, target_height: int | None | str) -> tuple[str, str | None, int, float]:
    """Extracts video stream URL, subtitle (.vtt) URL, actual height, and media duration."""
    start_idx = jsonp_data.find("{")
    end_idx = jsonp_data.rfind("}")
    
    if start_idx == -1 or end_idx == -1 or start_idx >= end_idx:
        raise ValueError("Failed to extract JSON payload from Wistia response.")

    json_str = jsonp_data[start_idx : end_idx + 1]
    data = json.loads(json_str)
    
    media = data.get("media", {})
    duration = float(media.get("duration", 0))
    assets = media.get("assets", [])
    captions = media.get("captions", [])

    # Extract Subtitles (.vtt)
    subtitle_url = captions[0].get("url") if captions else None
    
    # Filter out storyboard grids and non-video assets[cite: 1]
    valid_video_assets = [
        a for a in assets
        if a.get("url", "").endswith(".bin")
        and a.get("type") != "storyboard"
        and a.get("container") not in {"jpg", "jpeg", "png"}
        and "storyboard" not in a.get("display_name", "").lower()
    ]
    
    if not valid_video_assets:
        raise ValueError("No valid video stream found in media payload.")

    # Match exact resolution if target_height is specified integer
    if isinstance(target_height, int):
        for asset in valid_video_assets:
            if asset.get("height") == target_height:
                return asset["url"], subtitle_url, target_height, duration

    # Fallback to highest available video resolution
    best_asset = max(valid_video_assets, key=lambda a: a.get("height", 0))
    return best_asset["url"], subtitle_url, best_asset.get("height", 0), duration


def parse_range_input(selection_str: str, max_val: int) -> list[int]:
    """Parses selection input supporting formats like '1', '1, 3, 5', or '1-4, 7-9'."""
    if not selection_str or selection_str.strip() == "0":
        return list(range(1, max_val + 1))

    selected_indices = set()
    parts = selection_str.split(",")

    for part in parts:
        part = part.strip()
        if "-" in part:
            bounds = part.split("-")
            if len(bounds) == 2 and bounds[0].isdigit() and bounds[1].isdigit():
                start, end = int(bounds[0]), int(bounds[1])
                for idx in range(min(start, end), max(start, end) + 1):
                    if 1 <= idx <= max_val:
                        selected_indices.add(idx)
        elif part.isdigit():
            idx = int(part)
            if 1 <= idx <= max_val:
                selected_indices.add(idx)

    return sorted(list(selected_indices)) or list(range(1, max_val + 1))


def download_media_task(
    slug: str,
    media_id: str,
    seq_num: int,
    total_tracks: int,
    course_name: str,
    output_dir: str,
    target_height: int | None | str,
    is_audio_only: bool,
    position: int = 0
) -> None:
    """Task worker to process and download an individual video or audio stream with metadata and transcripts."""
    jsonp_raw = fetch_wistia_jsonp(media_id)
    stream_url, subtitle_url, actual_height, duration = parse_wistia_payload(jsonp_raw, target_height)

    # File Naming with Ordered Prefixes
    ext = "mp3" if is_audio_only else "mp4"
    quality_label = "audio" if is_audio_only else f"{actual_height}p"
    base_name = f"{seq_num:02d}_{slug}_{quality_label}"
    filename = f"{base_name}.{ext}"
    output_path = os.path.join(output_dir, filename)

    # Fetch and save clean transcript (.txt)
    transcript_path = os.path.join(output_dir, f"{seq_num:02d}_{slug}_transcript.txt")
    if not os.path.exists(transcript_path):
        download_and_clean_transcript(media_id, transcript_path)

    # File Skipping Check
    if os.path.exists(output_path) and os.path.getsize(output_path) > 100_000:
        print(f"[=] Skipping {filename} (already downloaded).")
        return

    # Metadata Strings
    clean_title = slug.replace("-", " ").title()
    clean_album = course_name.replace("-", " ").title()

    # Construct ffmpeg Command
    cmd = [
        "ffmpeg",
        "-y",
        "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
        "-i", stream_url,
    ]

    # Subtitle Input
    if subtitle_url and not is_audio_only:
        cmd.extend(["-i", subtitle_url])

    # Audio-only or Video Mode Setup
    if is_audio_only:
        cmd.extend(["-vn", "-c:a", "mp3", "-b:a", "192k"])
    else:
        cmd.extend(["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"])
        if subtitle_url:
            cmd.extend([
                "-c:s", "mov_text",
                "-metadata:s:s:0", "language=eng"
            ])

    # Metadata Tagging
    cmd.extend([
        "-metadata", f"title={clean_title}",
        "-metadata", f"album={clean_album}",
        "-metadata", "artist=Massolit",
        "-metadata", f"track={seq_num}/{total_tracks}",
    ])

    cmd.extend(["-progress", "pipe:1", "-nostats", output_path])

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            bufsize=1,
        )
    except FileNotFoundError:
        raise RuntimeError("ffmpeg is not installed or not in system PATH.")

    # Progress Tracking via tqdm
    if tqdm and duration > 0:
        pbar = tqdm(
            total=int(duration),
            desc=f"[{seq_num:02d}] {slug[:18]}...",
            unit="s",
            leave=False,
            file=sys.stderr,
            position=position,
            dynamic_ncols=True,
            bar_format="{l_bar}{bar:15}| {n_fmt}/{total_fmt}s",
        )
        last_out_time = 0.0

        for line in process.stdout:
            if line.startswith("out_time_ms="):
                try:
                    microseconds = float(line.split("=")[1].strip())
                    current_seconds = microseconds / 1_000_000
                    current_seconds = min(current_seconds, duration)
                    delta = current_seconds - last_out_time
                    if delta > 0:
                        pbar.update(min(delta, duration - pbar.n))
                        last_out_time = current_seconds
                except ValueError:
                    pass

        process.wait()
        pbar.n = int(duration)
        pbar.refresh()
        pbar.close()
        print(f"[+] Complete: {filename}")
    else:
        print(f"[+] Downloading {filename}...")
        process.wait()
        print(f"[+] Complete: {filename}")

    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg download failed for {filename}")


def prompt_quality_selection() -> tuple[int | None | str, bool]:
    print("\nSelect Format & Quality Preference:")
    print("  [1] 1080p")
    print("  [2] 720p")
    print("  [3] 480p")
    print("  [4] 360p")
    print("  [5] Highest Available (Default)")
    print("  [6] Audio Only (.mp3 Podcast Mode)")
    
    choice = input("Enter choice (1-6) [Default: 5]: ").strip()
    
    if choice == "6":
        return "audio", True
        
    quality_map = {"1": 1080, "2": 720, "3": 480, "4": 360}
    return quality_map.get(choice, None), False


def prompt_lesson_selection(lessons: list[tuple[str, str]]) -> list[tuple[int, str, str]]:
    print("\nAvailable Lessons in Course:")
    print("  [0] Whole Course (All Videos)")
    for idx, (slug, _) in enumerate(lessons, 1):
        clean_title = slug.replace("-", " ").title()
        print(f"  [{idx}] {clean_title}")

    choice = input(f"\nSelect video numbers or ranges (e.g., '1', '1, 3, 5', '1-4') [Default: 0]: ").strip()
    selected_numbers = parse_range_input(choice, len(lessons))
    
    return [(idx, lessons[idx - 1][0], lessons[idx - 1][1]) for idx in selected_numbers]


def main() -> int:
    try:
        raw_url = input("Paste Massolit URL: ").strip()
        parsed = urlparse(raw_url)

        if "massolit.io" not in parsed.netloc:
            raise ValueError("Please enter a valid massolit.io URL.")

        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) >= 2 and path_parts[0] == "courses":
            course_slug = path_parts[1]
            course_url = f"https://massolit.io/courses/{course_slug}"
        else:
            course_url = raw_url
            course_slug = path_parts[-1]

        print(f"[+] Fetching course details from: {course_url}")
        html = fetch_massolit_html(course_url)

        parser = CourseParser()
        parser.feed(html)

        unique_lessons = []
        seen = set()
        for slug, m_id in parser.lessons:
            if m_id not in seen:
                seen.add(m_id)
                unique_lessons.append((slug, m_id))

        if not unique_lessons:
            raise ValueError("No lessons were found for this course.")

        target_height, is_audio_only = prompt_quality_selection()
        selected_tasks = prompt_lesson_selection(unique_lessons)

        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, course_slug)
        os.makedirs(output_dir, exist_ok=True)

        print(f"\n[+] Processing {len(selected_tasks)} file(s) into: /{course_slug}\n")

        # Multi-Threaded Parallel Downloads
        max_workers = min(3, len(selected_tasks))
        total_tracks = len(unique_lessons)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    download_media_task,
                    slug,
                    media_id,
                    seq_num,
                    total_tracks,
                    course_slug,
                    output_dir,
                    target_height,
                    is_audio_only,
                    idx % max_workers
                )
                for idx, (seq_num, slug, media_id) in enumerate(selected_tasks)
            ]
            for future in as_completed(futures):
                future.result()

        print("\n[+] All selected downloads complete!")
        send_desktop_notification("Massolit Downloader", f"Finished downloading {len(selected_tasks)} lesson(s) from {course_slug}!")

    except (HTTPError, URLError, UnicodeError, ValueError, json.JSONDecodeError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())