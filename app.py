from flask import Flask, request, render_template, jsonify, session, redirect, url_for, Response
from gtts import gTTS
import whisper
from googletrans import Translator
import requests
import os
import base64
import cv2
import mediapipe as mp
import threading
import time
import json
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'
os.makedirs("static", exist_ok=True)

# -------------------------------
# User Management (Simple in-memory storage)
# -------------------------------
users = {
    'admin@wordwave.com': {
        'password': generate_password_hash('admin123'),
        'name': 'Admin User'
    }
}

def login_required(f):
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# -------------------------------
# Text & Voice Translation Setup
# -------------------------------
stt_model = whisper.load_model("small")
translator = Translator()
HF_TOKENS = [
    "REMOVED",
    "REMOVED",
]

# -------------------------------
# MediaPipe Hands Setup
# -------------------------------
mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
hands = mp_hands.Hands(static_image_mode=False,
                       max_num_hands=1,
                       min_detection_confidence=0.8,
                       min_tracking_confidence=0.8)

# -------------------------------
# Windows SAPI TTS
# -------------------------------
import win32com.client as wincl
speaker = wincl.Dispatch("SAPI.SpVoice")

# Global variables for sign language recognition
mute = False
target_language = "en"
last_gesture_word = ""
recognition_active = False
cap = None
recognition_thread = None
latest_frame_jpeg = None

# -------------------------------
# Gesture → Word Mapping
# -------------------------------
gesture_to_word = {
    "fist": "NO",
    "open": "HELLO",
    "thumbs_up": "YES",
    "thumbs_down": "DISLIKE",
    "victory": "GOODBYE",
    "iloveyou": "LOVE YOU",
    "thankyou": "THANK YOU",
    "welcome": "WELCOME",
    "sarika": "THIS IS SARIKA"
}

# -------------------------------
# Utility Functions
# -------------------------------
def speak_word(word):
    global mute
    if mute:
        return
    try:
        speaker.Speak(word)
    except:
        pass

def _hf_translate(text: str, src_lang: str, tgt_lang: str) -> str | None:
    # Try Helsinki-NLP opus-mt models by src->tgt code
    # e.g., en->hi => Helsinki-NLP/opus-mt-en-hi
    model = f"Helsinki-NLP/opus-mt-{src_lang}-{tgt_lang}"
    for token in HF_TOKENS:
        try:
            resp = requests.post(
                f"https://api-inference.huggingface.co/models/{model}",
                headers={"Authorization": f"Bearer {token}"},
                json={"inputs": text},
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data and "translation_text" in data[0]:
                    return data[0]["translation_text"]
                if isinstance(data, dict) and "error" in data:
                    continue
            else:
                continue
        except Exception:
            continue
    return None

def translate_text(text: str, src_lang: str | None, tgt_lang: str) -> str:
    # Basic normalization/autocorrect (best-effort)
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned

    # Try HF first if we have both codes
    if src_lang and tgt_lang and len(src_lang) <= 5 and len(tgt_lang) <= 5:
        hf = _hf_translate(cleaned, src_lang, tgt_lang)
        if hf:
            return hf

    # Fallback to googletrans
    try:
        detected = None
        if not src_lang:
            try:
                detected = translator.detect(cleaned).lang
            except Exception:
                detected = None
        src = src_lang or detected
        if src:
            # Try HF again with detected code
            hf2 = _hf_translate(cleaned, src, tgt_lang)
            if hf2:
                return hf2
            return translator.translate(cleaned, src=src, dest=tgt_lang).text
        return translator.translate(cleaned, dest=tgt_lang).text
    except Exception:
        return cleaned

def translate_word(word, lang="en", src=None):
    return translate_text(word, src, lang)

# -------------------------------
# Gesture Detection Logic (Landmark-Based)
# -------------------------------
def detect_gesture(hand_landmarks):
    """
    Detect gestures:
    - fist, open, thumbs up/down, victory, I Love You
    """
    tip_ids = [4, 8, 12, 16, 20]
    tips_up = []

    for i, tip_id in enumerate(tip_ids):
        tip_y = hand_landmarks.landmark[tip_id].y
        pip_y = hand_landmarks.landmark[tip_id - 2].y
        tips_up.append(tip_y < pip_y)

    # Thumb direction
    thumb_tip = hand_landmarks.landmark[4]
    thumb_ip = hand_landmarks.landmark[3]
    thumb_up = thumb_tip.y < thumb_ip.y - 0.02
    thumb_down = thumb_tip.y > thumb_ip.y + 0.02

    # Gesture rules
    if tips_up == [False, False, False, False, False]:
        return "fist"
    elif tips_up == [True, True, True, True, True]:
        return "open"
    elif tips_up[0] and not any(tips_up[1:]):
        return "thumbs_up"
    elif thumb_down and not any(tips_up[1:]):
        return "thumbs_down"
    elif tips_up[1] and tips_up[2] and not tips_up[0] and not tips_up[3] and not tips_up[4]:
        return "victory"
    elif tips_up[0] and tips_up[1] and not tips_up[2] and not tips_up[3] and tips_up[4]:
        return "iloveyou"
    else:
        return "open"

# -------------------------------
# Gesture Recognition Thread
# -------------------------------
def gesture_loop():
    global last_gesture_word, recognition_active, cap, latest_frame_jpeg
    while recognition_active:
        if cap is None:
            time.sleep(0.1)
            continue
            
        ret, frame = cap.read()
        if not ret:
            continue
            
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(frame_rgb)
        
        if results.multi_hand_landmarks:
            # Draw skeleton (thin, pretty)
            mp_drawing.draw_landmarks(
                frame,
                results.multi_hand_landmarks[0],
                mp_hands.HAND_CONNECTIONS,
                mp_drawing.DrawingSpec(color=(80, 200, 120), thickness=1, circle_radius=1),
                mp_drawing.DrawingSpec(color=(80, 120, 240), thickness=1)
            )
            # Detect gesture
            gesture = detect_gesture(results.multi_hand_landmarks[0])
            word = gesture_to_word.get(gesture, gesture)
            if word != last_gesture_word:
                translated = translate_word(word, target_language)
                speak_word(translated)
                last_gesture_word = word

        # Encode and store latest frame for streaming
        try:
            ok, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            if ok:
                latest_frame_jpeg = buf.tobytes()
        except:
            pass

        time.sleep(0.05)

# -------------------------------
# Routes
# -------------------------------
@app.route("/")
def index():
    if 'user' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('home'))

