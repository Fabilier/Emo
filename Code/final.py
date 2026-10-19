#!/usr/bin/env python3
"""Emo, robot compagnon : écran, servos, capteurs et sons.

Prérequis : Raspberry Pi, adafruit-circuitpython-servokit, RPi.GPIO, spidev, Pillow, alsa-utils (aplay).
Sons : python3 generate_sounds.py (une fois), dossier ./sound.
Exécution : python3 final.py   (Ctrl+C pour quitter proprement)
"""
import logging
import os
import queue
import subprocess
import threading
import time
from random import choice, randint

import RPi.GPIO as GPIO
from adafruit_servokit import ServoKit
from PIL import Image

from lib import LCD_2inch

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

try:
    import brain  # nécessite `requests` ; sans lui Emo fonctionne sans conversation
except ImportError as e:
    brain = None
    logging.warning('conversation désactivée : %s', e)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EMOTIONS_DIR = os.path.join(BASE_DIR, 'emotions')
SOUND_DIR = os.path.join(BASE_DIR, 'sound')


# Capteurs
TOUCH_PIN = 17
VIBRATION_PIN = 22
TOUCH_COOLDOWN = 1.5       # s min entre deux réactions
VIBRATION_COOLDOWN = 3.0
IDLE_BLINK_EVERY = 3       # une animation de clignement toutes les N boucles neutres

# Réactions au choc
SHOCK_EMOTIONS = ['angry', 'sad', 'excited', 'dizzy']

GPIO.setmode(GPIO.BCM)
GPIO.setup(TOUCH_PIN, GPIO.IN)
GPIO.setup(VIBRATION_PIN, GPIO.IN)

kit = ServoKit(channels=16)
servoR = kit.servo[5]   # bras droit, 0 = bas
servoL = kit.servo[11]  # bras gauche, 180 = bas
servoB = kit.servo[13]  # base, 90 = centre

events = queue.Queue()
stop = threading.Event()        # interrompt l'animation en cours
shutdown = threading.Event()    # arrêt du programme
disp_lock = threading.Lock()    # un seul accès SPI à la fois

disp = LCD_2inch.LCD_2inch()
disp.Init()


def count_frames(name):
    """Nombre réel d'images d'une émotion (évite les décalages avec le disque)."""
    d = os.path.join(EMOTIONS_DIR, name)
    return len([f for f in os.listdir(d) if f.startswith('frame') and f.endswith('.png')])


def load_frames(name):
    """Charge toutes les images en mémoire une fois (écran plus fluide)."""
    frames = []
    for i in range(count_frames(name)):
        try:
            frames.append(Image.open(os.path.join(EMOTIONS_DIR, name, f'frame{i}.png')).convert('RGB'))
        except OSError as e:
            logging.warning('image %s/%d illisible : %s', name, i, e)
    return frames


FRAMES = {n: load_frames(n) for n in os.listdir(EMOTIONS_DIR)
          if os.path.isdir(os.path.join(EMOTIONS_DIR, n)) and n not in ('sleep', 'bootup')}


def interruptible_sleep(duration):
    """Dort en s'arrêtant dès que `stop` est levé. Retourne True si interrompu."""
    return stop.wait(duration)


# ---------- Affichage et son ----------

def show(name, repeat=1):
    for _ in range(repeat):
        for frame in FRAMES[name]:
            if stop.is_set():
                return
            with disp_lock:
                disp.ShowImage(frame)


def sound(name):
    path = os.path.join(SOUND_DIR, name + '.wav')
    if not os.path.exists(path):
        return
    try:
        proc = subprocess.Popen(['aplay', '-q', path])
    except OSError as e:
        logging.warning('aplay indisponible : %s', e)
        return
    while proc.poll() is None:
        if stop.wait(0.05):
            proc.terminate()
            break
    proc.wait()


# ---------- Servos ----------

def servo_med():
    servoR.angle = servoL.angle = servoB.angle = 90


def servo_down():
    servoR.angle, servoL.angle, servoB.angle = 0, 180, 90


def sweep(servo, start, end, delay, step=1):
    """Déplace un servo en s'arrêtant si `stop` est levé."""
    for a in range(start, end, step if end > start else -step):
        if stop.is_set():
            return
        servo.angle = a
        time.sleep(delay)


def baserotate(reference, change, delay):
    sweep(servoB, reference, reference + change, delay)
    sweep(servoB, reference + change, reference - change, delay)
    sweep(servoB, reference - change, reference, delay)


def hands(start, end, delay):
    """Bras de `start` à `end` (degrés côté droit), le gauche en miroir."""
    step = 1 if end > start else -1
    for i in range(start, end, step):
        if stop.is_set():
            return
        servoR.angle = i
        servoL.angle = 180 - i
        time.sleep(delay)


def rotate(start, end, delay):
    hands(start, end, delay)
    hands(end, start, delay)


def happy():
    servo_med()
    for _ in range(5):
        for i in range(120):
            if stop.is_set():
                return
            if i <= 30:
                servoR.angle, servoL.angle, servoB.angle = 90 + i, 90 - i, 90 - i
            elif i <= 90:
                servoR.angle, servoL.angle, servoB.angle = 150 - i, i + 30, i + 30
            else:
                servoR.angle, servoL.angle, servoB.angle = i - 30, 210 - i, 210 - i
            time.sleep(0.004)


