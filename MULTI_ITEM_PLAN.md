# 多品項選擇模式 - 實作計畫

## 📋 需求總結

### 核心需求
1. **單一品項**：維持原本快速更新流程（輸入：地點 + 數量）
2. **多個品項**：顯示候選清單，使用者選擇（輸入：編號 + 地點 + 數量）

### 使用流程

#### 情境 A: 單一品項（維持原本）
```
使用者：*傳送尿布照片*
Bot：   ✅ 已記住品項：尿布
        請直接回覆「地點 + 數量」...
使用者：大順家 1
Bot：   ✅ 使用辨識品項：尿布
        已新增...
```

#### 情境 B: 多個品項（新增）
```
使用者：*傳送洗衣精照片*
Bot：   辨識到多個品項，請選擇：
        1. 尿布
        2. 洗衣精補充包
        3. 洗衣精瓶裝
        
        請回覆：編號 + 地點 + 數量
        例如：
        • 1 大順家 2
        • 2 南屏 0.5
        • 3 外出用品 1
使用者：2 大順家 1
Bot：   ✅ 使用品項：洗衣精補充包
        已新增...
```

---

## 🎯 實作計畫

### 階段 1: 資料結構調整

#### 1.1 修改 pending_items 結構

**原本（單一品項）：**
```python
pending_items = {
    chat_id: {
        "item": "尿布",  # 單一品項
        "timestamp": 123456
    }
}
```

**修改後（支援多品項）：**
```python
pending_items = {
    chat_id: {
        "mode": "single",  # or "multi"
        "items": ["尿布"],  # 單一品項也用 list
        "timestamp": 123456
    }
}

# 多品項範例
pending_items = {
    chat_id: {
        "mode": "multi",
        "items": ["尿布", "洗衣精補充包", "洗衣精瓶裝"],
        "timestamp": 123456
    }
}
```

---

### 階段 2: Vision API 調整

#### 2.1 修改 vision_service.py 的 prompt

**需求：**
- 要求 Vision API 回傳可能的候選品項（最多 5 個）
- 格式要清楚可解析

**修改建議：**
```python
# vision_service.py 中的 prompt
"請辨識這張照片中的物品，並列出可能的品項名稱。
如果有多個可能的品項，請列出最多 5 個候選品項。

回應格式：
辨識結果：[主要品項]
信心：[高/中/低]
候選品項：
1. [品項1]
2. [品項2]
3. [品項3]
建議操作：新增 大順家 [品項1] 1

請使用繁體中文，品項名稱要精確。"
```

#### 2.2 新增函數：extract_items_from_vision()

**功能：**
- 從 Vision API 回應中提取候選品項清單
- 返回 list，可能是單一品項或多個品項

**實作：**
```python
def extract_items_from_vision(vision_result):
    """
    從 vision API 回應中提取候選品項清單
    返回：["品項1", "品項2", ...] 或 []
    """
    lines = vision_result.split('\n')
    items = []
    in_candidates_section = False
    
    for line in lines:
        # 找到「候選品項：」開始提取
        if '候選品項' in line:
            in_candidates_section = True
            continue
        
        # 在候選品項區段中
        if in_candidates_section:
            # 匹配 "1. 品項名稱" 或 "- 品項名稱"
            match = re.match(r'^\s*[\d\-\*\.]+\s*(.+)$', line)
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
    
    return items
```

---

### 階段 3: 解析函數

#### 3.1 新增函數：parse_item_selection()

**功能：**
- 解析「編號 + 地點 + 數量」格式
- 例如：`1 大順家 2` → (1, "大順家", 2.0)

**實作：**
```python
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
```

---

### 階段 4: 修改 handle_photo_message()

