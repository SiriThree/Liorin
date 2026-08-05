#!/usr/bin/env python3
"""Generate a causal Liorin structured support dataset.

Products remain aligned with TraceMind manuals, while customers, orders,
tickets, and warranty cases are synthetic. The generation model intentionally
captures business causality instead of only producing fixed-size random rows:

- customers have long-tail activity weights;
- order status follows order age;
- tickets are produced from purchased items with product-specific issue rates;
- repeat tickets reference a parent ticket;
- warranty cases are escalated from eligible tickets.
"""

import json
import random
import calendar
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "structured"
MANUALS_DIR = Path(__file__).resolve().parents[1] / "knowledge" / "manuals"

CUSTOMER_COUNT = 300
ORDER_COUNT = 1500
MIN_TICKET_COUNT = 420
WARRANTY_CASE_COUNT = 140
TICKET_PROBABILITY_SCALE = 0.72
RANDOM_SEED = 20260804
CURRENT_DATE = date(2026, 8, 4)

FIRST_NAMES = [
    "Alex", "Avery", "Blake", "Casey", "Drew", "Elliot", "Harper", "Jordan",
    "Kai", "Morgan", "Parker", "Quinn", "Riley", "Rowan", "Sam", "Taylor",
    "Maya", "Noah", "Iris", "Leo", "Nina", "Owen", "Sara", "Victor",
    "Mei", "Hao", "Jia", "Wei", "Priya", "Anika", "Diego", "Sofia",
]
LAST_NAMES = [
    "Chen", "Zhang", "Wang", "Lin", "Liu", "Park", "Kim", "Singh",
    "Patel", "Garcia", "Miller", "Wilson", "Brown", "Davis", "Martinez", "Nguyen",
    "Hernandez", "Lopez", "Khan", "Shah", "Tan", "Yu", "Iyer", "Sato",
]
ENTERPRISES = [
    "Northstar", "Orion", "Vector", "Acme", "Helio", "Aster", "Summit",
    "Nimbus", "Atlas", "Meridian", "BluePeak", "Redwood", "Cobalt",
    "SinoTech", "Riverbend", "NovaGrid", "Kestrel Labs", "BrightWare",
]

PRODUCT_PROFILES = {
    "LIO-PROD-001": {"category": "xr_device", "warranty_months": 24, "issue_rate": 0.16, "warranty_escalation_rate": 0.18, "issues": ["connectivity", "lens_alignment", "firmware_update", "motion_tracking"]},
    "LIO-PROD-002": {"category": "ergonomics", "warranty_months": 36, "issue_rate": 0.07, "warranty_escalation_rate": 0.10, "issues": ["assembly_help", "noise_or_vibration", "hydraulic_lift", "part_replacement"]},
    "LIO-PROD-003": {"category": "fitness_equipment", "warranty_months": 24, "issue_rate": 0.12, "warranty_escalation_rate": 0.16, "issues": ["noise_or_vibration", "resistance_calibration", "assembly_help", "display_error"]},
    "LIO-PROD-004": {"category": "wearable", "warranty_months": 12, "issue_rate": 0.13, "warranty_escalation_rate": 0.12, "issues": ["battery_or_power", "bluetooth_pairing", "sync_failure", "charging"]},
    "LIO-PROD-005": {"category": "kids_vehicle", "warranty_months": 12, "issue_rate": 0.13, "warranty_escalation_rate": 0.18, "issues": ["battery_or_power", "startup_failure", "charger_failure", "safety_check"]},
    "LIO-PROD-006": {"category": "major_appliance", "warranty_months": 36, "issue_rate": 0.10, "warranty_escalation_rate": 0.22, "issues": ["cooling_performance", "noise_or_vibration", "water_leak", "temperature_control"]},
    "LIO-PROD-007": {"category": "input_device", "warranty_months": 12, "issue_rate": 0.08, "warranty_escalation_rate": 0.08, "issues": ["key_failure", "bluetooth_pairing", "firmware_update", "compatibility"]},
    "LIO-PROD-008": {"category": "power_equipment", "warranty_months": 24, "issue_rate": 0.17, "warranty_escalation_rate": 0.24, "issues": ["startup_failure", "fuel_system", "overload_shutdown", "maintenance"]},
    "LIO-PROD-009": {"category": "smart_home", "warranty_months": 24, "issue_rate": 0.10, "warranty_escalation_rate": 0.10, "issues": ["wiring_setup", "temperature_control", "schedule_programming", "connectivity"]},
    "LIO-PROD-010": {"category": "small_appliance", "warranty_months": 12, "issue_rate": 0.09, "warranty_escalation_rate": 0.11, "issues": ["overheat_protection", "startup_failure", "airflow_blocked", "noise_or_vibration"]},
    "LIO-PROD-011": {"category": "marine_vehicle", "warranty_months": 24, "issue_rate": 0.20, "warranty_escalation_rate": 0.26, "issues": ["throttle_response", "engine_start", "cooling_system", "maintenance"]},
    "LIO-PROD-012": {"category": "water_system", "warranty_months": 24, "issue_rate": 0.17, "warranty_escalation_rate": 0.23, "issues": ["water_leak", "startup_failure", "pressure_drop", "priming"]},
    "LIO-PROD-013": {"category": "major_appliance", "warranty_months": 36, "issue_rate": 0.12, "warranty_escalation_rate": 0.20, "issues": ["water_leak", "drainage", "detergent_residue", "salt_indicator"]},
    "LIO-PROD-014": {"category": "major_appliance", "warranty_months": 36, "issue_rate": 0.09, "warranty_escalation_rate": 0.18, "issues": ["temperature_control", "heating_element", "door_seal", "display_error"]},
    "LIO-PROD-015": {"category": "power_tool", "warranty_months": 12, "issue_rate": 0.13, "warranty_escalation_rate": 0.17, "issues": ["battery_or_power", "chuck_jam", "overheat_protection", "charging"]},
    "LIO-PROD-016": {"category": "camera", "warranty_months": 24, "issue_rate": 0.08, "warranty_escalation_rate": 0.10, "issues": ["lens_error", "battery_or_power", "storage_card", "firmware_update"]},
    "LIO-PROD-017": {"category": "air_treatment", "warranty_months": 24, "issue_rate": 0.10, "warranty_escalation_rate": 0.12, "issues": ["filter_indicator", "airflow_blocked", "sensor_cleaning", "noise_or_vibration"]},
    "LIO-PROD-018": {"category": "hvac", "warranty_months": 36, "issue_rate": 0.13, "warranty_escalation_rate": 0.22, "issues": ["cooling_performance", "filter_cleaning", "temperature_control", "water_leak"]},
    "LIO-PROD-019": {"category": "cleaning", "warranty_months": 12, "issue_rate": 0.14, "warranty_escalation_rate": 0.15, "issues": ["steam_pressure", "water_leak", "assembly_help", "descaling"]},
    "LIO-PROD-020": {"category": "input_device", "warranty_months": 12, "issue_rate": 0.07, "warranty_escalation_rate": 0.07, "issues": ["bluetooth_pairing", "tracking_accuracy", "battery_or_power", "compatibility"]},
}

