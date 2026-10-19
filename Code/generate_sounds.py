#!/usr/bin/env python3
"""Génère les sons d'Emo (WAV 16 bits mono, 22,05 kHz) dans ./sound.

Prérequis : python3, numpy (pip install numpy).
Exécution : python3 generate_sounds.py
Les sons sont synthétisés ici : aucun droit d'auteur, aucun téléchargement.
"""
import os
import sys
import wave

import numpy as np

SR = 22050
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sound")


def tone(freq, dur, vol=0.5, shape="sine"):
    """Note avec fréquence fixe ou courbe de fréquence (tableau) + enveloppe."""
    n = int(SR * dur)
    f = np.full(n, freq, dtype=float) if np.isscalar(freq) else np.interp(
        np.linspace(0, 1, n), np.linspace(0, 1, len(freq)), freq)
    phase = 2 * np.pi * np.cumsum(f) / SR
    if shape == "square":
        w = np.sign(np.sin(phase)) * 0.6 + np.sin(phase) * 0.4
    elif shape == "saw":
        w = 2 * ((phase / (2 * np.pi)) % 1) - 1
    else:
        w = np.sin(phase) + 0.25 * np.sin(2 * phase)
    att, rel = min(int(0.01 * SR), n // 4), min(int(0.05 * SR), n // 2)
    env = np.ones(n)
    env[:att] = np.linspace(0, 1, att)
    env[-rel:] = np.linspace(1, 0, rel)
    return vol * w * env / 1.25


def gap(dur):
    return np.zeros(int(SR * dur))


def save(name, signal):
    peak = np.max(np.abs(signal)) or 1.0
    data = (signal / max(peak, 1.0) * 32000).astype(np.int16)
    path = os.path.join(OUT, name + ".wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())
    print(f"{path} ({len(data) / SR:.1f}s)")


def main():
    os.makedirs(OUT, exist_ok=True)
    # happy : petit gazouillis montant
    save("happy", np.concatenate([
        tone(660, 0.09), tone(880, 0.09), tone(1100, 0.09), gap(0.03),
        tone([900, 1400], 0.15), tone([1400, 1000], 0.12), tone(1320, 0.2)]))
    # excited : trilles rapides
    save("excited", np.concatenate(
        [tone([700 + 120 * k, 1300 + 120 * k], 0.07) for k in range(6)]
        + [tone([1500, 2000, 1500], 0.25)]))
    # sad : glissando descendant, vibrato lent
    t = np.linspace(0, 1, int(SR * 0.9))
    sad_f = np.linspace(600, 220, t.size) + 15 * np.sin(2 * np.pi * 5 * t)
    save("sad", np.concatenate([tone(sad_f, 0.9, 0.5), gap(0.1),
                                tone([300, 180], 0.5, 0.35)]))
    # angry : grondement saturé
    t = np.linspace(0, 1, int(SR * 0.8))
    growl = 110 + 25 * np.sin(2 * np.pi * 18 * t)
    save("angry", np.concatenate([
        np.clip(tone(growl, 0.8, 0.9, "saw") * 1.8, -0.8, 0.8),
        tone([300, 150], 0.25, 0.6, "square")]))
    # dizzy : sirène qui tangue
    t = np.linspace(0, 1, int(SR * 1.2))
    save("dizzy", tone(700 + 350 * np.sin(2 * np.pi * 3.5 * t) * (1 - 0.5 * t),
                       1.2, 0.5))
    # bootup : jingle de démarrage
    save("bootup", np.concatenate([
        tone(392, 0.12), tone(523, 0.12), tone(659, 0.12), tone(784, 0.12),
        tone([784, 1047], 0.15), tone(1047, 0.35)]))
    # blink : bip discret
    save("blink", tone([1200, 1600], 0.06, 0.35))


if __name__ == "__main__":
    try:
        main()
    except OSError as e:
        sys.exit(f"Erreur d'écriture : {e}")
