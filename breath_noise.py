# -*- coding: utf-8 -*-
import math
import random
import signal
import struct
import sys
import time
import wave
from pathlib import Path

import pygame

RUN=True
def stop(a,b):
    global RUN
    RUN=False
signal.signal(signal.SIGTERM,stop)

mode=sys.argv[1] if len(sys.argv)>1 else "normal"


def ensure_noise_file(path: Path) -> None:
    if path.exists():
        return
    sample_rate = 44100
    duration = 10
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for _ in range(sample_rate * duration):
            wav_file.writeframes(struct.pack("<h", random.randint(-32768, 32767)))

pygame.mixer.init()
noise_file = Path(__file__).with_name("white_noise.wav")
ensure_noise_file(noise_file)
sound=pygame.mixer.Sound(str(noise_file))
ch=pygame.mixer.Channel(0)
ch.play(sound,-1)

print("🌙 白噪声:",mode)

def get_param():
    # 参数调整为与HTML粒子动画同步（6秒周期）
    if mode=="slow": return 3,4.5  # 7.5秒周期
    if mode=="soft": return 3.6,5.4  # 9秒周期
    return 2.4,3.6  # 6秒周期（normal）

while RUN:
    inhale,exhale=get_param()

    for i in range(50):
        vol=0.2+0.3*(math.sin(i/50*math.pi/2)**2)
        ch.set_volume(vol)
        time.sleep(inhale/50)

    for i in range(50):
        vol=0.5*(math.cos(i/50*math.pi/2)**2)+0.2
        ch.set_volume(vol)
        time.sleep(exhale/50)

pygame.quit()
print("🛑 白噪声结束")