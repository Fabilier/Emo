#!/usr/bin/env python3
"""Cerveau d'Emo : micro -> texte -> LLM -> réponse parlée + émotion.

Prérequis : Raspberry Pi, alsa-utils (arecord, aplay), pip install requests faster-whisper,
            piper (binaire + voix FR, variables PIPER_BIN et PIPER_VOICE).
Configuration (.env à la racine de Code/, jamais commité) : voir .env.example.
Fournisseur interchangeable : tout endpoint compatible OpenAI (Gemini, Mistral, Groq...).
Test sans matériel : python3 brain.py "Salut Emo"
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import wave
from array import array

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EMOTIONS = ('happy', 'sad', 'angry', 'excited', 'dizzy', 'blink')
FORMAT = (
    "Réponds en français, en une seule phrase de 15 mots maximum, droit au but, sans formule de politesse. "
    'Réponds uniquement en JSON : {"texte": "...", "emotion": "<' + '|'.join(EMOTIONS) + '>"}.'
)
PERSONAS = {
    'gentil': "Tu es Emo, un petit robot compagnon amical et chaleureux. ",
    'piquant': (
        "Tu es Emo, un petit robot compagnon à l'esprit vif : humour sec, ironie légère, répliques "
        "qui piquent avec tendresse, un brin rebelle et jamais méchant. Pas de vulgarité, aucune "
        "moquerie sur l'apparence, l'origine ou la religion, pas de prise de position politique. "
    ),
}


def system_prompt():
    """Personnalité choisie par EMO_PERSONA (gentil par défaut)."""
    return PERSONAS.get(os.environ.get('EMO_PERSONA', 'gentil'), PERSONAS['gentil']) + FORMAT


def load_env(path=os.path.join(BASE_DIR, '.env')):
    """Charge .env sans écraser les variables déjà définies."""
    if not os.path.exists(path):
        return
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
session = requests.Session()  # connexion gardée ouverte : pas de poignée de main TLS à chaque question


def enabled():
    return bool(os.environ.get('LLM_API_KEY'))


def parse_reply(content):
    """Extrait (texte, emotion) d'une réponse LLM ; tolère les blocs ```json."""
    content = content.strip().strip('`')
    if content.startswith('json'):
        content = content[4:]
    try:
        data = json.loads(content)
        text, emo = str(data.get('texte', '')).strip(), data.get('emotion')
    except (ValueError, AttributeError):
        text, emo = content, None
    return shorten(text), emo if emo in EMOTIONS else 'happy'


def shorten(text, limit=None):
    """Filet de sécurité : si le LLM bavarde, on coupe à la fin de phrase avant `limit` caractères."""
    limit = limit or int(os.environ.get('MAX_REPLY_CHARS', '120'))
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind('. '), cut.rfind('! '), cut.rfind('? '))
    return cut[:end + 1] if end > 20 else cut.rsplit(' ', 1)[0] + '...'


def ask(user_text, history=None):
    """Interroge le LLM. Retourne (texte, emotion)."""
    url = os.environ.get('LLM_BASE_URL', 'https://generativelanguage.googleapis.com/v1beta/openai').rstrip('/')
    messages = [{'role': 'system', 'content': system_prompt()}, *(history or []),
                {'role': 'user', 'content': user_text}]
    body = {'model': os.environ.get('LLM_MODEL', 'gemini-2.5-flash-lite'), 'messages': messages,
            'response_format': {'type': 'json_object'}, 'max_tokens': 80}
    if os.environ.get('LLM_REASONING_EFFORT'):  # ex. none sur Gemini : pas de phase de réflexion
        body['reasoning_effort'] = os.environ['LLM_REASONING_EFFORT']
    r = session.post(
        url + '/chat/completions', timeout=20,
        headers={'Authorization': 'Bearer ' + os.environ['LLM_API_KEY']},
        json=body)
    r.raise_for_status()
    return parse_reply(r.json()['choices'][0]['message']['content'])