@app.route("/login", methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if email in users and check_password_hash(users[email]['password'], password):
            session['user'] = email
            return redirect(url_for('home'))
        else:
            return render_template('login.html', error='Invalid credentials')
    
    return render_template('login.html')

@app.route("/signup", methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        name = request.form.get('name')
        
        if email in users:
            return render_template('signup.html', error='User already exists')
        
        users[email] = {
            'password': generate_password_hash(password),
            'name': name
        }
        session['user'] = email
        return redirect(url_for('home'))
    
    return render_template('signup.html')

# -------------------------------
# Google OAuth (Mocked minimal flow)
# -------------------------------
@app.route("/auth/google")
def google_login():
    # In production, redirect to Google's OAuth 2.0 consent screen.
    # For now, simulate success and go to callback.
    return redirect(url_for('google_callback'))

@app.route("/auth/google/callback")
def google_callback():
    # In production, verify token/userinfo. Here, set a demo user.
    session['user'] = 'google_user@wordwave.com'
    return redirect(url_for('home'))

@app.route("/logout")
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route("/home")
@login_required
def home():
    LANGUAGES = {
        "en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French", "de": "German",
        "it": "Italian", "pt": "Portuguese", "ru": "Russian", "ja": "Japanese", "ko": "Korean",
        "zh": "Chinese", "ar": "Arabic", "tr": "Turkish", "pl": "Polish", "nl": "Dutch"
    }
    return render_template("index.html", languages=LANGUAGES, user=session['user'])

@app.route("/about")
@login_required
def about_page():
    return render_template("about.html")

@app.route("/contact")
@login_required
def contact_page():
    return render_template("contact.html")

@app.route("/help")
@login_required
def help_page():
    return render_template("help.html")

@app.route("/text")
@login_required
def text_page():
    LANGUAGES = {
        "en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French", "de": "German",
        "it": "Italian", "pt": "Portuguese", "ru": "Russian", "ja": "Japanese", "ko": "Korean",
        "zh": "Chinese", "ar": "Arabic", "tr": "Turkish", "pl": "Polish", "nl": "Dutch"
    }
    return render_template("text.html", languages=LANGUAGES, user=session['user'])

@app.route("/text/translate", methods=["POST"])
@login_required
def text_translate():
    LANGUAGES = {
        "en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French", "de": "German",
        "it": "Italian", "pt": "Portuguese", "ru": "Russian", "ja": "Japanese", "ko": "Korean",
        "zh": "Chinese", "ar": "Arabic", "tr": "Turkish", "pl": "Polish", "nl": "Dutch"
    }
    text = request.form.get("text", "")
    src_lang = request.form.get("src_lang") or None
    tgt_lang = request.form.get("tgt_lang", "en")
    translated = translate_text(text, src_lang, tgt_lang) if text else ""
    audio_path = None
    if translated:
        try:
            tts_audio = gTTS(translated, lang=tgt_lang)
            audio_path = "static/output.mp3"
            tts_audio.save(audio_path)
        except Exception:
            audio_path = None
    return render_template("text.html", languages=LANGUAGES, user=session['user'], stt_text=translated, tts_audio=audio_path)

@app.route("/voice")
@login_required
def voice_page():
    LANGUAGES = {
        "en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French", "de": "German",
        "it": "Italian", "pt": "Portuguese", "ru": "Russian", "ja": "Japanese", "ko": "Korean",
        "zh": "Chinese", "ar": "Arabic", "tr": "Turkish", "pl": "Polish", "nl": "Dutch"
    }
    return render_template("voice.html", languages=LANGUAGES, user=session['user'])

@app.route("/sign")
@login_required
def sign_page():
    LANGUAGES = {
        "en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French", "de": "German",
        "it": "Italian", "pt": "Portuguese", "ru": "Russian", "ja": "Japanese", "ko": "Korean",
        "zh": "Chinese", "ar": "Arabic", "tr": "Turkish", "pl": "Polish", "nl": "Dutch"
    }
    return render_template("sign.html", languages=LANGUAGES, user=session['user'])

@app.route("/api/tts", methods=["POST"])
@login_required
def tts():
    text = request.form.get("text")
    tgt_lang = request.form.get("tgt_lang", "en")
    src_lang = request.form.get("src_lang") or None
    if not text:
        return jsonify({"error": "No text provided"}), 400

    translated = translate_text(text, src_lang, tgt_lang)
    tts_audio = gTTS(translated, lang=tgt_lang)
    audio_path = "static/output.mp3"
    tts_audio.save(audio_path)
    speak_word(translated)
    return jsonify({"audio": audio_path, "text": translated})

@app.route("/api/stt", methods=["POST"])
@login_required
def stt():
    audio_data_b64 = request.form.get("audio")
    tgt_lang = request.form.get("tgt_lang", "en")
    src_lang = request.form.get("src_lang") or None

    audio_path = None
    try:
        if "audio" in request.files and request.files["audio"].filename:
            # Prefer uploaded file (e.g., MediaRecorder Blob)
            audio_file = request.files["audio"]
            ext = os.path.splitext(audio_file.filename)[1] or ".webm"
            audio_path = f"static/input{ext}"
            audio_file.save(audio_path)
        elif audio_data_b64:
            # Base64 payload (assume webm from MediaRecorder)
            audio_bytes = base64.b64decode(audio_data_b64)
            audio_path = "static/input.webm"
            with open(audio_path, "wb") as f:
                f.write(audio_bytes)
        else:
            return jsonify({"error": "No audio provided"}), 400

        # Whisper can read via ffmpeg regardless of extension
        result = stt_model.transcribe(audio_path)
    finally:
        # Optional: keep input for debugging; comment next two lines to retain
        # if audio_path and os.path.exists(audio_path):
        #     os.remove(audio_path)
        pass
    text = result.get("text", "")
    translated = translate_text(text, src_lang, tgt_lang)
    tts_audio = gTTS(translated, lang=tgt_lang)
    audio_out_path = "static/output.mp3"
    tts_audio.save(audio_out_path)
    speak_word(translated)
    return jsonify({"audio": audio_out_path, "text": translated})

# Sign Language API endpoints
@app.route("/api/sign/start", methods=["POST"])
@login_required
def start_sign_recognition():
    global recognition_active, cap, recognition_thread
    
    if recognition_active:
        return jsonify({"status": "already_started", "message": "Recognition already active"})
    
    try:
        cap = cv2.VideoCapture(0)
        # Lower resolution for faster processing/less latency
        try:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
        except:
            pass
        if not cap.isOpened():
            return jsonify({"status": "error", "message": "Could not access camera"})
        
        recognition_active = True
        recognition_thread = threading.Thread(target=gesture_loop, daemon=True)
        recognition_thread.start()
        
        return jsonify({"status": "started", "message": "Recognition started successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/api/sign/stop", methods=["POST"])
@login_required
def stop_sign_recognition():
    global recognition_active, cap
    
    recognition_active = False
    if cap:
        cap.release()
        cap = None
    
    return jsonify({"status": "stopped", "message": "Recognition stopped"})

@app.route("/api/sign/stream")
@login_required
def sign_stream():
    def generate():
        while True:
            if not recognition_active:
                time.sleep(0.1)
                continue
            if latest_frame_jpeg is None:
                time.sleep(0.05)
                continue
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + latest_frame_jpeg + b"\r\n")
            time.sleep(0.05)

    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/api/sign/status")
@login_required
def sign_status():
    return jsonify({
        "active": recognition_active,
        "last_word": last_gesture_word,
        "gesture_mappings": gesture_to_word
    })

@app.route("/api/sign/toggle_mute", methods=["POST"])
@login_required
def toggle_mute():
    global mute
    mute = not mute
    return jsonify({"mute": mute})

# ---------------- Run App -----------------
if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