HARDWARE_ISSUES = {
    "hydraulic_lift", "part_replacement", "resistance_calibration", "battery_or_power",
    "charger_failure", "cooling_performance", "key_failure", "startup_failure",
    "fuel_system", "overload_shutdown", "overheat_protection", "engine_start",
    "cooling_system", "water_leak", "pressure_drop", "drainage", "heating_element",
    "door_seal", "chuck_jam", "lens_error", "steam_pressure",
}

LOW_VOLUME_CATEGORIES = {
    "marine_vehicle", "kids_vehicle", "power_equipment", "water_system",
    "major_appliance", "hvac",
}
BULK_CATEGORIES = {"input_device", "wearable", "small_appliance", "air_treatment"}
CANCEL_REASONS = [
    "customer_request", "payment_failed", "out_of_stock", "risk_control",
    "duplicate_order", "address_issue", "contract_hold", "price_changed",
]

PRODUCT_MARKET_PRICES = {
    "LIO-PROD-001": 2499.00,
    "LIO-PROD-002": 899.00,
    "LIO-PROD-003": 1899.00,
    "LIO-PROD-004": 329.00,
    "LIO-PROD-005": 1299.00,
    "LIO-PROD-006": 3299.00,
    "LIO-PROD-007": 459.00,
    "LIO-PROD-008": 4299.00,
    "LIO-PROD-009": 259.00,
    "LIO-PROD-010": 169.00,
    "LIO-PROD-011": 8899.00,
    "LIO-PROD-012": 1199.00,
    "LIO-PROD-013": 2899.00,
    "LIO-PROD-014": 799.00,
    "LIO-PROD-015": 699.00,
    "LIO-PROD-016": 1099.00,
    "LIO-PROD-017": 1499.00,
    "LIO-PROD-018": 3599.00,
    "LIO-PROD-019": 499.00,
    "LIO-PROD-020": 129.00,
}

EMAIL_DOMAINS = [
    "gmail.com", "outlook.com", "qq.com", "163.com", "icloud.com",
    "hotmail.com", "foxmail.com", "example.com",
]
CHANNELS = ["web", "mobile_app", "phone", "email", "marketplace", "field_sales"]
SALES_REPS = ["Mia Zhao", "Evan Brooks", "Nora Singh", "Luis Chen", "Aki Tanaka", None]
SUPPORT_TEAMS = ["tier1", "tier2", "field_service", "warranty_ops", "enterprise_success"]

