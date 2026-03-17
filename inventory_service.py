import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INVENTORY_FILE = BASE_DIR / "inventory.json"


def load_inventory():
    if not INVENTORY_FILE.exists():
        return {}
    with open(INVENTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_inventory(inventory):
    with open(INVENTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(inventory, f, indent=2, ensure_ascii=False)


def format_number(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def inventory_text(inventory):
    if not inventory:
        return "目前沒有庫存資料。"

    lines = ["目前庫存："]

    for location, items in inventory.items():
        lines.append(f"\n【{location}】")

        for item_name, item_data in items.items():
            qty = item_data.get("數量", 0)
            unit = item_data.get("單位", "個")
            threshold = item_data.get("低庫存門檻", 0)

            lines.append(f"- {item_name}：{format_number(qty)}{unit}（低庫存門檻：{format_number(threshold)}{unit}）")

            subareas = item_data.get("子區域", {})
            for subarea_name, subarea_qty in subareas.items():
                lines.append(f"  - {subarea_name}：{format_number(subarea_qty)}{unit}")

    return "\n".join(lines)


def parse_qty(qty_text):
    qty_text = qty_text.strip()
    mapping = {
        "半": 0.5,
        "半包": 0.5,
        "半片": 0.5,
        "半罐": 0.5,
        "半箱": 0.5,
    }
    if qty_text in mapping:
        return mapping[qty_text]

    qty_text = qty_text.replace("半包", "0.5").replace("半片", "0.5").replace("半罐", "0.5").replace("半箱", "0.5")
    qty_text = qty_text.replace("半", "0.5")

    try:
        return float(qty_text)
    except ValueError:
        return None


def normalize_location(location):
    mapping = {
        "大順": "大順家",
        "大順家": "大順家",
        "南屏": "南屏家",
        "南屏家": "南屏家",
        "外出": "外出用品",
        "外出用品": "外出用品",
    }
    return mapping.get(location, location)


def normalize_action(action):
    if action in ["新增", "增加", "補充", "買了", "買進"]:
        return "新增"
    if action in ["使用", "用了", "用掉", "消耗"]:
        return "使用"
    return action


def ensure_location_and_item(inventory, location, item):
    if location not in inventory:
        inventory[location] = {}

    if item not in inventory[location]:
        inventory[location][item] = {
            "數量": 0,
            "低庫存門檻": 1,
            "單位": "個"
        }


def update_inventory(inventory, action, location, item, qty):
    ensure_location_and_item(inventory, location, item)

    current_qty = inventory[location][item].get("數量", 0)
    unit = inventory[location][item].get("單位", "個")

    if action == "新增":
        inventory[location][item]["數量"] = current_qty + qty
        save_inventory(inventory)
        return (
            True,
            f"已新增 {location} 的 {item} {format_number(qty)}{unit}\n"
            f"目前數量：{format_number(inventory[location][item]['數量'])}{unit}"
        )

    if action == "使用":
        if qty > current_qty:
            return (
                False,
                f"{location} 的 {item} 庫存不足\n目前只有：{format_number(current_qty)}{unit}"
            )

        inventory[location][item]["數量"] = current_qty - qty
        save_inventory(inventory)
        return (
            True,
            f"已使用 {location} 的 {item} {format_number(qty)}{unit}\n"
            f"剩餘數量：{format_number(inventory[location][item]['數量'])}{unit}"
        )

    return False, "不支援的操作。"


def parse_natural_inventory_command(text):
    text = text.strip().replace("　", "").replace(" ", "")

    patterns = [
        r"^(新增|增加|補充|使用|用了|用掉|消耗)(大順家|大順|南屏家|南屏|外出用品|外出)(.+?)([0-9]+(?:\.[0-9]+)?|半)(包|片|罐|個|箱)?$",
        r"^(大順家|大順|南屏家|南屏|外出用品|外出)(新增|增加|補充|使用|用了|用掉|消耗)(.+?)([0-9]+(?:\.[0-9]+)?|半)(包|片|罐|個|箱)?$",
        r"^(大順家|大順|南屏家|南屏|外出用品|外出)(.+?)(新增|增加|補充|使用|用了|用掉|消耗)([0-9]+(?:\.[0-9]+)?|半)(包|片|罐|個|箱)?$",
    ]

    for idx, pattern in enumerate(patterns):
        m = re.match(pattern, text)
        if not m:
            continue

        groups = m.groups()

        if idx == 0:
            action, location, item, qty_text, _unit = groups
        elif idx == 1:
            location, action, item, qty_text, _unit = groups
        else:
            location, item, action, qty_text, _unit = groups

        location = normalize_location(location)
        action = normalize_action(action)
        qty = parse_qty(qty_text)

        if qty is None:
            return None

        return {
            "action": action,
            "location": location,
            "item": item,
            "qty": qty,
        }

    return None
