import ChatTTS
import soundfile
import torch
import numpy as np
import logging

logging.basicConfig(level=logging.INFO)

chat = ChatTTS.Chat()
chat.load_models(compile=True) # Set to True for better performance

def deterministic(seed=222):
    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.cuda.manual_seed(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    
deterministic(222)
rnd_spk_emb = chat.sample_random_speaker(222)
params_infer_code = {
    "spk_emb": rnd_spk_emb,
}

    
def tts(text):
    logging.info(f'Doing tts to {text}')
    return chat.infer([text], use_decoder=True, params_infer_code=params_infer_code)[0][0]

tts("初始化一下")

if __name__ == '__main__':
    wav = tts("测试中文和English")
    soundfile.write("output1.wav", wav, 24000)