ISSUE_LABELS_ZH = {
    "connectivity": "连接不稳定",
    "lens_alignment": "镜头校准异常",
    "firmware_update": "固件升级失败",
    "motion_tracking": "动作追踪异常",
    "assembly_help": "安装步骤不清楚",
    "noise_or_vibration": "噪音或振动异常",
    "hydraulic_lift": "升降杆失灵",
    "part_replacement": "配件需要更换",
    "resistance_calibration": "阻力校准异常",
    "display_error": "屏幕报错",
    "battery_or_power": "电池或供电异常",
    "bluetooth_pairing": "蓝牙无法配对",
    "sync_failure": "数据同步失败",
    "charging": "充电异常",
    "startup_failure": "无法启动",
    "charger_failure": "充电器疑似故障",
    "safety_check": "需要安全检查",
    "cooling_performance": "制冷效果异常",
    "water_leak": "漏水",
    "temperature_control": "温控不准",
    "key_failure": "按键失灵",
    "compatibility": "兼容性问题",
    "fuel_system": "供油系统异常",
    "overload_shutdown": "过载自动关机",
    "maintenance": "保养问题",
    "wiring_setup": "接线安装问题",
    "schedule_programming": "定时程序设置失败",
    "overheat_protection": "过热保护频繁触发",
    "airflow_blocked": "风道堵塞",
    "throttle_response": "油门响应异常",
    "engine_start": "发动机无法启动",
    "cooling_system": "冷却系统报警",
    "pressure_drop": "压力下降",
    "priming": "泵体无法正常引水",
    "drainage": "排水异常",
    "detergent_residue": "清洁剂残留",
    "salt_indicator": "盐量指示异常",
    "heating_element": "加热元件异常",
    "door_seal": "门封密封异常",
    "chuck_jam": "夹头卡住",
    "lens_error": "镜头报错",
    "storage_card": "存储卡无法识别",
    "filter_indicator": "滤芯指示灯异常",
    "filter_cleaning": "滤网清洁提醒异常",
    "sensor_cleaning": "传感器需要清洁",
    "steam_pressure": "蒸汽压力不足",
    "descaling": "除垢后仍提示异常",
    "tracking_accuracy": "指针定位不准",
}


