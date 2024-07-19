import asyncio
import uuid
import logging
from redis import asyncio as aioredis
from playsound import playsound
import pyaudio
import webrtcvad
import wave
import collections
from collections import deque
from .utils import asyncformer
from .config import REDIS_SERVER
import time
import multiprocessing

# Generate a unique UUID for the client
c_uuid = str(uuid.uuid4())

# Audio recording parameters
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 2048
FRAME_DURATION = 30  # milliseconds
FRAME_SIZE = int(RATE * FRAME_DURATION / 1000)

g_frames = deque(maxlen=100)
audio = pyaudio.PyAudio()
logging.basicConfig(level=logging.INFO)

# For audio recording
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
                await redis.rpush(f'STS:AUDIOS:{client_uuid}', content)
                logging.info('step4 Sync audio to redis server')

def export_wav(data, filename):
    wf = wave.open(filename, 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(audio.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(b''.join(data))
    wf.close()

def record_until_silence():
    frames = collections.deque(maxlen=30)  # Save the last 30 frames
    tmp = collections.deque(maxlen=1000)
    vad = webrtcvad.Vad()
    vad.set_mode(1)  # Sensitivity from 0 to 3, 0 is least sensitive, 3 is most sensitive
    triggered = False
    frames.clear()
    ratio = 0.5
    while True:
        frame = stream.read(FRAME_SIZE)
        is_speech = vad.is_speech(frame, RATE)
        if not triggered:
            frames.append((frame, is_speech))
            tmp.append(frame)
            num_voiced = len([f for f, speech in frames if speech])
            if num_voiced > ratio * frames.maxlen:
                logging.info("step2 Start recording... ")
                triggered = True
                frames.clear()
        else:
            frames.append((frame, is_speech))
            tmp.append(frame)
            num_unvoiced = len([f for f, speech in frames if not speech])
            if num_unvoiced > ratio * frames.maxlen:
                logging.info("step3 Stop recording...")
                export_wav(tmp, 'output.wav')
                with open('output.wav', 'rb') as f:
                    g_frames.appendleft(f.read())
                break

async def record_audio():
    while True:
        await asyncformer(record_until_silence)

async def receive_audio(lang,client_uuid):
    async with aioredis.from_url(REDIS_SERVER) as redis:
        while True:
            # Get all UUIDs from Redis
            uuids = await redis.smembers('client_uuids')
            # logging.info(f"all uuids: {uuids}")
            uuids = [uuid.decode('utf-8') for uuid in uuids]
            # uuids = [uuid.decode('utf-8') for uuid in uuids if uuid.decode('utf-8') != client_uuid]
            if not uuids:
                await asyncio.sleep(1)
                continue

            for uuid in uuids:
                channel = f'STS:{lang}:{uuid}'
                # logging.info(f"step5 Subscribe to sts {lang} {uuid}")
                length = await redis.llen(channel)
                # if length > 10:
                #     logging.info(f"Received channel sets expiration {lang} {uuid}")
                #     await redis.expire(channel, 1)
                content = await redis.blpop(channel, timeout=0.1)
                if content is None:
                    continue
                logging.info(f"step6 Received from {lang} {uuid}")
                ts = time.time()
                filename = f'received_{lang}_{uuid}_{ts}.wav'
                with open(filename, 'wb') as f:
                    f.write(content[1])
                    playsound(filename,block=False)
                    logging.info(f"step7 Played {filename}")


async def register_client(client_uuid):
    async with aioredis.from_url(REDIS_SERVER) as redis:
        # Register client UUID
        await redis.sadd('client_uuids', client_uuid)
        logging.info(f"step1 register Client UUID: {client_uuid}") 

import atexit

async def deregister_client(client_uuid):
    async with aioredis.from_url(REDIS_SERVER) as redis:
        await redis.srem('client_uuids', client_uuid)
        logging.info(f"deregister Client UUID: {client_uuid}")                  

def exit_handler(client_uuid):
    asyncio.run(deregister_client(client_uuid))

async def input_audio(client_uuid):
    try:
        task0 = asyncio.create_task(register_client(client_uuid))
        task1 = asyncio.create_task(record_audio())
        task2 = asyncio.create_task(sync_audio(client_uuid))
        await asyncio.gather(task0, task1, task2)
    except KeyboardInterrupt:
        # Deregister client UUID
        await deregister_client(client_uuid)
        stream.stop_stream()
        stream.close()
        audio.terminate()

async def output_audio(client_uuid):
    try:
        task3 = asyncio.create_task(receive_audio('en',client_uuid))
        await asyncio.gather(task3)
    except KeyboardInterrupt:
        # Deregister client UUID
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
    atexit.register(exit_handler,c_uuid)
    p1 = multiprocessing.Process(target=run_coroutine, args=(input_audio,c_uuid))
    p2 = multiprocessing.Process(target=run_coroutine, args=(output_audio,c_uuid))
    p1.start()
    p2.start()
    p1.join()
    p2.join()
