from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
import requests
import json
import os

app = Flask(__name__, static_folder='.')
CORS(app)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
API_KEY    = "sk-afri-cbdd588d618d43e497791c9975734d27"
BASE_URL   = "https://build.lewisnote.com/v1"
DAILY_LIMIT = 5   # générations gratuites par jour par IP

# ─── RATE LIMIT (in-memory, reset au redémarrage) ─────────────────────────────
from collections import defaultdict
from datetime import date

usage = defaultdict(lambda: {"date": str(date.today()), "count": 0})

def check_limit(ip):
    today = str(date.today())
    if usage[ip]["date"] != today:
        usage[ip] = {"date": today, "count": 0}
    if usage[ip]["count"] >= DAILY_LIMIT:
        return False
    usage[ip]["count"] += 1
    return True

def get_remaining(ip):
    today = str(date.today())
    if usage[ip]["date"] != today:
        return DAILY_LIMIT
    return max(0, DAILY_LIMIT - usage[ip]["count"])

def afri_headers():
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

# ─── SERVE FRONTEND ───────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# ─── REMAINING CREDITS ────────────────────────────────────────────────────────
@app.route('/api/remaining')
def remaining():
    ip = request.remote_addr
    return jsonify({"remaining": get_remaining(ip), "limit": DAILY_LIMIT})

# ─── ENHANCE PROMPT ───────────────────────────────────────────────────────────
@app.route('/api/enhance', methods=['POST'])
def enhance_prompt():
    data = request.json
    prompt = data.get('prompt', '')
    mode   = data.get('mode', 'image')

    type_desc = "image generation (style, lighting, composition, details)" \
        if mode == 'image' else "video generation (motion, camera, mood, scene)"

    body = {
        "model": "gpt-5.4-nano",
        "max_tokens": 200,
        "messages": [{
            "role": "user",
            "content": f"Enhance this prompt for {type_desc}. Reply ONLY with the improved English prompt, no explanation:\n\n{prompt}"
        }]
    }

    try:
        r = requests.post(f"{BASE_URL}/chat/completions",
                          headers=afri_headers(), json=body, timeout=20)
        result = r.json()
        enhanced = result['choices'][0]['message']['content'].strip()
        return jsonify({"enhanced": enhanced})
    except Exception as e:
        return jsonify({"enhanced": prompt})  # fallback: original prompt

