from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import base64
import os
from collections import defaultdict
from datetime import date

app = Flask(__name__, static_folder='.')
CORS(app)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
API_KEY     = "sk-afri-cbdd588d618d43e497791c9975734d27"
BASE_URL    = "https://build.lewisnote.com/v1"
DAILY_LIMIT = 5

# ─── RATE LIMIT ───────────────────────────────────────────────────────────────
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

def headers_json():
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

# ─── FRONTEND ─────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# ─── CREDITS ──────────────────────────────────────────────────────────────────
@app.route('/api/remaining')
def remaining():
    ip = request.remote_addr
    return jsonify({"remaining": get_remaining(ip), "limit": DAILY_LIMIT})

# ─── ENHANCE PROMPT ───────────────────────────────────────────────────────────
@app.route('/api/enhance', methods=['POST'])
def enhance_prompt():
    data   = request.get_json(force=True)
    prompt = data.get('prompt', '')
    mode   = data.get('mode', 'image')
    lang   = data.get('lang', 'fr')

    lang_names = {
        'fr':'French','fon':'Fon','yo':'Yoruba','ha':'Hausa',
        'sw':'Swahili','am':'Amharic','pt':'Portuguese','en':'English',
        'ar':'Arabic','wo':'Wolof','tw':'Twi'
    }
    src_lang = lang_names.get(lang, 'French')

    if mode == 'image':
        instruction = (
            f"The following prompt is written in {src_lang}. "
            "Translate it to English and enhance it for AI image generation "
            "(add visual style, lighting, composition, mood, camera details). "
            "Reply ONLY with the final English prompt, nothing else."
        )
    else:
        instruction = (
            f"The following prompt is written in {src_lang}. "
            "Translate it to English and enhance it for AI sound effect generation "
            "(add acoustic details, ambiance, instruments, texture). "
            "Reply ONLY with the final English prompt, nothing else."
        )

    body = {
        "model": "gpt-5.4-nano",
        "max_tokens": 250,
        "messages": [{"role": "user", "content": f"{instruction}\n\nPrompt: {prompt}"}]
    }

    try:
        r = requests.post(f"{BASE_URL}/chat/completions",
                          headers=headers_json(), json=body, timeout=20)
        result = r.json()
        enhanced = result['choices'][0]['message']['content'].strip()
        return jsonify({"enhanced": enhanced})
    except Exception:
        return jsonify({"enhanced": prompt})

