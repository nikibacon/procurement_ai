import os
import time
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

import ai_service
import vision_service
from inventory_service import (
    load_inventory,
    inventory_text,
    parse_natural_inventory_command,
    update_inventory,
    normalize_location,
    parse_qty,
)

load_dotenv()

debug_keys = [k for k in os.environ.keys() if "TELEGRAM" in k or "OPENAI" in k]
print("DEBUG ENV KEYS:", debug_keys)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

print("DEBUG TELEGRAM_TOKEN exists:", bool(TELEGRAM_TOKEN))
print("DEBUG OPENAI_API_KEY exists:", bool(OPENAI_API_KEY))

if not TELEGRAM_TOKEN:
    raise ValueError("找不到 TELEGRAM_TOKEN，請確認 Railway Variables 或 .env 有設定。")

if not OPENAI_API_KEY:
    raise ValueError("找不到 OPENAI_API_KEY，請確認 Railway Variables 或 .env 有設定。")

# 初始化 AI 服務
ai_service.initialize_client(OPENAI_API_KEY)
vision_service.initialize_client(OPENAI_API_KEY)

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# 暫存照片辨識結果，等待使用者輸入地點和數量
# 結構: {chat_id: {"mode": "single"/"multi", "items": ["品項1", "品項2", ...], "timestamp": 時間戳記}}
pending_items = {}


def send_message(chat_id, text):
    url = f"{BASE_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()


def get_updates(offset=None):
    url = f"{BASE_URL}/getUpdates"
    params = {"timeout": 20}
    if offset is not None:
        params["offset"] = offset

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def extract_items_from_vision(vision_result):
    """
    從 vision API 回應中提取候選品項清單
    返回：["品項1", "品項2", ...] 或 []
    最多返回 5 個品項
    """
    lines = vision_result.split('\n')
    items = []
    in_candidates_section = False
    
    for line in lines:
        # 找到「候選品項：」開始提取
        if '候選品項' in line:
            in_candidates_section = True
            # 檢查是否在同一行就有品項（例如：候選品項：1. xxx 2. xxx）
            after_colon = line.split('：', 1)
            if len(after_colon) > 1:
                same_line_text = after_colon[1].strip()
                # 嘗試解析同一行的品項
                parts = re.split(r'\d+\.\s*', same_line_text)
                for part in parts:
                    item = part.strip()
                    if item and item not in items:
                        items.append(item)
            continue
        
        # 在候選品項區段中
        if in_candidates_section:
            # 匹配 "1. 品項名稱" 或 "- 品項名稱"
            match = re.match(r'^\s*[\d\-\*]+\.\s*(.+)$', line)
            if match:
                item = match.group(1).strip()
                if item and item not in items:
                    items.append(item)
            # 空行或其他內容表示結束
            elif line.strip() == '' or '建議操作' in line:
                break
    
    # 如果沒有找到候選品項，嘗試提取「建議品項名稱」
    if not items:
        for line in lines:
            if '建議品項名稱' in line or '品項名稱' in line:
                parts = line.split('：')
                if len(parts) >= 2:
                    item = parts[1].strip()
                    if item:
                        items.append(item)
                        break
    
    # 限制最多 5 個品項
    return items[:5]


def parse_location_qty(text):
    """
    解析「地點 + 數量」格式
    例如：大順家 1、南屏 0.5、外出用品 2
    返回：(location, qty) 或 (None, None)
    """
    text = text.strip().replace("　", " ")
    
    # 移除可能的單位詞
    text = re.sub(r'(包|片|罐|個|箱)$', '', text).strip()
    
    # 模式：地點 + 空格/無空格 + 數量
    patterns = [
        r'^(大順家|大順|南屏家|南屏|外出用品|外出)\s*([0-9]+(?:\.[0-9]+)?|半)$',
    ]
    
    for pattern in patterns:
        m = re.match(pattern, text)
        if m:
            location_raw, qty_text = m.groups()
            location = normalize_location(location_raw)
            qty = parse_qty(qty_text)
            
            if qty is not None:
                return location, qty
    
    return None, None