def angry():
    servo_down()
    for _ in range(5):
        baserotate(90, randint(10, 30), 0.01)


def sad():
    servo_down()
    for i in range(60):
        if stop.is_set():
            return
        servoB.angle = 90 - i if i <= 15 else (60 + i if i <= 45 else 150 - i)
        time.sleep(0.09)


def excited():
    servo_down()
    for i in range(120):
        if stop.is_set():
            return
        servoB.angle = 90 - i if i <= 30 else (i + 30 if i <= 90 else 210 - i)
        time.sleep(0.01)


def dizzy():
    servo_med()
    for i in range(80):
        if stop.is_set():
            return
        servoB.angle = 90 + (25 if i % 2 else -25) * (1 - i / 80)
        time.sleep(0.05)


def blink():
    servo_down()


EMOTION_MOVES = {'happy': happy, 'angry': angry, 'sad': sad,
                 'excited': excited, 'dizzy': dizzy, 'blink': blink}


# ---------- Capteurs ----------

def check_sensors():
    """Surveille toucher et vibration ; un seul événement en attente à la fois."""
    last_touch = last_vib = 0.0
    touch_prev = False
    while not shutdown.is_set():
        now = time.monotonic()
        touched = GPIO.input(TOUCH_PIN) == GPIO.HIGH
        if touched and not touch_prev and now - last_touch > TOUCH_COOLDOWN and events.empty():
            last_touch = now
            events.put('talk' if brain and brain.enabled() else 'happy')
        touch_prev = touched
        if GPIO.input(VIBRATION_PIN) == GPIO.HIGH and now - last_vib > VIBRATION_COOLDOWN and events.empty():
            last_vib = now
            events.put(choice(SHOCK_EMOTIONS))
        shutdown.wait(0.05)


# ---------- Orchestration ----------

def run_parallel(*targets):
    """Lance les cibles en parallèle ; relève la première exception d'un worker après le join."""
    errors = []

    def runner(fn, args):
        try:
            fn(*args)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=runner, args=(t, a), daemon=True) for t, a in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise errors[0]


def safe(fn, *args):
    """Une erreur d'affichage ou de servo est journalisée, Emo continue."""
    try:
        fn(*args)
    except Exception as e:
        logging.warning('%s a échoué : %s', fn.__name__, e)


def bootup():
    run_parallel((show, ('bootup3',)), (sound, ('bootup',)))
    run_parallel((show, ('blink2', 3)), (rotate, (0, 150, 0.005)),
                 (baserotate, (90, 45, 0.01)))


def play_emotion(name):
    logging.info('émotion : %s', name)
    run_parallel((show, (name, 4)), (sound, (name,)), (EMOTION_MOVES[name], ()))


def think(ev):
    """Animation de réflexion tant que `ev` n'est pas levé."""
    while not ev.is_set() and not stop.is_set():
        for frame in FRAMES['blink2']:
            if ev.is_set() or stop.is_set():
                return
            with disp_lock:
                disp.ShowImage(frame)


def talk(history=[]):
    """Conversation : écoute, LLM, puis réponse parlée avec l'émotion choisie."""
    try:
        threading.Thread(target=sound, args=('blink',), daemon=True).start()  # bip : je t'écoute
        run_parallel((show, ('neutral', 1)))
        heard = brain.listen()
        if not heard:
            return
        logging.info('entendu : %s', heard)
        done = threading.Event()
        thinker = threading.Thread(target=think, args=(done,), daemon=True)
        thinker.start()
        try:
            reply, emo = brain.ask(heard, history)
        finally:
            done.set()
            thinker.join()
        history += [{'role': 'user', 'content': heard}, {'role': 'assistant', 'content': reply}]
        del history[:-6]
        run_parallel((show, (emo, 2)), (brain.speak, (reply, stop)), (EMOTION_MOVES[emo], ()))
    except Exception as e:  # réseau, micro, voix : Emo ne doit jamais planter
        logging.warning('conversation impossible : %s', e)
        play_emotion('sad')


def idle(cycle):
    """Une boucle d'attente ; s'interrompt dès qu'un événement arrive."""
    face = 'blink2' if cycle % IDLE_BLINK_EVERY == 0 else 'neutral'
    run_parallel((show, (face, 2)), (baserotate, (90, 60, 0.02)))


def main():
    threading.Thread(target=check_sensors, daemon=True).start()
    if brain:
        brain.preload()
    safe(bootup)
    cycle = 0
    while True:
        try:
            name = events.get_nowait()
        except queue.Empty:
            name = None
        if name == 'talk':
            stop.clear()
            talk()
            servo_down()
            continue
        if name in EMOTION_MOVES:
            stop.clear()
            safe(play_emotion, name)
            servo_down()
            continue
        # on interrompt l'attente dès qu'un événement arrive
        stop.clear()
        cycle += 1
        idle_thread = threading.Thread(target=safe, args=(idle, cycle), daemon=True)
        idle_thread.start()
        while idle_thread.is_alive():
            if not events.empty():
                stop.set()
            idle_thread.join(0.05)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logging.info('arrêt demandé')
    finally:
        shutdown.set()
        stop.set()
        try:
            servo_down()
            disp.module_exit()
        except Exception as e:
            logging.warning('nettoyage : %s', e)
        GPIO.cleanup()
