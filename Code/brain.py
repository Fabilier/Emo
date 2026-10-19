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
    r = requests.post(
        url + '/chat/completions', timeout=20,
        headers={'Authorization': 'Bearer ' + os.environ['LLM_API_KEY']},
        json={'model': os.environ.get('LLM_MODEL', 'gemini-2.5-flash'), 'messages': messages,
              'response_format': {'type': 'json_object'}, 'max_tokens': 80})
    r.raise_for_status()
    return parse_reply(r.json()['choices'][0]['message']['content'])


def listen(seconds=5):
    """Enregistre le micro puis transcrit en local (faster-whisper, audio non envoyé au cloud)."""
    from faster_whisper import WhisperModel
    with tempfile.NamedTemporaryFile(suffix='.wav') as tmp:
        subprocess.run(['arecord', '-q', '-f', 'S16_LE', '-r', '16000', '-d', str(seconds), tmp.name],
                       check=True)
        model = _whisper()
        segments, _ = model.transcribe(tmp.name, language='fr')
        return ' '.join(s.text.strip() for s in segments).strip()


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


if __name__ == '__main__':
    if not enabled():
        sys.exit('LLM_API_KEY manquant (voir .env.example)')
    try:
        print(ask(' '.join(sys.argv[1:]) or 'Bonjour Emo !'))
    except (requests.RequestException, KeyError, ValueError) as e:
        sys.exit(f'Erreur LLM : {e}')