def parse_item_selection(text):
    """
    解析「編號 + 地點 + 數量」格式
    例如：1 大順家 2、2 南屏 0.5、3 外出用品 1
    返回：(index, location, qty) 或 (None, None, None)
    """
    text = text.strip().replace("　", " ")
    
    # 移除可能的單位詞
    text = re.sub(r'(包|片|罐|個|箱)$', '', text).strip()
    
    # 模式：編號 + 空格 + 地點 + 空格/無空格 + 數量
    patterns = [
        r'^(\d+)\s+(大順家|大順|南屏家|南屏|外出用品|外出)\s*([0-9]+(?:\.[0-9]+)?|半)$',
    ]
    
    for pattern in patterns:
        m = re.match(pattern, text)
        if m:
            index_str, location_raw, qty_text = m.groups()
            index = int(index_str)
            location = normalize_location(location_raw)
            qty = parse_qty(qty_text)
            
            if qty is not None:
                return index, location, qty
    
    return None, None, None


def handle_photo_message(chat_id, photo_list):
    if not photo_list:
        send_message(chat_id, "沒有收到照片資料。")
        return

    largest_photo = photo_list[-1]
    file_id = largest_photo["file_id"]

    try:
        file_path = vision_service.get_file_path(TELEGRAM_TOKEN, file_id)
        local_path = vision_service.TMP_DIR / f"{file_id}.jpg"
        vision_service.download_telegram_file(TELEGRAM_TOKEN, file_path, local_path)

        result = vision_service.ask_vision_with_image(local_path)
        
        # 嘗試提取候選品項清單
        items = extract_items_from_vision(result)
        
        if not items:
            # 無法提取品項，使用原始流程
            reply = (
                "我看了這張照片，先幫你做初步辨識：\n\n"
                f"{result}\n\n"
                "如果辨識正確，你可以直接回覆像這樣：\n"
                "新增 大順家 尿布 1\n"
                "新增 南屏家 濕紙巾 2\n"
                "新增 外出用品 濕紙巾隨身包 3"
            )
            send_message(chat_id, reply)
            return
        
        # 判斷品項數量
        if len(items) == 1:
            # 單一品項：維持原本快速更新流程
            pending_items[chat_id] = {
                "mode": "single",
                "items": items,
                "timestamp": time.time()
            }
            
            reply = (
                "我看了這張照片，辨識結果：\n\n"
                f"{result}\n\n"
                "━━━━━━━━━━━━━━━━\n"
                f"✅ 已記住品項：{items[0]}\n\n"
                "請直接回覆「地點 + 數量」即可新增庫存：\n"
                "例如：\n"
                "• 大順家 1\n"
                "• 南屏 0.5\n"
                "• 外出用品 2"
            )
        else:
            # 多個品項：進入選擇模式
            pending_items[chat_id] = {
                "mode": "multi",
                "items": items[:5],  # 固定保留前 5 個
                "timestamp": time.time()
            }
            
            # 建立候選清單
            items_list = "\n".join([f"{i+1}. {item}" for i, item in enumerate(items[:5])])
            
            reply = (
                f"辨識到多個品項，請選擇：\n\n"
                f"{items_list}\n\n"
                "━━━━━━━━━━━━━━━━\n"
                "請回覆「編號 + 地點 + 數量」\n"
                "例如：\n"
                "• 1 大順家 2\n"
                "• 2 南屏 0.5\n"
                "• 3 外出用品 1"
            )
        
        send_message(chat_id, reply)

    except Exception as e:
        send_message(chat_id, f"照片辨識失敗：{e}")