**修改邏輯：**
```python
def handle_photo_message(chat_id, photo_list):
    # ... 下載照片 ...
    
    result = vision_service.ask_vision_with_image(local_path)
    
    # 提取候選品項清單
    items = extract_items_from_vision(result)
    
    if not items:
        # 無法提取品項，使用原始流程
        reply = "我看了這張照片，先幫你做初步辨識：\n\n" + result + "\n\n..."
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
            "items": items,
            "timestamp": time.time()
        }
        
        # 建立候選清單
        items_list = "\n".join([f"{i+1}. {item}" for i, item in enumerate(items)])
        
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
```

---

### 階段 5: 修改 handle_text_message() 的 pending 處理

**修改邏輯：**
```python
if chat_id in pending_items:
    pending_data = pending_items[chat_id]
    mode = pending_data["mode"]
    items = pending_data["items"]
    
    # === 單一品項模式（原本邏輯） ===
    if mode == "single":
        # 1. 優先嘗試解析「地點 + 數量」
        location, qty = parse_location_qty(normalized_text)
        
        if location and qty:
            item_name = items[0]
            success, message = update_inventory(...)
            del pending_items[chat_id]
            send_message(chat_id, f"✅ 使用辨識品項：{item_name}\n\n{message}")
            return
        
        # 2. 嘗試解析完整命令
        # 3. 檢查系統指令
        # 4. 格式錯誤
        # ... (保持原本邏輯) ...
    
    # === 多品項模式（新增邏輯） ===
    elif mode == "multi":
        # 1. 優先嘗試解析「編號 + 地點 + 數量」
        index, location, qty = parse_item_selection(normalized_text)
        
        if index and location and qty:
            # 檢查編號是否有效
            if 1 <= index <= len(items):
                item_name = items[index - 1]  # 編號從 1 開始
                success, message = update_inventory(
                    inventory, "新增", location, item_name, qty
                )
                del pending_items[chat_id]
                send_message(chat_id, f"✅ 使用品項：{item_name}\n\n{message}")
                return
            else:
                # 編號超出範圍
                send_message(chat_id, f"⚠️ 編號錯誤\n\n請選擇 1-{len(items)} 之間的編號")
                return
        
        # 2. 嘗試解析完整命令（清除 pending）
        parsed = parse_natural_inventory_command(normalized_text)
        if parsed:
            del pending_items[chat_id]
            success, message = update_inventory(...)
            send_message(chat_id, message)
            return
        
        # 3. 檢查系統指令（清除 pending）
        if normalized_text in ["/start", "查看庫存", "購買建議", ...]:
            del pending_items[chat_id]
            # 執行對應指令
            return
        
        # 4. 格式錯誤（保留 pending）
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
```

---

## 📋 修改檔案清單

### 需要修改的檔案

#### 1. vision_service.py
- **修改：** `ask_vision_with_image()` 的 prompt，要求回傳候選品項清單
- **不修改：** 其他函數保持不變

#### 2. telegram_bot.py
- **修改：** `pending_items` 資料結構
- **修改：** `extract_item_name()` → 改成 `extract_items_from_vision()`
- **新增：** `parse_item_selection()` - 解析「編號 + 地點 + 數量」
- **修改：** `handle_photo_message()` - 判斷單一/多品項
- **修改：** `handle_text_message()` - 處理 single/multi mode

### 不需要修改的檔案
- `inventory_service.py` - 完全不變
- `ai_service.py` - 完全不變
- `inventory.json` - 完全不變

---

## 🧪 測試計畫

### 測試案例 1: 單一品項（維持原本流程）
```
傳送：尿布照片
預期：辨識到 1 個品項 → 快速更新模式
輸入：大順家 1
預期：✅ 使用辨識品項：尿布，更新成功
```

### 測試案例 2: 多個品項（新流程）
```
傳送：洗衣精照片
預期：辨識到多個品項 → 顯示候選清單
      1. 洗衣精補充包
      2. 洗衣精瓶裝
      3. 洗衣精
輸入：1 大順家 2
預期：✅ 使用品項：洗衣精補充包，更新成功
```

