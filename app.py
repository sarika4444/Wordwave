from flask import Flask, request, render_template
from gtts import gTTS
import whisper
from googletrans import Translator
import os
import base64

app = Flask(__name__)

# Load Whisper model once
stt_model = whisper.load_model("small")
translator = Translator()

# ----------------- Languages (100+ major languages) -----------------
LANGUAGES = {
    "af": "Afrikaans", "sq": "Albanian", "am": "Amharic", "ar": "Arabic", "hy": "Armenian",
    "az": "Azerbaijani", "eu": "Basque", "be": "Belarusian", "bn": "Bengali", "bs": "Bosnian",
    "bg": "Bulgarian", "ca": "Catalan", "ceb": "Cebuano", "ny": "Chichewa", "zh-cn": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)", "co": "Corsican", "hr": "Croatian", "cs": "Czech", "da": "Danish",
    "nl": "Dutch", "en": "English", "eo": "Esperanto", "et": "Estonian", "tl": "Filipino",
    "fi": "Finnish", "fr": "French", "fy": "Frisian", "gl": "Galician", "ka": "Georgian",
    "de": "German", "el": "Greek", "gu": "Gujarati", "ht": "Haitian Creole", "ha": "Hausa",
    "haw": "Hawaiian", "he": "Hebrew", "hi": "Hindi", "hmn": "Hmong", "hu": "Hungarian",
    "is": "Icelandic", "ig": "Igbo", "id": "Indonesian", "ga": "Irish", "it": "Italian",
    "ja": "Japanese", "jw": "Javanese", "kn": "Kannada", "kk": "Kazakh", "km": "Khmer",
    "ko": "Korean", "ku": "Kurdish (Kurmanji)", "ky": "Kyrgyz", "lo": "Lao", "la": "Latin",
    "lv": "Latvian", "lt": "Lithuanian", "lb": "Luxembourgish", "mk": "Macedonian", "mg": "Malagasy",
    "ms": "Malay", "ml": "Malayalam", "mt": "Maltese", "mi": "Maori", "mr": "Marathi",
    "mn": "Mongolian", "my": "Myanmar (Burmese)", "ne": "Nepali", "no": "Norwegian", "or": "Odia",
    "ps": "Pashto", "fa": "Persian", "pl": "Polish", "pt": "Portuguese", "pa": "Punjabi",
    "ro": "Romanian", "ru": "Russian", "sm": "Samoan", "gd": "Scots Gaelic", "sr": "Serbian",
    "st": "Sesotho", "sn": "Shona", "sd": "Sindhi", "si": "Sinhala", "sk": "Slovak",
    "sl": "Slovenian", "so": "Somali", "es": "Spanish", "su": "Sundanese", "sw": "Swahili",
    "sv": "Swedish", "tg": "Tajik", "ta": "Tamil", "tt": "Tatar", "te": "Telugu",
    "th": "Thai", "tr": "Turkish", "tk": "Turkmen", "uk": "Ukrainian", "ur": "Urdu",
    "ug": "Uyghur", "uz": "Uzbek", "vi": "Vietnamese", "cy": "Welsh", "xh": "Xhosa",
    "yi": "Yiddish", "yo": "Yoruba", "zu": "Zulu"
}

# ---------------- Routes -----------------
@app.route("/")
def index():
    return render_template("index.html", tts_audio=None, stt_text=None, error=None, languages=LANGUAGES)

# ---------------- Text → Translate → Speech -----------------
@app.route("/tts", methods=["POST"])
def tts():
    text = request.form.get("text")
    src_lang = request.form.get("src_lang", "")
    tgt_lang = request.form.get("tgt_lang", "en")

    if not text:
        return render_template("index.html", error="No text provided", languages=LANGUAGES)

    try:
        # Translate
        translated = translator.translate(text, src=src_lang if src_lang else "auto", dest=tgt_lang).text

        # Generate speech
        tts_audio = gTTS(translated, lang=tgt_lang)
        audio_path = "static/output.mp3"
        tts_audio.save(audio_path)

        return render_template("index.html", tts_audio=audio_path, stt_text=translated, error=None, languages=LANGUAGES)
    except Exception as e:
        return render_template("index.html", error=f"Translation/TTS Error: {str(e)}", languages=LANGUAGES)

# ---------------- Voice → Translate → Speech -----------------
@app.route("/stt", methods=["POST"])
def stt():
    audio_data = request.form.get("audio")

    if audio_data:
        try:
            audio_bytes = base64.b64decode(audio_data)
            audio_path = "static/input.wav"
            with open(audio_path, "wb") as f:
                f.write(audio_bytes)
        except Exception as e:
            return render_template("index.html", error=f"Audio decode error: {str(e)}", languages=LANGUAGES)
    elif "audio" in request.files:
        audio_file = request.files["audio"]
        audio_path = "static/input.wav"
        audio_file.save(audio_path)
    else:
        return render_template("index.html", error="No audio provided", languages=LANGUAGES)

    tgt_lang = request.form.get("tgt_lang", "en")

    try:
        # Transcribe voice
        result = stt_model.transcribe(audio_path)
        text = result.get("text", "")

        # Translate to target language
        translated = translator.translate(text, dest=tgt_lang).text

        # Convert translated text to speech
        tts_audio = gTTS(translated, lang=tgt_lang)
        audio_out_path = "static/output.mp3"
        tts_audio.save(audio_out_path)

        return render_template("index.html", tts_audio=audio_out_path, stt_text=translated, error=None, languages=LANGUAGES)
    except Exception as e:
        return render_template("index.html", error=f"Voice Translation Error: {str(e)}", languages=LANGUAGES)

# ---------------- Run App -----------------
if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    app.run(debug=True)
