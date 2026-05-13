from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import uuid
import os
import threading
import time

app = Flask(__name__)
CORS(app)

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

jobs = {}
stats = {"total": 0, "mp3": 0, "mp4": 0}


def do_convert(job_id, url, fmt, quality):
    jobs[job_id]["status"] = "processing"
    jobs[job_id]["progress"] = 10

    out_path = os.path.join(DOWNLOAD_FOLDER, job_id)

    def progress_hook(d):
        if d["status"] == "downloading":
            pct = d.get("_percent_str", "0%").strip().replace("%", "")
            try:
                jobs[job_id]["progress"] = min(int(float(pct) * 0.8), 80)
            except:
                pass

    try:
        if fmt == "mp3":
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": out_path + ".%(ext)s",
                "progress_hooks": [progress_hook],
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": quality.replace("k", "") if quality != "best" else "192",
                }],
                "quiet": True,
            }
            ext = "mp3"
        else:
            q_map = {
                "best": "bestvideo+bestaudio/best",
                "4k": "bestvideo[height<=2160]+bestaudio/best",
                "1080p": "bestvideo[height<=1080]+bestaudio/best",
                "720p": "bestvideo[height<=720]+bestaudio/best",
                "480p": "bestvideo[height<=480]+bestaudio/best",
                "360p": "bestvideo[height<=360]+bestaudio/best",
            }
            ydl_opts = {
                "format": q_map.get(quality, "bestvideo+bestaudio/best"),
                "outtmpl": out_path + ".%(ext)s",
                "progress_hooks": [progress_hook],
                "merge_output_format": "mp4",
                "quiet": True,
            }
            ext = "mp4"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        found = None
        for f in os.listdir(DOWNLOAD_FOLDER):
            if f.startswith(job_id):
                found = os.path.join(DOWNLOAD_FOLDER, f)
                break

        if not found:
            raise Exception("Output file not found after conversion.")

        jobs[job_id]["status"] = "done"
        jobs[job_id]["progress"] = 100
        jobs[job_id]["file"] = found
        jobs[job_id]["ext"] = ext

        stats["total"] += 1
        if fmt == "mp3":
            stats["mp3"] += 1
        else:
            stats["mp4"] += 1

        def cleanup():
            time.sleep(3600)
            try:
                os.remove(found)
            except:
                pass
            jobs.pop(job_id, None)

        threading.Thread(target=cleanup, daemon=True).start()

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["errorMessage"] = str(e)


@app.route("/")
def index():
    return jsonify({"status": "YTConvert backend running ✅"})


@app.route("/api/convert/start", methods=["POST"])
def start_convert():
    data = request.get_json(force=True)
    url = data.get("url", "").strip()
    fmt = data.get("format", "mp3").strip()
    quality = data.get("quality", "best").strip()

    if not url:
        return jsonify({"error": "No URL provided."}), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "queued", "progress": 0, "file": None, "ext": None, "errorMessage": None}

    thread = threading.Thread(target=do_convert, args=(job_id, url, fmt, quality), daemon=True)
    thread.start()

    return jsonify({"jobId": job_id}), 202


@app.route("/api/convert/status/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)


@app.route("/api/convert/download/<job_id>")
def download(job_id):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "File not ready."}), 404

    file_path = job["file"]
    ext = job.get("ext", "mp3")
    mime = "audio/mpeg" if ext == "mp3" else "video/mp4"

    return send_file(
        file_path,
        as_attachment=True,
        download_name=f"ytconvert_{job_id[:8]}.{ext}",
        mimetype=mime,
    )


@app.route("/api/convert/stats")
def get_stats():
    return jsonify({
        "totalConversions": stats["total"],
        "mp3Conversions": stats["mp3"],
        "mp4Conversions": stats["mp4"],
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
