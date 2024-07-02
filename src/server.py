import asyncio
import logging
import time
from collections import deque

from redis import asyncio as aioredis
from faster_whisper import WhisperModel

from .config import REDIS_SERVER
from .utils import asyncformer
from .translate import translate

CONVERSATION = deque(maxlen=100)
MODEL_SIZE = "large-v3"
CN_PROMPT = '聊一下基于faster-whisper的实时/低延迟语音转写服务'
logging.basicConfig(level=logging.INFO)
model = WhisperModel(MODEL_SIZE, device="auto", compute_type="default")
logging.info('Model loaded')
logging.getLogger("faster_whisper").setLevel(logging.ERROR)


async def transcribe():
    # download audio from redis by popping from list: STS:AUDIO
    def b_transcribe():
        # transcribe audio to text
        start_time = time.time()
        segments, info = model.transcribe("chunk.mp3",
                                          beam_size=5,
                                          no_speech_threshold=0.8,
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

    async with aioredis.from_url(REDIS_SERVER) as redis:
        '-' * 81
        while True:
            length = await redis.llen('STS:AUDIOS')
            if length > 10:
                await redis.expire('STS:AUDIOS', 1)
            content = await redis.blpop('STS:AUDIOS', timeout=0.1)
            if content is None:
                continue

            with open('chunk.mp3', 'wb') as f:
                f.write(content[1])

            text, _period = await asyncformer(b_transcribe)
            t = text.strip().replace('.', '')
            if not t:
                continue
            logging.info(t)
            CONVERSATION.append(text)
            translated = translate(text)
            


async def main():
    await asyncio.gather(transcribe())


if __name__ == '__main__':
    asyncio.run(main())
