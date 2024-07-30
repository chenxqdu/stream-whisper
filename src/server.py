import asyncio
import logging
import tempfile
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
model = WhisperModel(MODEL_SIZE, device="auto", compute_type="default")
logging.info('Model loaded')
logging.getLogger("faster_whisper").setLevel(logging.ERROR)


async def transcribe(audio_content, client_uuid):
    # download audio from redis by popping from list: STS:AUDIO
    def b_transcribe(fname):
        # transcribe audio to text
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

    tmp = tempfile.NamedTemporaryFile(dir=".", suffix=".wav")
    logging.info(f"Input audio temp file: {tmp.name}")
    tmp.write(audio_content)
    text, _period = await asyncformer(b_transcribe, tmp.name)
    logging.info(f"Transcribe time: {_period }")
    tmp.close()
    t = text.strip().replace('.', '')
    if not t:
        return

    CONVERSATION.append(text)
    time_translate_begin = time.time()
    translated = translate(text)
    time_translate_end = time.time()
    logging.info(f"Translate time: {time_translate_end - time_translate_begin }")
    tasks = []
    for lang in translated:
        lang_text = translated[lang]
        # logging.info(f"Translated content {lang}: {lang_text}")
        tasks.append(tts_and_push(lang_text, lang, client_uuid))

    await asyncio.gather(*tasks)


async def tts_and_push(text, lang, client_uuid):
    time_tts_begin = time.time()
    wav = tts(text)
    tmp = tempfile.NamedTemporaryFile(dir=".", suffix=".wav")
    logging.info(f"tts {lang} temp file: {tmp.name}")
    soundfile.write(tmp, wav, 24000, format="WAV")
    tmp.seek(0)
    async with aioredis.from_url(REDIS_SERVER) as redis:
        for iter_id in await redis.smembers('client_uuids'):
            c_id = iter_id.decode('utf-8')
            await redis.rpush(f'STS:SEQS:{c_id}', client_uuid)
        await redis.rpush(f'STS:{lang}', tmp.read())
        logging.info(f'Sync {lang} tts to STS:{lang}')
    tmp.close()
    time_tts_end = time.time()
    logging.info(f"tts time: {time_tts_end - time_tts_begin }")


async def receive_audio():
    async with aioredis.from_url(REDIS_SERVER) as redis:
        while True:
            content = await redis.blpop('STS:AUDIOS', timeout=0.1)
            if content is None:
                continue
            audio_content = content[1]
            seq_id = await redis.blpop('STS:SEQS', timeout=0.1)
            await transcribe(audio_content, seq_id[1].decode('utf-8'))


async def main():
    await asyncio.gather(receive_audio())


if __name__ == '__main__':
    asyncio.run(main())
