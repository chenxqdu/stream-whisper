# Use the Conversation API to send a text message to Anthropic Claude.

import boto3
import json
from botocore.exceptions import ClientError
import logging

# Create a Bedrock Runtime client in the AWS Region you want to use.
client = boto3.client("bedrock-runtime", region_name="us-west-2")

# Set the model ID, e.g., Claude 3 Haiku.
model_id = "anthropic.claude-3-sonnet-20240229-v1:0"

system_message = """Fix only the grammar errors and do not delete anything in the following text in <text></text> from auto speech recognition and translate it into Chinese and English using the following output format:
{
  "zh": "Translation in Chinese",
  "en": "Translation in English"
}
"""


def translate(text):
    conversation = [
        {
            "role": "user",
            "content": [{"text": f'<text>{text}</text>'}],
        }
    ]

    system = [
        {
            'text': system_message,
        },
    ]
    try:
        response = client.converse(
            system=system,
            modelId=model_id,
            messages=conversation,
            inferenceConfig={"maxTokens": 4096, "temperature": 0.5, "topP": 0.9},
        )
        response_text = response["output"]["message"]["content"][0]["text"]
        logging.info(response_text)
        response_text = response_text[response_text.find('{'):]
        translated_dict = json.loads(response_text)
        logging.info(translated_dict)
        return translated_dict
    except (ClientError, Exception) as e:
        print(f"ERROR: Can't invoke '{model_id}'. Reason: {e}")
        return {"zh": "", "en": ""}


if __name__ == '__main__':
    translate("亚马逊云科技AI技术展示")