# ─── IMAGE GENERATION ─────────────────────────────────────────────────────────
@app.route('/api/image', methods=['POST'])
def generate_image():
    ip = request.remote_addr
    if not check_limit(ip):
        return jsonify({"error": "Limite journalière atteinte. Revenez demain !"}), 429

    data   = request.get_json(force=True)
    prompt = data.get('prompt', '').strip()
    model  = data.get('model', 'flux-2-klein')
    size   = data.get('size', '1024x1024')

    if not prompt:
        return jsonify({"error": "Le prompt est vide."}), 400

    try:
        if model == 'gpt-image-1.5':
            body = {
                "model": "gpt-image-1.5",
                "prompt": prompt,
                "n": 1,
                "size": size,
                "quality": data.get('quality', 'medium'),
                "output_format": "png"
            }
            r = requests.post(f"{BASE_URL}/images/generations",
                              headers=headers_json(), json=body, timeout=90)
        else:
            # flux-2-klein: width + height séparés, pas de size string
            parts = size.split('x') if 'x' in size else ['1024', '1024']
            body = {
                "prompt": prompt,
                "width": int(parts[0]),
                "height": int(parts[1]),
                "steps": 25
            }
            r = requests.post(f"{BASE_URL}/images/flux",
                              headers=headers_json(), json=body, timeout=90)

        if not r.ok:
            try:
                err = r.json().get('error', {})
                msg = err.get('message', str(err)) if isinstance(err, dict) else str(err)
            except Exception:
                msg = r.text[:300]
            return jsonify({"error": msg}), r.status_code

        result = r.json()

        # Cherche l'URL dans les formats possibles
        url = None
        if result.get('data') and len(result['data']) > 0:
            url = result['data'][0].get('url') or result['data'][0].get('b64_json')
        if not url:
            url = result.get('url') or result.get('image_url')

        if not url:
            return jsonify({"error": f"Réponse inattendue: {str(result)[:300]}"}), 500

        # Convertir base64 en data URL si nécessaire
        if url and not url.startswith('http') and not url.startswith('data:'):
            url = f"data:image/png;base64,{url}"

        return jsonify({"url": url, "remaining": get_remaining(ip)})

    except requests.Timeout:
        return jsonify({"error": "Timeout — l'API prend trop de temps."}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── TTS ──────────────────────────────────────────────────────────────────────
@app.route('/api/tts', methods=['POST'])
def generate_tts():
    ip = request.remote_addr
    if not check_limit(ip):
        return jsonify({"error": "Limite journalière atteinte. Revenez demain !"}), 429

    data  = request.get_json(force=True)
    text  = data.get('text', '').strip()
    voice = data.get('voice', 'nova')
    speed = float(data.get('speed', 1.0))

    if not text:
        return jsonify({"error": "Le texte est vide."}), 400

    body = {"model": "gpt-audio-1.5", "input": text, "voice": voice, "speed": speed}

    try:
        r = requests.post(f"{BASE_URL}/audio/speech",
                          headers=headers_json(), json=body, timeout=60)
        if not r.ok:
            try:
                msg = r.json().get('error', {}).get('message', r.text[:200])
            except Exception:
                msg = r.text[:200]
            return jsonify({"error": msg}), r.status_code

        return jsonify({
            "audio_b64": base64.b64encode(r.content).decode('utf-8'),
            "remaining": get_remaining(ip)
        })
    except requests.Timeout:
        return jsonify({"error": "Timeout TTS."}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── AFRI VOICE TTS ───────────────────────────────────────────────────────────
@app.route('/api/afri-voice', methods=['POST'])
def generate_afri_voice():
    ip = request.remote_addr
    if not check_limit(ip):
        return jsonify({"error": "Limite journalière atteinte. Revenez demain !"}), 429

    data     = request.get_json(force=True)
    text     = data.get('text', '').strip()
    language = data.get('language', 'fr')
    gender   = data.get('gender', 'female')

    if not text:
        return jsonify({"error": "Le texte est vide."}), 400

    body = {"text": text, "language": language, "gender": gender}

    try:
        r = requests.post(f"{BASE_URL}/audio/afri-voice/tts",
                          headers=headers_json(), json=body, timeout=60)
        if not r.ok:
            try:
                msg = r.json().get('error', {}).get('message', r.text[:200])
            except Exception:
                msg = r.text[:200]
            return jsonify({"error": msg}), r.status_code

        return jsonify({
            "audio_b64": base64.b64encode(r.content).decode('utf-8'),
            "remaining": get_remaining(ip)
        })
    except requests.Timeout:
        return jsonify({"error": "Timeout Afri Voice."}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── AFRI VOICE DESIGN ────────────────────────────────────────────────────────
@app.route('/api/voice-design', methods=['POST'])
def generate_voice_design():
    ip = request.remote_addr
    if not check_limit(ip):
        return jsonify({"error": "Limite journalière atteinte. Revenez demain !"}), 429

    data        = request.get_json(force=True)
    text        = data.get('text', '').strip()
    description = data.get('description', '').strip()

    if not text or not description:
        return jsonify({"error": "Texte et description requis."}), 400

    body = {"text": text, "voice_description": description}

    try:
        r = requests.post(f"{BASE_URL}/audio/afri-voice/design",
                          headers=headers_json(), json=body, timeout=60)
        if not r.ok:
            try:
                msg = r.json().get('error', {}).get('message', r.text[:200])
            except Exception:
                msg = r.text[:200]
            return jsonify({"error": msg}), r.status_code

        return jsonify({
            "audio_b64": base64.b64encode(r.content).decode('utf-8'),
            "remaining": get_remaining(ip)
        })
    except requests.Timeout:
        return jsonify({"error": "Timeout Voice Design."}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── SOUND EFFECTS ────────────────────────────────────────────────────────────
@app.route('/api/sfx', methods=['POST'])
def generate_sfx():
    ip = request.remote_addr
    if not check_limit(ip):
        return jsonify({"error": "Limite journalière atteinte. Revenez demain !"}), 429

    data     = request.get_json(force=True)
    prompt   = data.get('prompt', '').strip()
    duration = int(data.get('duration', 10))

    if not prompt:
        return jsonify({"error": "Le prompt est vide."}), 400

    body = {"text": prompt, "duration_seconds": duration}

    try:
        r = requests.post(f"{BASE_URL}/audio/sound-effects",
                          headers=headers_json(), json=body, timeout=90)
        if not r.ok:
            try:
                msg = r.json().get('error', {}).get('message', r.text[:200])
            except Exception:
                msg = r.text[:200]
            return jsonify({"error": msg}), r.status_code

        return jsonify({
            "audio_b64": base64.b64encode(r.content).decode('utf-8'),
            "remaining": get_remaining(ip)
        })
    except requests.Timeout:
        return jsonify({"error": "Timeout SFX."}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── RUN ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 AfriStudio backend sur http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