def record(path, max_s=8.0, silence_s=0.8, wait_s=4.0):
    """Enregistre jusqu'à `silence_s` de silence après la parole (au lieu de 5 s fixes).
    Retourne False si personne n'a parlé dans les `wait_s` premières secondes."""
    thr = int(os.environ.get('SILENCE_RMS', '500'))
    rate, chunk = 16000, 1600  # morceaux de 0,1 s
    proc = subprocess.Popen(['arecord', '-q', '-f', 'S16_LE', '-r', str(rate), '-c', '1', '-t', 'raw'],
                            stdout=subprocess.PIPE)
    frames, spoke, quiet, elapsed = [], False, 0.0, 0.0
    try:
        while elapsed < max_s:
            data = proc.stdout.read(chunk * 2)
            if len(data) < chunk * 2:
                break
            samples = array('h', data)
            rms = (sum(x * x for x in samples) / len(samples)) ** 0.5
            elapsed += 0.1
            frames.append(data)
            if rms > thr:
                spoke, quiet = True, 0.0
            elif spoke:
                quiet += 0.1
                if quiet >= silence_s:
                    break
            elif elapsed >= wait_s:
                return False
    finally:
        proc.terminate()
        proc.wait()
    if not spoke:
        return False
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b''.join(frames))
    return True


def listen():
    """Enregistre (arrêt au silence) puis transcrit (STT_PROVIDER=local par défaut, ou api)."""
    with tempfile.NamedTemporaryFile(suffix='.wav') as tmp:
        if not record(tmp.name):
            return ''
        if os.environ.get('STT_PROVIDER', 'local') == 'api':
            return transcribe_api(tmp.name)
        segments, _ = _whisper().transcribe(tmp.name, language='fr', beam_size=1)
        return ' '.join(s.text.strip() for s in segments).strip()


def transcribe_api(path):
    """Transcription cloud via endpoint /audio/transcriptions (Mistral Voxtral par défaut).
    L'audio quitte le Pi : à réserver au POC ou à un fournisseur UE."""
    base = os.environ.get('STT_BASE_URL', 'https://api.mistral.ai/v1').rstrip('/')
    key = os.environ.get('STT_API_KEY') or os.environ['LLM_API_KEY']
    with open(path, 'rb') as f:
        r = session.post(base + '/audio/transcriptions', timeout=20,
                          headers={'Authorization': 'Bearer ' + key},
                          data={'model': os.environ.get('STT_MODEL', 'voxtral-mini-latest'),
                                'language': 'fr'},
                          files={'file': ('audio.wav', f, 'audio/wav')})
    r.raise_for_status()
    return r.json().get('text', '').strip()


_model = None


def _whisper():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(os.environ.get('WHISPER_MODEL', 'tiny'), compute_type='int8')
    return _model


def speak(text, stop=None):
    """Synthèse locale avec piper, lue par aplay. `stop` (threading.Event) interrompt."""
    piper, voice = os.environ.get('PIPER_BIN', 'piper'), os.environ.get('PIPER_VOICE')
    if not voice or not text:
        return
    with tempfile.NamedTemporaryFile(suffix='.wav') as tmp:
        subprocess.run([piper, '--model', voice, '--output_file', tmp.name],
                       input=text.encode(), check=True, capture_output=True)
        proc = subprocess.Popen(['aplay', '-q', tmp.name])
        while proc.poll() is None:
            if stop is not None and stop.wait(0.05):
                proc.terminate()
                break
        proc.wait()


def preload():
    """Charge Whisper en tâche de fond au démarrage (le 1er échange ne paie plus le chargement)."""
    if enabled() and os.environ.get('STT_PROVIDER', 'local') == 'local':
        threading.Thread(target=_whisper, daemon=True).start()


if __name__ == '__main__':
    if not enabled():
        sys.exit('LLM_API_KEY manquant (voir .env.example)')
    try:
        print(ask(' '.join(sys.argv[1:]) or 'Bonjour Emo !'))
    except (requests.RequestException, KeyError, ValueError) as e:
        sys.exit(f'Erreur LLM : {e}')
