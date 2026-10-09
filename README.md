# Massolit Course & Media Downloader

An automated Python tool designed to download courses, lectures, audio tracks, embedded subtitles, and clean text transcripts from **Massolit**.

## Features

- **High-Definition Downloads**: Select resolutions up to 1080p, or default to the highest available stream.
- **Audio-Only / Podcast Mode**: Option to export pure `.mp3` audio files with re-encoded AAC/MP3 tracks to eliminate video components and save bandwidth.
- **Transcript Downloader**: Automatically extracts clean text transcripts (`.txt`) alongside each lesson, removing VTT timestamp artifacts.
- **Embedded Subtitles**: Muxes Soft English subtitles (`mov_text`) directly into `.mp4` containers.
- **Metadata Tagging**: Automatically embeds track numbers, course titles, titles, and artists directly into MP4/MP3 media tags via `ffmpeg`.
- **Flexible Multi-Select**: Download individual videos, custom comma-separated selections, or range blocks (e.g., `1, 3, 5-8` or `0` for whole courses).
- **Concurrent Queueing**: Fast multi-threaded parallel downloads with real-time terminal progress indicators using `tqdm`.
- **Cross-Platform**: Fully compatible across Windows, macOS, and Linux, with native desktop notifications upon queue completion.

---

## Requirements & Prerequisites

### 1. System Dependencies
This script requires **`ffmpeg`** installed and available in your system `PATH`.

- **macOS**: `brew install ffmpeg`
- **Linux (Ubuntu/Debian)**: `sudo apt install ffmpeg`
- **Windows**: Download binary builds from [ffmpeg.org](https://ffmpeg.org/download.html) and add the `bin/` directory to your System Environment Variables.

### 2. Python Dependencies
Install required Python packages via `pip`:

```bash
pip install tqdm certifi
```

---

## Usage

1. Clone or download this repository:
   ```bash
   git clone https://github.com/NathanStephenStanley/Massolit-Course-Media-Downloader.git
   cd Massolit-Course-Media-Downloader
   ```

2. Run the script:
   ```bash
   python main.py
   ```

3. **Follow the interactive prompts**:
   - **URL Input**: Paste a Massolit course or lesson URL (e.g., `https://massolit.io/courses/priestley-an-inspector-calls`).
   - **Quality Preference**: Choose video resolution (`1080p`, `720p`, `480p`, `360p`, `Highest`) or select `Audio Only (.mp3)`.
   - **Lesson Selection**: Select specific lesson numbers (`1, 3, 5`), range selections (`1-5`), or enter `0` to download the entire course.

---

## File Organization Structure

All media and transcript files are organized inside a folder named after the course slug:

```text
priestley-an-inspector-calls/
├── 01_introduction_1080p.mp4
├── 01_introduction_transcript.txt
├── 02_historical-context-politics-and-society_1080p.mp4
├── 02_historical-context-politics-and-society_transcript.txt
└── ...
```

---

## Disclaimer

This tool is created for personal offline educational reference only. Ensure compliance with Massolit's terms of service and copyright regulations when downloading course materials.
