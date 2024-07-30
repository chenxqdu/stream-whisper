import asyncio
import collections
import multiprocessing
import sys
import tempfile
import uuid
import wave
from collections import deque

from playsound import playsound
from redis import asyncio as aioredis
import pyaudio
import webrtcvad
import logging
from src.utils import asyncformer
from src.config import REDIS_SERVER

import atexit

# Generate a unique UUID for the client
c_uuid = str(uuid.uuid4())

# Audio recording parameters
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
# RATE = 48000
CHUNK = 2048
FRAME_DURATION = 30  # 毫秒
FRAME_SIZE = int(RATE * FRAME_DURATION / 1000)

g_frames = deque(maxlen=100)
audio = pyaudio.PyAudio()
logging.basicConfig(level=logging.INFO)

# for audio recording
stream = audio.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)


async def sync_audio(client_uuid):
    # Sync audio to redis server list STS:AUDIO
    async with aioredis.from_url(REDIS_SERVER) as redis:
        while True:
            if g_frames:
                content = g_frames.pop()
                if client_uuid is not None and content is not None:
                    await redis.rpush('STS:SEQS', client_uuid)
                    await redis.rpush('STS:AUDIOS', content)
                logging.info('Sync audio to redis server')


def export_wav(data, filename):
    wf = wave.open(filename, 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(audio.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(b''.join(data))
    wf.close()


def record_until_silence():
    frames = collections.deque(maxlen=30)  # 保存最近 30 个帧
    tmp = collections.deque(maxlen=1000)
    vad = webrtcvad.Vad()
    vad.set_mode(1)  # 敏感度，0 到 3，0 最不敏感，3 最敏感
    triggered = False
    frames.clear()
    ratio = 0.5
    while True:
        frame = stream.read(FRAME_SIZE, exception_on_overflow=False)
        is_speech = vad.is_speech(frame, RATE)
        if not triggered:
            frames.append((frame, is_speech))
            tmp.append(frame)
            num_voiced = len([f for f, speech in frames if speech])
            if num_voiced > ratio * frames.maxlen:
                logging.info("start recording...")
                triggered = True
                frames.clear()
        else:
            frames.append((frame, is_speech))
            tmp.append(frame)
            num_unvoiced = len([f for f, speech in frames if not speech])
            if num_unvoiced > ratio * frames.maxlen:
                logging.info("stop recording...")
                export_wav(tmp, 'record.wav')
                with open('record.wav', 'rb') as f:
                    g_frames.appendleft(f.read())
                break


async def record_audio():
    while True:
        await asyncformer(record_until_silence)


def exit_handler(client_uuid):
    asyncio.run(deregister_client(client_uuid))


async def deregister_client(client_uuid):
    async with aioredis.from_url(REDIS_SERVER) as redis:
        await redis.srem('client_uuids', client_uuid)
        #TODO deregister language
        logging.info(f"deregister Client UUID: {client_uuid}")


async def register_client(client_uuid, client_lang):
    async with aioredis.from_url(REDIS_SERVER) as redis:
        # Register client UUID
        await redis.sadd('client_uuids', client_uuid)
        # Register client Language
        if client_lang not in await redis.smembers('client_langs'):
            await redis.sadd('client_langs', client_lang)
        logging.info(f"step1 register Client UUID:  {client_uuid} and Language: {client_lang}")


async def input_audio(client_uuid, client_lang):
    try:
        task0 = asyncio.create_task(register_client(client_uuid, client_lang))
        task1 = asyncio.create_task(record_audio())
        task2 = asyncio.create_task(sync_audio(client_uuid))
        await asyncio.gather(task0, task1, task2)
    except KeyboardInterrupt:
        # Deregister client
        await deregister_client(client_uuid)
        stream.stop_stream()
        stream.close()
        audio.terminate()


async def receive_audio(client_uuid, client_lang):
    async with aioredis.from_url(REDIS_SERVER) as redis:
        while True:
            content = await redis.blpop(f'STS:{client_lang}', timeout=0.1)
            seq_uuid = await redis.blpop(f'STS:SEQS:{client_uuid}', timeout=0.1)
            if content is None:
                continue
            if seq_uuid is not None and client_uuid == seq_uuid[1].decode('utf-8'):
                continue
            tmp = tempfile.NamedTemporaryFile(dir=".", suffix=".wav")
            logging.info(f"Output audio temp file: {tmp.name}")
            tmp.write(content[1])
            playsound(tmp.name, block=False)
            logging.info(f"{client_lang} played")
            tmp.close()


async def output_audio(client_uuid, client_lang):
    try:
        task3 = asyncio.create_task(receive_audio(client_uuid, client_lang))
        await asyncio.gather(task3)
    except KeyboardInterrupt:
        # Deregister client
        await deregister_client(client_uuid)


def run_coroutine(coro_func, *args):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        coro = coro_func(*args)
        loop.run_until_complete(coro)
    finally:
        loop.close()


if __name__ == "__main__":
    atexit.register(exit_handler, c_uuid)
    p1 = multiprocessing.Process(target=run_coroutine, args=(input_audio, c_uuid, sys.argv[1]))
    p2 = multiprocessing.Process(target=run_coroutine, args=(output_audio, c_uuid, sys.argv[1]))
    p1.start()
    p2.start()
    p1.join()
    p2.join()