def handle_text_message(chat_id, text):
    inventory = load_inventory()
    normalized_text = text.strip()
    
    # ==========================================
    # 最優先：檢查是否有待處理的照片辨識品項
    # ==========================================
    if chat_id in pending_items:
        pending_data = pending_items[chat_id]
        mode = pending_data["mode"]
        items = pending_data["items"]
        
        # === 單一品項模式（原本邏輯） ===
        if mode == "single":
            # 1. 優先嘗試解析「地點 + 數量」格式
            location, qty = parse_location_qty(normalized_text)
            
            if location and qty:
                # 成功解析，使用 pending 的品項名稱更新庫存
                item_name = items[0]
                success, message = update_inventory(
                    inventory,
                    "新增",  # 照片辨識後預設為新增
                    location,
                    item_name,
                    qty,
                )
                
                # 清除 pending 狀態
                del pending_items[chat_id]
                
                # 回覆結果
                send_message(chat_id, f"✅ 使用辨識品項：{item_name}\n\n{message}")
                return
            
            # 2. 嘗試解析為完整的自然語言命令
            parsed = parse_natural_inventory_command(normalized_text)
            if parsed:
                # 使用者輸入了完整命令，清除 pending 並執行
                del pending_items[chat_id]
                
                success, message = update_inventory(
                    inventory,
                    parsed["action"],
                    parsed["location"],
                    parsed["item"],
                    parsed["qty"],
                )
                send_message(chat_id, message)
                return
            
            # 3. 檢查是否為系統指令（會清除 pending）
            if normalized_text == "/start":
                del pending_items[chat_id]
                reply = (
                    "家庭採購與生活助理已啟動。\n\n"
                    "目前支援：\n"
                    "查看庫存\n"
                    "購買建議\n"
                    "今日提醒\n"
                    "本週重點\n\n"
                    "自然語言更新範例：\n"
                    "大順新增尿布1\n"
                    "南屏用了尿布半\n"
                    "外出用品新增濕紙巾隨身包2\n\n"
                    "也可以直接傳照片，我會先幫你辨識品項。"
                )
                send_message(chat_id, reply)
                return
            
            if normalized_text == "查看庫存":
                del pending_items[chat_id]
                send_message(chat_id, inventory_text(inventory))
                return
            
            if normalized_text == "購買建議":
                del pending_items[chat_id]
                summary = inventory_text(inventory)
                result = ai_service.get_purchase_suggestion(summary)
                send_message(chat_id, result)
                return
            
            if normalized_text == "今日提醒":
                del pending_items[chat_id]
                summary = inventory_text(inventory)
                result = ai_service.get_daily_reminder(summary)
                send_message(chat_id, result)
                return
            
            if normalized_text == "本週重點":
                del pending_items[chat_id]
                summary = inventory_text(inventory)
                result = ai_service.get_weekly_summary(summary)
                send_message(chat_id, result)
                return
            
            # 4. 格式錯誤，提示正確格式（保留 pending）
            item_name = items[0]
            send_message(
                chat_id,
                f"⚠️ 格式不正確\n\n"
                f"目前記住的品項：{item_name}\n\n"
                f"請輸入「地點 + 數量」，例如：\n"
                f"• 大順家 1\n"
                f"• 南屏 0.5\n"
                f"• 外出用品 2\n\n"
                f"或輸入完整命令：新增 大順家 {item_name} 1"
            )
            return
        
        # === 多品項模式（新增邏輯） ===
        elif mode == "multi":
            # 1. 優先嘗試解析「編號 + 地點 + 數量」格式
            index, location, qty = parse_item_selection(normalized_text)
            
            if index and location and qty:
                # 檢查編號是否有效
                if 1 <= index <= len(items):
                    item_name = items[index - 1]  # 編號從 1 開始，list index 從 0 開始
                    success, message = update_inventory(
                        inventory, "新增", location, item_name, qty
                    )
                    
                    # 清除 pending 狀態
                    del pending_items[chat_id]
                    
                    # 回覆結果
                    send_message(chat_id, f"✅ 使用品項：{item_name}\n\n{message}")
                    return
                else:
                    # 編號超出範圍
                    send_message(
                        chat_id,
                        f"⚠️ 編號錯誤\n\n請輸入 1 到 {len(items)} 之間的編號"
                    )
                    return
            
            # 2. 嘗試解析為完整的自然語言命令
            parsed = parse_natural_inventory_command(normalized_text)
            if parsed:
                # 使用者輸入了完整命令，清除 pending 並執行
                del pending_items[chat_id]
                
                success, message = update_inventory(
                    inventory,
                    parsed["action"],
                    parsed["location"],
                    parsed["item"],
                    parsed["qty"],
                )
                send_message(chat_id, message)
                return
            
            # 3. 檢查是否為系統指令（會清除 pending）
            if normalized_text == "/start":
                del pending_items[chat_id]
                reply = (
                    "家庭採購與生活助理已啟動。\n\n"
                    "目前支援：\n"
                    "查看庫存\n"
                    "購買建議\n"
                    "今日提醒\n"
                    "本週重點\n\n"
                    "自然語言更新範例：\n"
                    "大順新增尿布1\n"
                    "南屏用了尿布半\n"
                    "外出用品新增濕紙巾隨身包2\n\n"
                    "也可以直接傳照片，我會先幫你辨識品項。"
                )
                send_message(chat_id, reply)
                return
            
            if normalized_text == "查看庫存":
                del pending_items[chat_id]
                send_message(chat_id, inventory_text(inventory))
                return
            
            if normalized_text == "購買建議":
                del pending_items[chat_id]
                summary = inventory_text(inventory)
                result = ai_service.get_purchase_suggestion(summary)
                send_message(chat_id, result)
                return
            
            if normalized_text == "今日提醒":
                del pending_items[chat_id]
                summary = inventory_text(inventory)
                result = ai_service.get_daily_reminder(summary)
                send_message(chat_id, result)
                return
            
            if normalized_text == "本週重點":
                del pending_items[chat_id]
                summary = inventory_text(inventory)
                result = ai_service.get_weekly_summary(summary)
                send_message(chat_id, result)
                return
            
            # 4. 格式錯誤，提示正確格式（保留 pending）
            items_list = "\n".join([f"{i+1}. {item}" for i, item in enumerate(items)])
            send_message(
                chat_id,
                f"⚠️ 格式不正確\n\n"
                f"候選品項：\n{items_list}\n\n"
                f"請回覆「編號 + 地點 + 數量」，例如：\n"
                f"• 1 大順家 2\n"
                f"• 2 南屏 0.5\n"
                f"或輸入完整命令"
            )
            return
    
    # ==========================================
    # 沒有 pending：既有的正常流程
    # ==========================================
    
    if normalized_text == "/start":
        reply = (
            "家庭採購與生活助理已啟動。\n\n"
            "目前支援：\n"
            "查看庫存\n"
            "購買建議\n"
            "今日提醒\n"
            "本週重點\n\n"
            "自然語言更新範例：\n"
            "大順新增尿布1\n"
            "南屏用了尿布半\n"
            "外出用品新增濕紙巾隨身包2\n\n"
            "也可以直接傳照片，我會先幫你辨識品項。"
        )
        send_message(chat_id, reply)
        return

    if normalized_text == "查看庫存":
        send_message(chat_id, inventory_text(inventory))
        return

    # 既有的自然語言命令解析
    parsed = parse_natural_inventory_command(normalized_text)
    if parsed:
        success, message = update_inventory(
            inventory,
            parsed["action"],
            parsed["location"],
            parsed["item"],
            parsed["qty"],
        )
        send_message(chat_id, message)
        return

    if normalized_text == "購買建議":
        summary = inventory_text(inventory)
        result = ai_service.get_purchase_suggestion(summary)
        send_message(chat_id, result)
        return

    if normalized_text == "今日提醒":
        summary = inventory_text(inventory)
        result = ai_service.get_daily_reminder(summary)
        send_message(chat_id, result)
        return

    if normalized_text == "本週重點":
        summary = inventory_text(inventory)
        result = ai_service.get_weekly_summary(summary)
        send_message(chat_id, result)
        return

    send_message(
        chat_id,
        "我目前支援：\n"
        "- 查看庫存\n"
        "- 購買建議\n"
        "- 今日提醒\n"
        "- 本週重點\n\n"
        "自然語言更新範例：\n"
        "- 大順新增尿布1\n"
        "- 南屏用了尿布半\n"
        "- 外出用品新增濕紙巾隨身包2\n\n"
        "也可以直接傳照片給我辨識。"
    )


def main():
    print("Telegram Bot 啟動中（requests 版）...")

    offset = None

    while True:
        try:
            data = get_updates(offset=offset)

            if not data.get("ok"):
                print("Telegram API 回傳失敗：", data)
                time.sleep(3)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1

                message = update.get("message")
                if not message:
                    continue

                chat_id = message["chat"]["id"]

                if "photo" in message:
                    print("收到照片訊息")
                    handle_photo_message(chat_id, message["photo"])
                    continue

                text = message.get("text", "").strip()
                if not text:
                    continue

                print("收到訊息：", text)
                handle_text_message(chat_id, text)

        except requests.exceptions.RequestException as e:
            print("網路錯誤：", e)
            time.sleep(5)
        except Exception as e:
            print("程式錯誤：", e)
            time.sleep(5)


if __name__ == "__main__":
    main()