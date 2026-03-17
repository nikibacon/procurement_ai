import os
import base64
from pathlib import Path
import requests
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent
TMP_DIR = BASE_DIR / "tmp_images"
TMP_DIR.mkdir(exist_ok=True)

client = None


def initialize_client(api_key=None):
    """初始化 OpenAI client"""
    global client
    if api_key is None:
        api_key = os.getenv("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key)


def ask_vision_with_image(image_path):
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一個家庭庫存辨識助理。"
                    "請根據照片判斷最可能的物品類型。"
                    "請用繁體中文回答。"
                    "如果不確定，要明確說不確定。"
                    "回答格式固定為：\n"
                    "辨識結果：xxx\n"
                    "信心：高/中/低\n"
                    "建議品項名稱：xxx\n"
                    "建議操作：新增 地點 品項 數量"
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "請辨識這張照片中的家庭用品。"
                            "可能的例子有：尿布、濕紙巾、奶粉、白米、濕紙巾隨身包。"
                            "若看到的是箱裝或多包裝，也請說明。"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        },
                    },
                ],
            },
        ],
    )

    return response.choices[0].message.content


def get_file_path(telegram_token, file_id):
    url = f"https://api.telegram.org/bot{telegram_token}/getFile"
    response = requests.get(url, params={"file_id": file_id}, timeout=30)
    response.raise_for_status()
    data = response.json()

    if not data.get("ok"):
        raise ValueError("無法取得 Telegram 檔案資訊")

    return data["result"]["file_path"]


def download_telegram_file(telegram_token, file_path, local_path):
    file_url = f"https://api.telegram.org/file/bot{telegram_token}/{file_path}"
    response = requests.get(file_url, timeout=60)
    response.raise_for_status()

    with open(local_path, "wb") as f:
        f.write(response.content)