# ─── IMAGE GENERATION ─────────────────────────────────────────────────────────
@app.route('/api/image', methods=['POST'])
def generate_image():
    ip = request.remote_addr
    if not check_limit(ip):
        return jsonify({"error": "Limite journalière atteinte. Revenez demain !"}), 429

    data    = request.json
    prompt  = data.get('prompt', '')
    model   = data.get('model', 'flux-2-klein')
    size    = data.get('size', '1024x1024')

    if model == 'flux-2-klein':
        endpoint = f"{BASE_URL}/images/flux"
        body = {"prompt": prompt, "size": size}
    else:
        endpoint = f"{BASE_URL}/images/generations"
        body = {"model": model, "prompt": prompt, "n": 1, "size": size}

    try:
        r = requests.post(endpoint, headers=afri_headers(), json=body, timeout=60)
        result = r.json()
        if not r.ok:
            return jsonify({"error": result.get('error', {}).get('message', str(result))}), r.status_code
        url = result.get('data', [{}])[0].get('url') or result.get('url')
        return jsonify({"url": url, "remaining": get_remaining(ip)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── VIDEO GENERATION ─────────────────────────────────────────────────────────
@app.route('/api/video', methods=['POST'])
def generate_video():
    ip = request.remote_addr
    if not check_limit(ip):
        return jsonify({"error": "Limite journalière atteinte. Revenez demain !"}), 429

    data     = request.json
    prompt   = data.get('prompt', '')
    duration = data.get('duration', 6)

    body = {"model": "sora-2", "prompt": prompt, "duration": duration}

    try:
        r = requests.post(f"{BASE_URL}/videos/generations",
                          headers=afri_headers(), json=body, timeout=120)
        result = r.json()
        if not r.ok:
            return jsonify({"error": result.get('error', {}).get('message', str(result))}), r.status_code

        # Direct URL or async job
        url = result.get('url') or result.get('data', [{}])[0].get('url') if result.get('data') else None
        job_id = result.get('id') if not url else None

        return jsonify({"url": url, "job_id": job_id, "remaining": get_remaining(ip)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── VIDEO POLL ───────────────────────────────────────────────────────────────
@app.route('/api/video/<job_id>', methods=['GET'])
def poll_video(job_id):
    try:
        r = requests.get(f"{BASE_URL}/videos/generations/{job_id}",
                         headers=afri_headers(), timeout=30)
        result = r.json()
        url = result.get('url') or (result.get('data', [{}])[0].get('url') if result.get('data') else None)
        return jsonify({"status": result.get('status', 'processing'), "url": url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── SOUND EFFECTS ────────────────────────────────────────────────────────────
@app.route('/api/sfx', methods=['POST'])
def generate_sfx():
    ip = request.remote_addr
    if not check_limit(ip):
        return jsonify({"error": "Limite journalière atteinte. Revenez demain !"}), 429

    data     = request.json
    prompt   = data.get('prompt', '')
    duration = data.get('duration', 10)

    body = {"text": prompt, "duration_seconds": duration}

    try:
        r = requests.post(f"{BASE_URL}/audio/sound-effects",
                          headers=afri_headers(), json=body, timeout=60)
        if not r.ok:
            return jsonify({"error": r.json().get('error', {}).get('message', 'Erreur API')}), r.status_code
        # Return audio as base64
        import base64
        audio_b64 = base64.b64encode(r.content).decode('utf-8')
        return jsonify({"audio_b64": audio_b64, "remaining": get_remaining(ip)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── TTS ──────────────────────────────────────────────────────────────────────
@app.route('/api/tts', methods=['POST'])
def generate_tts():
    ip = request.remote_addr
    if not check_limit(ip):
        return jsonify({"error": "Limite journalière atteinte. Revenez demain !"}), 429

    data  = request.json
    text  = data.get('text', '')
    voice = data.get('voice', 'nova')
    speed = data.get('speed', 1.0)

    body = {"model": "gpt-audio-1.5", "input": text, "voice": voice, "speed": speed}

    try:
        r = requests.post(f"{BASE_URL}/audio/speech",
                          headers=afri_headers(), json=body, timeout=60)
        if not r.ok:
            return jsonify({"error": r.json().get('error', {}).get('message', 'Erreur API')}), r.status_code
        import base64
        audio_b64 = base64.b64encode(r.content).decode('utf-8')
        return jsonify({"audio_b64": audio_b64, "remaining": get_remaining(ip)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── AFRI VOICE TTS ───────────────────────────────────────────────────────────
@app.route('/api/afri-voice', methods=['POST'])
def generate_afri_voice():
    ip = request.remote_addr
    if not check_limit(ip):
        return jsonify({"error": "Limite journalière atteinte. Revenez demain !"}), 429

    data     = request.json
    text     = data.get('text', '')
    language = data.get('language', 'fr')
    gender   = data.get('gender', 'female')

    body = {"text": text, "language": language, "gender": gender}

    try:
        r = requests.post(f"{BASE_URL}/audio/afri-voice/tts",
                          headers=afri_headers(), json=body, timeout=60)
        if not r.ok:
            return jsonify({"error": r.json().get('error', {}).get('message', 'Erreur API')}), r.status_code
        import base64
        audio_b64 = base64.b64encode(r.content).decode('utf-8')
        return jsonify({"audio_b64": audio_b64, "remaining": get_remaining(ip)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── AFRI VOICE DESIGN ────────────────────────────────────────────────────────
@app.route('/api/voice-design', methods=['POST'])
def generate_voice_design():
    ip = request.remote_addr
    if not check_limit(ip):
        return jsonify({"error": "Limite journalière atteinte. Revenez demain !"}), 429

    data        = request.json
    text        = data.get('text', '')
    description = data.get('description', '')

    body = {"text": text, "voice_description": description}

    try:
        r = requests.post(f"{BASE_URL}/audio/afri-voice/design",
                          headers=afri_headers(), json=body, timeout=60)
        if not r.ok:
            return jsonify({"error": r.json().get('error', {}).get('message', 'Erreur API')}), r.status_code
        import base64
        audio_b64 = base64.b64encode(r.content).decode('utf-8')
        return jsonify({"audio_b64": audio_b64, "remaining": get_remaining(ip)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── RUN ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("🚀 AfriStudio Backend démarré sur http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
# test
