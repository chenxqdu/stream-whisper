import asyncio
from redis import asyncio as aioredis
from playsound import playsound
import logging

from .config import REDIS_SERVER

logging.basicConfig(level=logging.INFO)

async def receive_audio(lang):
    channel = f'STS:{lang}'
    logging.info(f"receiving from {channel}")
    # Sync audio to redis server list STS:AUDIO
    async with aioredis.from_url(REDIS_SERVER) as redis:
        while True:
            length = await redis.llen(channel)
            if length > 10:
                await redis.expire(channel, 1)
            content = await redis.blpop(channel, timeout=0.1)
            if content is None:
                continue
            logging.info(f"{lang} received")
            with open(f'received_{lang}.wav', 'wb') as f:
                f.write(content[1])
                playsound(f'received_{lang}.wav')                
                logging.info(f"{lang} played")

                

async def main():
    try:
        import sys
        await asyncio.gather(receive_audio(lang=sys.argv[1]))
    except KeyboardInterrupt:
        pass

# def api():
#     return asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())