def _write_json(name: str, rows: list[dict]) -> None:
    (DATA_DIR / f"{name}.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _profile(product: dict) -> dict:
    return PRODUCT_PROFILES.get(
        product["product_id"],
        {"category": "technical_product", "warranty_months": 12, "issue_rate": 0.08, "warranty_escalation_rate": 0.1, "issues": ["manual_clarification"]},
    )


def load_and_normalize_products() -> list[dict]:
    products = json.loads((DATA_DIR / "products.json").read_text(encoding="utf-8"))
    manual_files = {
        path.name.split("_", 1)[0]: path.name
        for path in sorted(MANUALS_DIR.glob("LIO-PROD-*.md"))
        if "_" in path.name
    }
    for product in products:
        profile = _profile(product)
        manual_file = manual_files.get(product["product_id"])
        if manual_file:
            manual_stem = Path(manual_file).stem
            product_name = manual_stem.split("_", 1)[1]
            product["name"] = product_name.removesuffix("手册")
            product["manual_file"] = manual_file
            product["source_file"] = None
        product["category"] = profile["category"]
        product["warranty_months"] = profile["warranty_months"]
        product["price"] = PRODUCT_MARKET_PRICES.get(product["product_id"], product["price"])
        current_stock = product.get("currently_in_stock", product.get("in_stock", True))
        product["currently_in_stock"] = bool(current_stock)
        product.pop("in_stock", None)
    return products


def _consumer_email(first: str, last: str, idx: int) -> str:
    patterns = [
        f"{first.lower()}.{last.lower()}{idx}",
        f"{first[0].lower()}{last.lower()}",
        f"{last.lower()}_{first.lower()}",
        f"{first.lower()}{random.randint(1981, 2004)}",
        f"{first.lower()}-{last.lower()}",
    ]
    if random.random() < 0.03:
        return f"{random.choice(patterns).upper()}@{random.choice(EMAIL_DOMAINS)}"
    return f"{random.choice(patterns)}@{random.choice(EMAIL_DOMAINS)}"


def _enterprise_email(company: str, department: str, idx: int) -> str:
    slug = company.lower().replace(" ", "")
    local = random.choice([
        department,
        f"{department}-team",
        f"{department}.{idx}",
        "support",
        "purchasing",
        "helpdesk",
    ])
    domain = random.choice([f"{slug}.example.com", f"{slug}.co", f"{slug}-tech.cn"])
    return f"{local}@{domain}"


def _maybe_phone(idx: int) -> str | None:
    if random.random() < 0.18:
        return None
    if random.random() < 0.25:
        return f"+86 13{random.randint(0, 9)} {random.randint(1000, 9999)} {random.randint(1000, 9999)}"
    return f"+1-415-{random.randint(200, 999)}-{random.randint(1000, 9999)}"


def generate_customers() -> list[dict]:
    customers = [
        {"customer_id": "CUST-001", "email": "lin.chen@example.com", "name": "Lin Chen", "tenant_id": "TENANT-CONSUMER", "segment": "Consumer", "activity_score": 3.8, "phone": "+1-415-288-0142", "company_name": None, "source_system": "shopify"},
        {"customer_id": "CUST-002", "email": "ops@northstar.example.com", "name": "Northstar Ops", "tenant_id": "TENANT-NORTHSTAR", "segment": "Enterprise", "activity_score": 18.0, "phone": None, "company_name": "Northstar", "source_system": "salesforce"},
        {"customer_id": "CUST-003", "email": "mei.zhang@example.com", "name": "Mei Zhang", "tenant_id": "TENANT-CONSUMER", "segment": "Consumer", "activity_score": 1.4, "phone": "+86 136 2026 0804", "company_name": None, "source_system": "legacy_crm"},
        {"customer_id": "CUST-004", "email": "it@orion.example.com", "name": "Orion IT", "tenant_id": "TENANT-ORION", "segment": "Enterprise", "activity_score": 13.5, "phone": "+1-415-614-2001", "company_name": "Orion", "source_system": "salesforce"},
        {"customer_id": "CUST-005", "email": "hao.wang@example.com", "name": "Hao Wang", "tenant_id": "TENANT-CONSUMER", "segment": "Consumer", "activity_score": 0.9, "phone": None, "company_name": None, "source_system": "web"},
    ]
    used_emails = {customer["email"].lower() for customer in customers}
    for idx in range(len(customers) + 1, CUSTOMER_COUNT + 1):
        if random.random() < 0.34:
            company = random.choice(ENTERPRISES)
            department = random.choice(["ops", "it", "support", "field", "procurement"])
            email = _enterprise_email(company, department, idx)
            while email.lower() in used_emails:
                email = _enterprise_email(company, department, idx + random.randint(1, 999))
            used_emails.add(email.lower())
            customers.append({
                "customer_id": f"CUST-{idx:03d}",
                "email": email,
                "name": random.choice([f"{company} {department.title()}", f"{department.title()} Desk", f"{company} Shared Inbox"]),
                "tenant_id": f"TENANT-{company.upper().replace(' ', '-')}",
                "segment": "Enterprise",
                "activity_score": round(random.lognormvariate(0.9, 1.05) * random.uniform(0.65, 1.45), 3),
                "phone": _maybe_phone(idx),
                "company_name": company,
                "source_system": random.choice(["salesforce", "partner_portal", "legacy_crm", "field_sales"]),
            })
        else:
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            email = _consumer_email(first, last, idx)
            while email.lower() in used_emails:
                email = _consumer_email(first, last, idx + random.randint(1, 999))
            used_emails.add(email.lower())
            display_name = f"{first} {last}"
            if random.random() < 0.06:
                display_name = random.choice([display_name.lower(), display_name.upper(), f"{last}, {first}"])
            customers.append({
                "customer_id": f"CUST-{idx:03d}",
                "email": email,
                "name": display_name,
                "tenant_id": "TENANT-CONSUMER",
                "segment": "Consumer",
                "activity_score": round(random.lognormvariate(-0.1, 0.8), 3),
                "phone": _maybe_phone(idx),
                "company_name": None,
                "source_system": random.choice(["web", "mobile_app", "marketplace", "legacy_crm"]),
            })
    return customers


def _customer_activity_weights(customers: list[dict]) -> list[float]:
    """Long-tail activity: explicit score drives repeat purchase frequency."""
    return [max(float(customer["activity_score"]), 0.05) for customer in customers]


def _weighted_order_date() -> date:
    year = random.choices([2024, 2025, 2026], weights=[28, 44, 28], k=1)[0]
    year_start = date(year, 1, 1)
    year_end = min(date(year, 12, 31), CURRENT_DATE)
    max_day = (year_end - year_start).days
    if random.random() < 0.34:
        q4 = date(year, 10, 1)
        if q4 <= year_end:
            return q4 + timedelta(days=random.randint(0, (year_end - q4).days))
    return year_start + timedelta(days=random.randint(0, max_day))


def _status_for_order(order_date: date) -> str:
    age_days = (CURRENT_DATE - order_date).days
    if age_days <= 1:
        return random.choices(["Processing", "Cancelled"], weights=[92, 8], k=1)[0]
    if age_days <= 5:
        return random.choices(["Processing", "Shipped", "Cancelled"], weights=[42, 50, 8], k=1)[0]
    if age_days <= 14:
        return random.choices(["Shipped", "Delivered", "Cancelled"], weights=[36, 58, 6], k=1)[0]
    return random.choices(["Delivered", "Cancelled"], weights=[96, 4], k=1)[0]


def _order_status_events(order: dict) -> list[dict]:
    order_date = date.fromisoformat(order["order_date"])
    events = []
    event_id_base = order["order_id"].replace("ORD-", "OSE-")
    steps = [("created", order_date)]
    if order["status"] == "Cancelled":
        steps.append(("cancelled", min(CURRENT_DATE, order_date + timedelta(days=random.randint(0, 6)))))
    else:
        paid_at = order_date if random.random() < 0.74 else order_date + timedelta(days=1)
        steps.append(("paid", min(CURRENT_DATE, paid_at)))
        if order["status"] in {"Processing", "Shipped", "Delivered"}:
            processing_at = min(CURRENT_DATE, paid_at + timedelta(days=random.randint(0, 3)))
            steps.append(("processing", processing_at))
        if order["status"] in {"Shipped", "Delivered"}:
            shipped_at = min(CURRENT_DATE, processing_at + timedelta(days=random.randint(1, 5)))
            steps.append(("shipped", shipped_at))
        if order["status"] == "Delivered":
            delivered_at = min(CURRENT_DATE, shipped_at + timedelta(days=random.randint(2, 10)))
            steps.append(("delivered", delivered_at))

    for idx, (status, happened_at) in enumerate(steps, start=1):
        events.append({
            "event_id": f"{event_id_base}-{idx:02d}",
            "order_id": order["order_id"],
            "status": status,
            "happened_at": happened_at.isoformat(),
            "actor": random.choice(["system", "payment_gateway", "warehouse", "carrier", "support_agent"]),
            "note": random.choice([None, "", "auto sync", "manual correction", "carrier callback"]),
        })
    return events


def _product_weights(products: list[dict], customer_segment: str) -> list[float]:
    weights = []
    for product in products:
        category = _profile(product)["category"]
        price_factor = max(0.35, 1.35 - product["price"] / 1200)
        enterprise_boost = 1.55 if customer_segment == "Enterprise" and category in {
            "major_appliance", "hvac", "power_equipment", "water_system",
            "input_device", "air_treatment",
        } else 1.0
        weights.append(price_factor * enterprise_boost)
    return weights


def _choose_order_products(
    products: list[dict],
    customer_segment: str,
    line_count: int,
) -> list[dict]:
    """Weighted sampling without duplicate SKU rows in one order."""
    available = products.copy()
    chosen = []
    for _ in range(min(line_count, len(available))):
        weights = _product_weights(available, customer_segment)
        product = random.choices(available, weights=weights, k=1)[0]
        chosen.append(product)
        available = [candidate for candidate in available if candidate["product_id"] != product["product_id"]]
    return chosen


def _quantity_for_product(product: dict, customer_segment: str) -> int:
    category = _profile(product)["category"]
    if customer_segment == "Consumer":
        if category in LOW_VOLUME_CATEGORIES:
            return random.choices([1, 2], weights=[97, 3], k=1)[0]
        return random.choices([1, 2, 3], weights=[84, 14, 2], k=1)[0]

    if category == "marine_vehicle":
        return random.choices([1, 2], weights=[96, 4], k=1)[0]
    if category in LOW_VOLUME_CATEGORIES:
        return random.choices([1, 2, 3, 5, 10], weights=[48, 28, 15, 7, 2], k=1)[0]
    if category in BULK_CATEGORIES:
        return random.choices([1, 2, 3, 5, 10, 20], weights=[24, 25, 20, 16, 10, 5], k=1)[0]
    return random.choices([1, 2, 3, 5], weights=[48, 29, 16, 7], k=1)[0]


def _line_price(product: dict, customer: dict, channel: str) -> float:
    price = product["price"]
    if customer["segment"] == "Enterprise":
        price *= random.uniform(0.78, 0.96)
    elif channel == "marketplace":
        price *= random.uniform(0.88, 1.05)
    else:
        price *= random.uniform(0.92, 1.08)
    if random.random() < 0.12:
        price *= random.choice([0.85, 0.9, 0.95, 1.1])
    return round(price, 2)


def generate_orders_and_items(customers: list[dict], products: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    orders = []
    order_items = []
    order_status_events = []
    activity_weights = _customer_activity_weights(customers)
    item_id = 1

    for idx in range(1, ORDER_COUNT + 1):
        customer = random.choices(customers, weights=activity_weights, k=1)[0]
        order_date = _weighted_order_date()
        status = _status_for_order(order_date)
        order_id = f"ORD-{order_date.year}-{idx:05d}"
        channel = random.choice(CHANNELS)
        tracking_number = None if status in {"Processing", "Cancelled"} else f"LIO{order_date.year}{idx:08d}"
        cancel_reason = random.choice(CANCEL_REASONS) if status == "Cancelled" else None
        if customer["segment"] == "Enterprise":
            line_count = random.choices([1, 2, 3, 4, 5], weights=[22, 34, 24, 14, 6], k=1)[0]
        else:
            line_count = random.choices([1, 2, 3], weights=[62, 30, 8], k=1)[0]
        selected_products = _choose_order_products(products, customer["segment"], line_count)

        if cancel_reason == "out_of_stock":
            out_of_stock = [
                product for product in products
                if not product["currently_in_stock"]
                and product["product_id"] not in {selected["product_id"] for selected in selected_products}
            ]
            if out_of_stock and selected_products:
                selected_products[-1] = random.choice(out_of_stock)

        total = 0.0
        for product in selected_products:
            quantity = _quantity_for_product(product, customer["segment"])
            price = _line_price(product, customer, channel)
            total += quantity * price
            order_items.append({
                "order_item_id": item_id,
                "order_id": order_id,
                "product_id": product["product_id"],
                "quantity": quantity,
                "price_per_unit": price,
            })
            item_id += 1

        orders.append({
            "order_id": order_id,
            "customer_id": customer["customer_id"],
            "order_date": order_date.isoformat(),
            "status": status,
            "total_amount": round(total, 2),
            "tracking_number": tracking_number,
            "cancel_reason": cancel_reason,
            "channel": channel,
            "sales_rep": random.choice(SALES_REPS) if customer["segment"] == "Enterprise" else None,
            "discount_code": random.choice([None, None, None, "WELCOME10", "BULK-Q3", "RENEWAL", "MARKETPLACE"]),
        })
        order_status_events.extend(_order_status_events(orders[-1]))
    return orders, order_items, order_status_events


def _eligible_order_items(orders: list[dict], order_items: list[dict]) -> list[tuple[dict, dict]]:
    order_by_id = {o["order_id"]: o for o in orders if o["status"] in {"Delivered", "Shipped"}}
    return [(order_by_id[i["order_id"]], i) for i in order_items if i["order_id"] in order_by_id]


def _ticket_probability(order: dict, item: dict, product: dict) -> float:
    profile = _profile(product)
    age_days = max((CURRENT_DATE - date.fromisoformat(order["order_date"])).days, 1)
    early_life = 1.8 if age_days <= 45 else 1.0
    wear_out = 1.3 if age_days >= 420 else 1.0
    quantity = min(2.2, 1 + item["quantity"] / 14)
    status = 1.2 if order["status"] == "Shipped" else 1.0
    raw_probability = profile["issue_rate"] * early_life * wear_out * quantity * status
    return min(0.58, raw_probability * TICKET_PROBABILITY_SCALE)


def _priority_for_issue(issue_type: str, segment: str) -> str:
    urgent_issues = {"water_leak", "engine_start", "fuel_system", "cooling_system", "overload_shutdown", "safety_check"}
    if issue_type in urgent_issues:
        return random.choices(["high", "urgent", "medium"], weights=[55, 30, 15], k=1)[0]
    if segment == "Enterprise":
        return random.choices(["medium", "high", "urgent", "low"], weights=[48, 34, 8, 10], k=1)[0]
    return random.choices(["low", "medium", "high"], weights=[36, 48, 16], k=1)[0]


def _ticket_status(created_at: date, priority: str) -> str:
    age_days = (CURRENT_DATE - created_at).days
    if age_days <= 3:
        return random.choices(["open", "in_progress"], weights=[62, 38], k=1)[0]
    if age_days <= 14:
        return random.choices(["open", "pending_customer", "in_progress", "resolved"], weights=[18, 22, 36, 24], k=1)[0]
    if priority in {"urgent", "high"}:
        return random.choices(["in_progress", "pending_customer", "resolved"], weights=[22, 18, 60], k=1)[0]
    return random.choices(["pending_customer", "resolved"], weights=[20, 80], k=1)[0]


def _ticket_date(order_date: date, parent_created_at: date | None = None) -> date | None:
    if parent_created_at and parent_created_at >= CURRENT_DATE:
        return None
    start = parent_created_at + timedelta(days=random.randint(1, 18)) if parent_created_at else order_date + timedelta(days=1)
    if start > CURRENT_DATE:
        return None
    return start + timedelta(days=random.randint(0, max((CURRENT_DATE - start).days, 0)))


def _ticket_summary(product_name: str, issue_type: str) -> str:
    issue_label = ISSUE_LABELS_ZH.get(issue_type, issue_type.replace("_", " "))
    issue_text = issue_type.replace("_", " ")
    templates = [
        f"{product_name}使用几天后出现{issue_label}，客户已经尝试断电重启，但问题仍然存在。",
        f"客户反馈{product_name}{issue_label}，希望确认是否需要寄修或更换配件。",
        f"{product_name}在正常使用中出现{issue_label}，客户说问题是间歇性的。",
        f"电话进线记录：客户说{product_name}{issue_label}，现场暂时无法继续使用。",
        f"邮件反馈{product_name}{issue_label}，客户已按说明书排查过一次。",
        f"售后回访中提到{product_name}{issue_label}，需要确认下一步处理方式。",
        f"Partner case import: {issue_text}; restart/reset already attempted.",
        f"Legacy partner record mentions {issue_text}; product details were mapped later.",
        f"Legacy import: {issue_text}; details incomplete.",
    ]
    if random.random() < 0.025:
        return ""
    summary = random.choice(templates)
    if random.random() < 0.08:
        summary += random.choice([" Error code E2 noted.", " Photo attached.", " Customer unhappy.", " Need callback."])
    return summary


def _ticket_events(ticket: dict) -> list[dict]:
    created_at = date.fromisoformat(ticket["created_at"])
    event_id_base = ticket["ticket_id"].replace("TCK-", "TKE-")
    steps = [("created", created_at, "system")]
    last_at = created_at
    if ticket["status"] in {"in_progress", "pending_customer", "resolved"}:
        last_at = min(CURRENT_DATE, last_at + timedelta(days=random.randint(0, 2)))
        steps.append(("assigned", last_at, "support_agent"))
    if ticket["status"] in {"in_progress", "pending_customer", "resolved"}:
        last_at = min(CURRENT_DATE, last_at + timedelta(days=random.randint(0, 2)))
        steps.append(("first_response", last_at, "support_agent"))
    if ticket["status"] == "pending_customer":
        last_at = min(CURRENT_DATE, last_at + timedelta(days=random.randint(1, 5)))
        steps.append(("pending_customer", last_at, "support_agent"))
    if ticket["status"] == "resolved":
        last_at = min(CURRENT_DATE, last_at + timedelta(days=random.randint(2, 14)))
        steps.append(("resolved", last_at, "support_agent"))
    if ticket["parent_ticket_id"] and ticket["status"] != "open" and random.random() < 0.65:
        steps.insert(1, ("reopened", created_at, "customer"))

    return [
        {
            "event_id": f"{event_id_base}-{idx:02d}",
            "ticket_id": ticket["ticket_id"],
            "event_type": event_type,
            "happened_at": happened_at.isoformat(),
            "actor": actor,
            "note": random.choice([None, "", "customer replied", "SLA timer updated", "merged from email thread"]),
        }
        for idx, (event_type, happened_at, actor) in enumerate(steps, start=1)
    ]


def _make_ticket(ticket_id: str, parent_ticket_id: str | None, order: dict, item: dict, product: dict, customer: dict, issue_type: str, created_at: date) -> dict:
    priority = _priority_for_issue(issue_type, customer["segment"])
    order_id = order["order_id"]
    if parent_ticket_id is None and random.random() < 0.045:
        order_id = None
    return {
        "ticket_id": ticket_id,
        "parent_ticket_id": parent_ticket_id,
        "customer_id": customer["customer_id"],
        "product_id": product["product_id"],
        "order_id": order_id,
        "issue_type": issue_type,
        "priority": priority,
        "status": _ticket_status(created_at, priority),
        "created_at": created_at.isoformat(),
        "summary": _ticket_summary(product["name"], issue_type),
        "channel": random.choice(["email", "phone", "web", "chat", "marketplace"]),
        "assigned_team": random.choice(SUPPORT_TEAMS),
        "attachments_count": random.choices([0, 1, 2, 3, 5], weights=[62, 23, 9, 4, 2], k=1)[0],
        "customer_sentiment": random.choice(["neutral", "frustrated", "urgent", "confused", None]),
    }


def generate_tickets(customers: list[dict], products: list[dict], orders: list[dict], order_items: list[dict]) -> tuple[list[dict], list[dict]]:
    customer_by_id = {c["customer_id"]: c for c in customers}
    product_by_id = {p["product_id"]: p for p in products}
    candidates = _eligible_order_items(orders, order_items)
    tickets = []
    ticket_events = []
    ticket_index = 1
    root_keys = set()

    for order, item in candidates:
        product = product_by_id[item["product_id"]]
        if random.random() >= _ticket_probability(order, item, product):
            continue

        customer = customer_by_id[order["customer_id"]]
        issue_type = random.choice(_profile(product)["issues"])
        root_key = (order["order_id"], item["product_id"], issue_type)
        if root_key in root_keys:
            continue
        created_at = _ticket_date(date.fromisoformat(order["order_date"]))
        if created_at is None:
            continue
        ticket = _make_ticket(f"TCK-2026-{ticket_index:05d}", None, order, item, product, customer, issue_type, created_at)
        tickets.append(ticket)
        ticket_events.extend(_ticket_events(ticket))
        root_keys.add(root_key)
        ticket_index += 1

        repeat_probability = 0.08
        if ticket["priority"] in {"high", "urgent"}:
            repeat_probability += 0.08
        if issue_type in HARDWARE_ISSUES:
            repeat_probability += 0.05
        if random.random() < repeat_probability:
            follow_up_date = _ticket_date(date.fromisoformat(order["order_date"]), created_at)
            if follow_up_date is None:
                continue
            follow_up = _make_ticket(
                f"TCK-2026-{ticket_index:05d}",
                ticket["ticket_id"],
                order,
                item,
                product,
                customer,
                issue_type,
                follow_up_date,
            )
            follow_up["summary"] = f"跟进 {ticket['ticket_id']}：{follow_up['summary']}"
            follow_up["order_id"] = ticket["order_id"]
            tickets.append(follow_up)
            ticket_events.extend(_ticket_events(follow_up))
            ticket_index += 1

    if len(tickets) < MIN_TICKET_COUNT:
        shortfall = MIN_TICKET_COUNT - len(tickets)
        supplement_candidates = []
        for order, item in candidates:
            product = product_by_id[item["product_id"]]
            unused_issues = [
                issue
                for issue in _profile(product)["issues"]
                if (order["order_id"], item["product_id"], issue) not in root_keys
            ]
            if not unused_issues:
                continue
            supplement_candidates.append((order, item, unused_issues))

        for order, item, unused_issues in random.sample(
            supplement_candidates,
            k=min(shortfall, len(supplement_candidates)),
        ):
            product = product_by_id[item["product_id"]]
            customer = customer_by_id[order["customer_id"]]
            issue_type = random.choice(unused_issues)
            created_at = _ticket_date(date.fromisoformat(order["order_date"]))
            if created_at is None:
                continue
            ticket = _make_ticket(f"TCK-2026-{ticket_index:05d}", None, order, item, product, customer, issue_type, created_at)
            tickets.append(ticket)
            ticket_events.extend(_ticket_events(ticket))
            root_keys.add((order["order_id"], item["product_id"], issue_type))
            ticket_index += 1

    if len(tickets) < MIN_TICKET_COUNT:
        root_tickets = [ticket for ticket in tickets if ticket["parent_ticket_id"] is None]
        for parent in random.sample(root_tickets, k=min(MIN_TICKET_COUNT - len(tickets), len(root_tickets))):
            order = next(order for order in orders if order["order_id"] == parent["order_id"])
            item = next(
                item
                for item in order_items
                if item["order_id"] == parent["order_id"] and item["product_id"] == parent["product_id"]
            )
            product = product_by_id[parent["product_id"]]
            customer = customer_by_id[parent["customer_id"]]
            parent_date = date.fromisoformat(parent["created_at"])
            follow_up_date = _ticket_date(date.fromisoformat(order["order_date"]), parent_date)
            if follow_up_date is None:
                continue
            follow_up = _make_ticket(
                f"TCK-2026-{ticket_index:05d}",
                parent["ticket_id"],
                order,
                item,
                product,
                customer,
                parent["issue_type"],
                follow_up_date,
            )
            follow_up["summary"] = f"跟进 {parent['ticket_id']}：{follow_up['summary']}"
            follow_up["order_id"] = parent["order_id"]
            tickets.append(follow_up)
            ticket_events.extend(_ticket_events(follow_up))
            ticket_index += 1

    return tickets, ticket_events


def _eligible_warranty_tickets(tickets: list[dict], products: list[dict]) -> list[dict]:
    product_by_id = {p["product_id"]: p for p in products}
    eligible = []
    used_incident_keys = set()
    for ticket in tickets:
        if ticket["parent_ticket_id"] is not None:
            continue
        if ticket["order_id"] is None:
            continue
        incident_key = (ticket["order_id"], ticket["product_id"], ticket["issue_type"])
        if incident_key in used_incident_keys:
            continue
        product = product_by_id[ticket["product_id"]]
        profile = _profile(product)
        if ticket["issue_type"] in HARDWARE_ISSUES or ticket["priority"] in {"high", "urgent"}:
            if random.random() < profile["warranty_escalation_rate"]:
                eligible.append(ticket)
                used_incident_keys.add(incident_key)
    return eligible


def generate_warranty_cases(customers: list[dict], products: list[dict], orders: list[dict], tickets: list[dict]) -> list[dict]:
    order_by_id = {o["order_id"]: o for o in orders}
    product_by_id = {p["product_id"]: p for p in products}
    customer_by_id = {c["customer_id"]: c for c in customers}
    eligible = _eligible_warranty_tickets(tickets, products)
    if len(eligible) < WARRANTY_CASE_COUNT:
        eligible_incident_keys = {
            (ticket["order_id"], ticket["product_id"], ticket["issue_type"])
            for ticket in eligible
        }
        eligible_ids = {ticket["ticket_id"] for ticket in eligible}
        pool = []
        for ticket in tickets:
            incident_key = (ticket["order_id"], ticket["product_id"], ticket["issue_type"])
            if (
                ticket["ticket_id"] not in eligible_ids
                and ticket["parent_ticket_id"] is None
                and ticket["order_id"] is not None
                and incident_key not in eligible_incident_keys
                and (ticket["priority"] in {"high", "urgent"} or ticket["issue_type"] in HARDWARE_ISSUES)
            ):
                pool.append(ticket)
        eligible.extend(random.sample(pool, k=min(WARRANTY_CASE_COUNT - len(eligible), len(pool))))

    cases = []
    used_ticket_ids = set()
    used_incident_keys = set()
    for ticket in eligible:
        incident_key = (ticket["order_id"], ticket["product_id"], ticket["issue_type"])
        if (
            len(cases) >= WARRANTY_CASE_COUNT
            or ticket["ticket_id"] in used_ticket_ids
            or incident_key in used_incident_keys
        ):
            continue
        used_ticket_ids.add(ticket["ticket_id"])
        used_incident_keys.add(incident_key)
        order = order_by_id[ticket["order_id"]]
        product = product_by_id[ticket["product_id"]]
        customer = customer_by_id[ticket["customer_id"]]
        base_months = product["warranty_months"]
        extended = customer["segment"] == "Enterprise" and random.random() < 0.35
        warranty_months = base_months + 12 if extended else base_months
        expires_at = _add_months(date.fromisoformat(order["order_date"]), warranty_months)
        expired = expires_at < CURRENT_DATE
        coverage_type = "extended_warranty" if extended else "manufacturer_warranty"
        coverage_status = "expired" if expired else "in_warranty"
        if expired:
            status = random.choices(["expired", "denied"], weights=[84, 16], k=1)[0]
        else:
            status = random.choices(["active", "under_review", "denied"], weights=[70, 26, 4], k=1)[0]
        cases.append({
            "case_id": f"WAR-2026-{len(cases) + 1:05d}",
            "ticket_id": ticket["ticket_id"],
            "customer_id": ticket["customer_id"],
            "product_id": ticket["product_id"],
            "order_id": ticket["order_id"],
            "status": status,
            "coverage_type": coverage_type,
            "coverage_status": coverage_status,
            "expires_at": expires_at.isoformat(),
        })
    return cases


def main() -> None:
    random.seed(RANDOM_SEED)
    products = load_and_normalize_products()
    customers = generate_customers()
    orders, order_items, order_status_events = generate_orders_and_items(customers, products)
    tickets, ticket_events = generate_tickets(customers, products, orders, order_items)
    warranty_cases = generate_warranty_cases(customers, products, orders, tickets)

    _write_json("products", products)
    _write_json("customers", customers)
    _write_json("orders", orders)
    _write_json("order_items", order_items)
    _write_json("order_status_events", order_status_events)
    _write_json("tickets", tickets)
    _write_json("ticket_events", ticket_events)
    _write_json("warranty_cases", warranty_cases)

    print(f"customers: {len(customers)}")
    print(f"products: {len(products)}")
    print(f"orders: {len(orders)}")
    print(f"order_items: {len(order_items)}")
    print(f"order_status_events: {len(order_status_events)}")
    print(f"tickets: {len(tickets)}")
    print(f"ticket_events: {len(ticket_events)}")
    print(f"warranty_cases: {len(warranty_cases)}")


if __name__ == "__main__":
    main()
