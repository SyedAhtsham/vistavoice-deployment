from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
import os
import edge_tts
from moviepy.editor import ImageClip, AudioFileClip
from pydub import AudioSegment
import uuid
import asyncio
import re

app = Flask(__name__)
CORS(app, origins=["http://localhost:8080"])  # Allow React app

# File paths relative to server/ directory
UPLOAD_FOLDER = 'static/uploads'
OUTPUT_FOLDER = 'static/outputs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Available Microsoft Edge TTS voices (matching React app)
VOICES = [
    "en-US-AriaNeural", "en-US-GuyNeural", "en-US-JennyNeural", "en-US-ChristopherNeural",
    "es-MX-DaliaNeural", "es-MX-JorgeNeural", "es-US-PalomaNeural", "es-US-AlonsoNeural",
    "fr-FR-DeniseNeural", "fr-FR-HenriNeural"
]

@app.route('/generate_clip', methods=['POST'])
def generate_clip():
    try:
        # Get form data from React app
        image = request.files.get('image')
        texts = request.form.getlist('texts[]')
        voices = request.form.getlist('voices[]')
        speeds = request.form.getlist('speeds[]')
        silence_before = int(request.form.get('silence_before', 0))
        silence_between = int(request.form.get('silence_between', 0))
        silence_after = int(request.form.get('silence_after', 0))
        fadein = 'fadein' in request.form
        fadeout = 'fadeout' in request.form

        # Validate inputs
        if not image or not texts or not voices or not speeds or len(texts) != len(voices) or len(texts) != len(speeds):
            return jsonify({'error': 'Missing or mismatched inputs (texts, voices, or speeds)'}), 400

        # Sanitize image filename
        image_filename = image.filename
        image_basename = re.sub(r'[^\w\-_\.]', '_', os.path.splitext(image_filename)[0])
        image_ext = os.path.splitext(image_filename)[1]
        image_path = os.path.join(UPLOAD_FOLDER, f"{image_basename}{image_ext}")
        image.save(image_path)

        # Generate voiceovers
        audio_paths = []
        combined_audio = AudioSegment.silent(duration=0)

        for i, (text, voice, speed) in enumerate(zip(texts, voices, speeds)):
            if not text.strip() or voice not in VOICES:
                return jsonify({'error': 'Invalid text or voice selection'}), 400

            try:
                speed_float = float(speed)
                if not (0.5 <= speed_float <= 2.0):
                    return jsonify({'error': 'Speed must be between 0.5 and 2.0'}), 400
            except ValueError:
                return jsonify({'error': 'Invalid speed value'}), 400

            # Convert speed to edge_tts rate format (e.g., 1.5 -> "+50%", 0.5 -> "-50%")
            rate_percentage = (speed_float - 1) * 100
            rate = f"{rate_percentage:+.0f}%"

            # Generate voiceover
            output_path = os.path.join(OUTPUT_FOLDER, f"voiceover_{i}_{uuid.uuid4()}.mp3")
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(communicate.save(output_path))
            loop.close()

            # Load audio and add silence
            audio = AudioSegment.from_mp3(output_path)
            if i == 0:
                combined_audio += AudioSegment.silent(duration=silence_before)
            combined_audio += audio
            if i < len(texts) - 1:
                combined_audio += AudioSegment.silent(duration=silence_between)
            elif i == len(texts) - 1:
                combined_audio += AudioSegment.silent(duration=silence_after)

            audio_paths.append(output_path)

        # Export combined audio
        combined_audio_path = os.path.join(OUTPUT_FOLDER, f"combined_{uuid.uuid4()}.mp3")
        combined_audio.export(combined_audio_path, format="mp3", bitrate="320k")

        # Create video clip
        audio_clip = AudioFileClip(combined_audio_path)
        duration = len(combined_audio) / 1000
        image_clip = ImageClip(image_path).set_duration(duration).set_audio(audio_clip)

        # Apply fade effects
        if fadein:
            image_clip = image_clip.fadein(0.6)
        if fadeout:
            image_clip = image_clip.fadeout(0.6)

        # Save video with the same base name as the image
        video_filename = f"{image_basename}.mp4"
        video_path = os.path.join(OUTPUT_FOLDER, video_filename)
        image_clip.write_videofile(video_path, fps=30, codec="libx264", audio_codec="aac")

        # Clean up temporary files
        for audio_path in audio_paths:
            os.remove(audio_path)
        os.remove(combined_audio_path)
        os.remove(image_path)  # Clean up uploaded image

        # Return video URL
        video_url = f"/download/{video_filename}"
        return jsonify({'video_url': video_url})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download/<filename>')
def download(filename):
    try:
        return send_file(os.path.join(OUTPUT_FOLDER, filename), as_attachment=True)
    except FileNotFoundError:
        return jsonify({'error': 'File not found'}), 404

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)