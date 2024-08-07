import asyncio
import logging
import time
from collections import deque

from redis import asyncio as aioredis
from faster_whisper import WhisperModel
import soundfile

from .config import REDIS_SERVER
from .utils import asyncformer
from .translate import translate
from .tts import tts

CONVERSATION = deque(maxlen=100)
MODEL_SIZE = "large-v3"
CN_PROMPT = '聊一下基于faster-whisper的实时/低延迟语音转写服务'
logging.basicConfig(level=logging.INFO)
model = WhisperModel(MODEL_SIZE, num_workers=4, device="auto", compute_type="default")
logging.info('Model loaded')
logging.getLogger("faster_whisper").setLevel(logging.ERROR)


async def transcribe(uuid, audio_content):
    # Transcribe audio to text
    def b_transcribe(fname):
        start_time = time.time()
        segments, info = model.transcribe(fname,
                                          beam_size=5,
                                          no_speech_threshold=0.8,
                                          repetition_penalty=2
                                          )
        end_time = time.time()
        period = end_time - start_time
        text = ''
        if info.language_probability < 0.8:
            return text, period

        for segment in segments:
            t = segment.text
            if t.strip().replace('.', ''):
                text += ', ' + t if text else t
        return text, period

    tmp = tempfile.NamedTemporaryFile(dir=".",suffix=".wav")
    logging.info(f"audio temp file: {tmp.name}")
    tmp.write(audio_content)
    text, _period = await asyncformer(b_transcribe,tmp.name)
    tmp.close()
    t = text.strip().replace('.', '')
    if not t:
        return

    logging.info(f"Transcribed [{uuid}]: {t}")
    CONVERSATION.append(text)
    time_translate_begin = time.time()
    translated = translate(text)
    logging.info(f"Translated [{uuid}]: {translated}")
    time_translate_end = time.time()
    logging.info(f"Translate time: {time_translate_begin - time_translate_end}")
    tasks = []
    for lang in translated:
        lang_text = translated[lang]
        logging.info(f"TTS [{uuid}, {lang}]: {lang_text}")
        tasks.append(tts_and_push(lang_text, lang, uuid))

    await asyncio.gather(*tasks)

import tempfile

async def tts_and_push(text, lang, uuid):
    time_tts_begin = time.time()
    wav = tts(text)
    tmp = tempfile.NamedTemporaryFile(dir=".",suffix=".wav")
    logging.info(f"tts temp file: {tmp.name}")
    soundfile.write(tmp, wav, 24000,format="WAV")
    tmp.seek(0)
    async with aioredis.from_url(REDIS_SERVER) as redis:
        await redis.rpush(f'STS:{lang}:{uuid}', tmp.read())
        logging.info(f'Sync {lang} TTS to STS:{lang}:{uuid}')
    tmp.close()

    time_tts_end = time.time()
    logging.info(f"tts time: {time_tts_begin - time_tts_end}")



async def receive_audio():
    async with aioredis.from_url(REDIS_SERVER) as redis:
        while True:
            # Get all UUIDs from Redis
            uuids = await redis.smembers('client_uuids')
            logging.info(f"uuids: {uuids}")
            if not uuids:
                await asyncio.sleep(1)
                continue

            for uuidb in uuids:
                uuid = uuidb.decode('utf-8')
                channel = f'STS:AUDIOS:{uuid}'
                logging.info(f"channel: {channel}")
                # length = await redis.llen(channel)
                # if length > 10:
                #     await redis.expire(channel, 1)

                content = await redis.blpop(channel, timeout=0.1)
                if content is None:
                    logging.info(f"No content available in {channel}")
                    continue

                audio_content = content[1]
                await transcribe(uuid, audio_content)


async def main():
    await asyncio.gather(receive_audio())


if __name__ == '__main__':
    asyncio.run(main())