### 測試案例 3: 多品項 - 格式錯誤
```
傳送：照片（多品項）
輸入：1 大順家（缺數量）
預期：⚠️ 格式不正確，提示正確格式，保留 pending
輸入：1 大順家 2
預期：✅ 更新成功
```

### 測試案例 4: 多品項 - 編號錯誤
```
傳送：照片（3 個品項）
輸入：5 大順家 1
預期：⚠️ 編號錯誤，請選擇 1-3，保留 pending
```

### 測試案例 5: 多品項 - 取消 pending
```
傳送：照片（多品項）
輸入：查看庫存
預期：清除 pending，顯示庫存
```

### 測試案例 6: 既有功能不受影響
```
輸入：大順新增尿布1
預期：正常執行（不需要照片）
```

---

## ⚠️ 注意事項

### 1. Vision API 的候選品項格式

Vision API 可能無法總是回傳標準格式，需要容錯處理：
- 如果無法解析候選品項，退回原始流程
- 如果只解析到 1 個品項，進入單一品項模式

### 2. pending_items 資料結構向下兼容

雖然修改了資料結構，但因為是記憶體暫存，不需要考慮向下兼容。

### 3. 品項數量上限

建議最多顯示 5 個候選品項，避免訊息過長。

### 4. 編號從 1 開始

使用者看到的編號從 1 開始，但 Python list index 從 0 開始，需要轉換。

---

## 📊 程式碼預估

### 新增程式碼
- `extract_items_from_vision()`: ~40 行
- `parse_item_selection()`: ~30 行
- `handle_photo_message()` 修改: ~20 行
- `handle_text_message()` 新增 multi mode: ~50 行
- Vision prompt 修改: ~10 行

**總計：約 +150 行**

### 修改檔案
- `vision_service.py`: ~10 行修改
- `telegram_bot.py`: ~140 行新增/修改

---

## 🎯 實作步驟

### Step 1: 修改 vision_service.py
- 更新 prompt，要求回傳候選品項清單

### Step 2: 修改 telegram_bot.py - 新增解析函數
- 新增 `extract_items_from_vision()`
- 新增 `parse_item_selection()`

### Step 3: 修改 telegram_bot.py - 修改 pending 結構
- 修改 `pending_items` 初始化
- 修改 `handle_photo_message()`

### Step 4: 修改 telegram_bot.py - 修改 pending 處理
- 修改 `handle_text_message()` 的 pending 區塊
- 新增 multi mode 處理邏輯

### Step 5: 測試
- 語法檢查
- 單一品項測試
- 多品項測試
- 既有功能測試

---

## ✅ 確認事項與限制

### 已確認的限制條件

- [x] Vision API prompt **最小修改**，不破壞既有單一品項辨識流程
- [x] `pending_items` 資料結構（mode + items）可接受
- [x] 單一品項維持原本流程（地點 + 數量）
- [x] 多品項使用（編號 + 地點 + 數量）
- [x] 編號從 1 開始（使用者視角）
- [x] **固定保留前 5 個候選品項**
- [x] 編號超出範圍：**明確提示「請輸入 1 到 N 之間的編號」**
- [x] Multi mode 下**允許完整自然語言命令**，清除 pending
- [x] **成功更新後一定清除 pending**
- [x] **系統指令在 pending 下正常使用**，使用後清除 pending
- [x] **保持所有輸出為繁體中文**
- [x] 格式錯誤時保留 pending
- [x] 既有功能完全不受影響

---

## 🎉 預期效果

### 優勢
1. **更精確**：使用者可以從多個候選品項中選擇
2. **更靈活**：單一品項仍然快速，多品項也不複雜
3. **向下兼容**：既有功能完全不受影響
4. **使用者體驗**：清楚的候選清單和提示

### 風險
1. **Vision API 可能無法總是回傳多個品項**：已有容錯處理
2. **使用者可能不習慣編號格式**：提供清楚的範例和提示
3. **多品項可能較少見**：單一品項仍保持快速流程

---

請確認這個實作計畫是否符合需求，確認後我會開始實作。
