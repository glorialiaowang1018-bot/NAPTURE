# -*- coding: utf-8 -*-
import os
import signal
import subprocess
import sys
import time

import dashscope
from dashscope import Generation


dashscope.api_key = os.getenv("DASHSCOPE_API_KEY", "")
RUN = True
context = ""
segment_index = 0

STORY_SEGMENTS = [
    "夜色慢慢落下来，小兔子抱着柔软的枕头，走到安静的窗边。月光照在树叶上，像一条银色的小路。",
    "它沿着月光小路来到森林里，看见一只迷路的小星星。小星星轻轻闪着光，请小兔子陪它寻找回家的方向。",
    "它们走过开满小花的草地，又听见远处的小溪唱着轻柔的歌。小兔子一点也不着急，只是慢慢向前走。",
    "后来，云朵为它们让开了一条路。小星星终于飞回夜空，还送给小兔子一束暖暖的星光。",
    "小兔子回到自己的床上，把星光放在枕边。它闭上眼睛，呼吸越来越轻，很快进入了甜甜的梦乡。",
]


def stop(_signal, _frame):
    global RUN
    RUN = False


signal.signal(signal.SIGTERM, stop)


def fallback_text():
    global segment_index
    text = STORY_SEGMENTS[segment_index % len(STORY_SEGMENTS)]
    segment_index += 1
    return text


def generate_text():
    global context
    if not dashscope.api_key:
        return fallback_text()
    prompt = (
        "你是幼儿园午睡故事讲述者。延续同一个温柔、安静的儿童故事，"
        "每次只讲2到4句，不要突然更换人物，不要说教。已讲内容：\n" + context
    )
    try:
        response = Generation.call(model="qwen-turbo", prompt=prompt)
        text = response.output.text.strip()
        if not text:
            return fallback_text()
        context = (context + "\n" + text)[-800:]
        return text
    except Exception:
        return fallback_text()


def speak_offline(text):
    if os.name != "nt":
        print(text, flush=True)
        time.sleep(max(3, len(text) / 5))
        return
    environment = os.environ.copy()
    environment["STORY_TEXT"] = text
    command = (
        "Add-Type -AssemblyName System.Speech; "
        "$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "try { $voice.SelectVoice('Microsoft Huihui Desktop') } catch {}; "
        "$voice.Rate = -2; $voice.Volume = 75; $voice.Speak($env:STORY_TEXT)"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"offline speech failed with code {result.returncode}")


print("故事播放已启动", flush=True)
while RUN:
    speak_offline(generate_text())
    for _ in range(10):
        if not RUN:
            break
        time.sleep(0.1)
print("故事播放已结束", flush=True)
