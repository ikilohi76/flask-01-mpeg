import os
import subprocess
import logging
import tempfile
import re
from flask import Flask, request, send_file, jsonify

# Konfigurasi logging lebih detail
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # Maksimal upload 500MB

def safe_remove(file_path):
    """Menghapus file dengan aman"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        logging.warning(f"Gagal menghapus {file_path}: {e}")

@app.route("/", methods=["GET"])
def home():
    return "FFmpeg API is running!"

@app.route("/process-video", methods=["POST"])
def process_video():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded!"}), 400

    file = request.files["file"]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_input:
        input_path = temp_input.name
        file.save(input_path)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_output:
        output_path = temp_output.name

    logging.info(f"Processing video: {input_path}")

    ffmpeg_path = subprocess.run(["which", "ffmpeg"], capture_output=True, text=True).stdout.strip()
    if not ffmpeg_path:
        ffmpeg_path = "ffmpeg"

    # 🔍 Dapatkan durasi video
    duration_cmd = [ffmpeg_path, "-i", input_path]
    duration_result = subprocess.run(duration_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", duration_result.stderr)
    if match:
        hours, minutes, seconds = map(float, match.groups())
        duration = hours * 3600 + minutes * 60 + seconds - 0.5  # Mengurangi sedikit agar tidak kelebihan durasi
        logging.info(f"Durasi asli video: {hours}:{minutes}:{seconds} (total {duration:.2f} detik)")
    else:
        logging.error("Gagal mendapatkan durasi video!")
        safe_remove(input_path)
        return jsonify({"error": "Failed to get video duration!"}), 500

    # ⚙️ Perintah FFmpeg dengan proteksi dari deteksi 
    command = [
        ffmpeg_path, "-y",
        "-loglevel", "info",
        "-hide_banner",
        "-fflags", "+genpts",
        "-r", "30",
        "-vsync", "vfr",
        "-i", input_path,
        "-t", str(duration),  # Gunakan durasi asli tanpa mengurangi terlalu banyak

        # 🎨 Filter visual lebih unik
        "-vf", "eq=contrast=1.02:brightness=0.02:saturation=1.04,"
               "noise=alls=5:allf=t,"
               "gblur=sigma=0.4,"
               "drawtext=text='\ \ ':fontsize=30:fontcolor=white@0.02:"
               "x=rand(0\,w-50):y=rand(0\,h-50)",  

        # 🎥 Encoding video
        "-c:v", "libx264",
        "-profile:v", "high",
        "-preset", "ultrafast",
        "-crf", "27",  # Lebih rendah untuk lebih banyak perubahan detail
        "-b:v", "1200k",
        "-pix_fmt", "yuv420p",

        # 🔊 Audio processing lebih unik
        "-c:a", "aac",
        "-b:a", "128k",
        "-af", "rubberband=pitch=1.015,volume=1.03",

        # 🔄 Sinkronisasi dan optimasi
        "-strict", "-2",
        "-shortest",
        "-movflags", "+faststart",

        # ❌ Hapus semua metadata dan chapters
        "-map_metadata", "-1",
        "-map_chapters", "-1",
        "-metadata", "title=",
        "-metadata", "artist=",
        "-metadata", "album=",
        "-metadata", "comment=",
        "-metadata", "encoder=",
        
        output_path
    ]

    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        logging.error("FFmpeg timeout! Video terlalu lama diproses.")
        safe_remove(input_path)
        safe_remove(output_path)
        return jsonify({"error": "Processing timeout!"}), 500

    logging.info(f"FFmpeg Exit Code: {result.returncode}")
    logging.info(f"FFmpeg Output: {result.stdout}")  
    logging.info(f"FFmpeg Error: {result.stderr}")  

    if result.returncode != 0 or not os.path.exists(output_path) or os.stat(output_path).st_size == 0:
        logging.error("FFmpeg gagal atau output video kosong!")
        safe_remove(input_path)
        safe_remove(output_path)
        return jsonify({"error": "FFmpeg failed or output file is empty!"}), 500

    response = send_file(output_path, as_attachment=True)

    safe_remove(input_path)
    safe_remove(output_path)

    return response

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
