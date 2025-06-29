from .notifications import send_report
from .services import consume_order_stock, get_sales_summary
from magazyn import DB_PATH
from .config import settings, load_config
import os
import json
import base64
import subprocess
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo
import requests


class ConfigError(Exception):
    """Raised when required configuration is missing."""


def parse_time_str(value: str) -> dt_time:
    """Return time from ``HH:MM`` or raise ``ValueError``."""
    try:
        return dt_time.fromisoformat(value)
    except ValueError as e:
        raise ValueError(f"Invalid time value: {value}") from e


API_TOKEN = settings.API_TOKEN
PAGE_ACCESS_TOKEN = settings.PAGE_ACCESS_TOKEN
RECIPIENT_ID = settings.RECIPIENT_ID
STATUS_ID = settings.STATUS_ID
PRINTER_NAME = settings.PRINTER_NAME
CUPS_SERVER = settings.CUPS_SERVER
CUPS_PORT = settings.CUPS_PORT
POLL_INTERVAL = settings.POLL_INTERVAL
QUIET_HOURS_START = parse_time_str(settings.QUIET_HOURS_START)
QUIET_HOURS_END = parse_time_str(settings.QUIET_HOURS_END)
TIMEZONE = settings.TIMEZONE
BASE_URL = "https://api.baselinker.com/connector.php"
PRINTED_FILE = os.path.join(os.path.dirname(__file__), "printed_orders.txt")
PRINTED_EXPIRY_DAYS = settings.PRINTED_EXPIRY_DAYS
LABEL_QUEUE = os.path.join(os.path.dirname(__file__), "queued_labels.jsonl")
LOG_LEVEL = settings.LOG_LEVEL
# Use the same database file as the web application
DB_FILE = DB_PATH
# Location of the legacy database used by the standalone printer agent
OLD_DB_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, "printer", "data.db")
)
LOG_FILE = settings.LOG_FILE

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

HEADERS = {
    "X-BLToken": API_TOKEN,
    "Content-Type": "application/x-www-form-urlencoded",
}


def reload_env():
    """Reload environment variables and update globals."""
    global settings
    settings = load_config()
    global API_TOKEN, PAGE_ACCESS_TOKEN, RECIPIENT_ID, STATUS_ID, PRINTER_NAME
    global CUPS_SERVER, CUPS_PORT, POLL_INTERVAL, QUIET_HOURS_START
    global QUIET_HOURS_END, TIMEZONE, PRINTED_EXPIRY_DAYS, LOG_LEVEL
    global LOG_FILE, DB_FILE
    API_TOKEN = settings.API_TOKEN
    PAGE_ACCESS_TOKEN = settings.PAGE_ACCESS_TOKEN
    RECIPIENT_ID = settings.RECIPIENT_ID
    STATUS_ID = settings.STATUS_ID
    PRINTER_NAME = settings.PRINTER_NAME
    CUPS_SERVER = settings.CUPS_SERVER
    CUPS_PORT = settings.CUPS_PORT
    POLL_INTERVAL = settings.POLL_INTERVAL
    QUIET_HOURS_START = parse_time_str(settings.QUIET_HOURS_START)
    QUIET_HOURS_END = parse_time_str(settings.QUIET_HOURS_END)
    TIMEZONE = settings.TIMEZONE
    PRINTED_EXPIRY_DAYS = settings.PRINTED_EXPIRY_DAYS
    old_log_file = LOG_FILE
    LOG_LEVEL = settings.LOG_LEVEL
    LOG_FILE = settings.LOG_FILE
    DB_FILE = settings.DB_PATH
    HEADERS["X-BLToken"] = API_TOKEN

    from . import db

    db.configure_engine(DB_FILE)

    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    if old_log_file != LOG_FILE:
        root_logger = logging.getLogger()
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"
        )
        for h in list(root_logger.handlers):
            if isinstance(h, logging.FileHandler):
                root_logger.removeHandler(h)
                h.close()
        file_handler = logging.FileHandler(LOG_FILE)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def reload_config():
    """Reload configuration from .env and update globals."""
    reload_env()


last_order_data = {}
_agent_thread = None
# Timestamps for last periodic reports
_last_weekly_report = None
_last_monthly_report = None
# Event used to signal the agent loop to exit
_stop_event = threading.Event()


def validate_env():
    required = {
        "API_TOKEN": API_TOKEN,
        "PAGE_ACCESS_TOKEN": PAGE_ACCESS_TOKEN,
        "RECIPIENT_ID": RECIPIENT_ID,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        logger.error(
            "Brak wymaganych zmiennych środowiskowych: %s", ", ".join(missing)
        )
        raise ConfigError(
            "Missing environment variables: " + ", ".join(missing)
        )


def ensure_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS printed_orders("
        "order_id TEXT PRIMARY KEY, printed_at TEXT, last_order_data TEXT)"
    )
    cur.execute("PRAGMA table_info(printed_orders)")
    cols = [row[1] for row in cur.fetchall()]
    if "last_order_data" not in cols:
        cur.execute(
            "ALTER TABLE printed_orders ADD COLUMN last_order_data TEXT"
        )
        conn.commit()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS label_queue("
        "order_id TEXT, label_data TEXT, ext TEXT, last_order_data TEXT)"
    )
    conn.commit()

    if os.path.exists(PRINTED_FILE):
        cur.execute("SELECT COUNT(*) FROM printed_orders")
        if cur.fetchone()[0] == 0:
            with open(PRINTED_FILE, "r") as f:
                for line in f:
                    if "," in line:
                        oid, ts = line.strip().split(",")
                        cur.execute(
                            "INSERT OR IGNORE INTO printed_orders("
                            "order_id, printed_at) VALUES (?, ?)",
                            (oid, ts),
                        )
            conn.commit()
    if os.path.exists(LABEL_QUEUE):
        cur.execute("SELECT COUNT(*) FROM label_queue")
        if cur.fetchone()[0] == 0:
            with open(LABEL_QUEUE, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                        cur.execute(
                            "INSERT INTO label_queue("
                            "order_id, label_data, ext, last_order_data)"
                            " VALUES (?, ?, ?, ?)",
                            (
                                item.get("order_id"),
                                item.get("label_data"),
                                item.get("ext"),
                                json.dumps(item.get("last_order_data", {})),
                            ),
                        )
                    except Exception as e:
                        logger.error(f"Błąd migracji z {LABEL_QUEUE}: {e}")
            conn.commit()

    # migrate data from old standalone database if present and tables are empty
    if os.path.exists(OLD_DB_FILE):
        try:
            old_conn = sqlite3.connect(OLD_DB_FILE)
            old_cur = old_conn.cursor()
            for table, cols in (
                ("printed_orders", 3),
                ("label_queue", 4),
            ):
                old_cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
                if not old_cur.fetchone():
                    continue
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                if cur.fetchone()[0] == 0:
                    placeholders = ",".join(["?"] * cols)
                    for row in old_cur.execute(f"SELECT * FROM {table}"):
                        cur.execute(
                            f"INSERT INTO {table} VALUES ({placeholders})",
                            row,
                        )
            conn.commit()
            old_conn.close()
        except Exception as e:
            logger.error(f"B\u0142\u0105d migracji z {OLD_DB_FILE}: {e}")
    conn.close()


def ensure_db_init():
    ensure_db()


def load_printed_orders():
    """Return printed orders sorted by newest first."""
    ensure_db()
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "SELECT order_id, printed_at, last_order_data FROM printed_orders ORDER BY printed_at DESC"
    )
    rows = cur.fetchall()
    conn.close()
    items = []
    for oid, ts, data_json in rows:
        try:
            data = json.loads(data_json) if data_json else {}
        except Exception:
            data = {}
        items.append(
            {
                "order_id": oid,
                "printed_at": datetime.fromisoformat(ts),
                "last_order_data": data,
            }
        )
    return items


def mark_as_printed(order_id, last_order_data=None):
    """Record that an order's labels were printed."""
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    data_json = json.dumps(last_order_data or {})
    cur.execute(
        "INSERT OR IGNORE INTO printed_orders(order_id, printed_at, last_order_data) VALUES (?, ?, ?)",
        (order_id, datetime.now().isoformat(), data_json),
    )
    cur.execute(
        "UPDATE printed_orders SET last_order_data=? WHERE order_id=?",
        (data_json, order_id),
    )
    conn.commit()
    conn.close()


def clean_old_printed_orders():
    threshold = datetime.now() - timedelta(days=PRINTED_EXPIRY_DAYS)
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM printed_orders WHERE printed_at < ?",
        (threshold.isoformat(),),
    )
    conn.commit()
    conn.close()


def load_queue():
    ensure_db()
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "SELECT order_id, label_data, ext, last_order_data FROM label_queue"
    )
    rows = cur.fetchall()
    conn.close()
    items = []
    for order_id, label_data, ext, last_order_json in rows:
        try:
            last_data = json.loads(last_order_json) if last_order_json else {}
        except Exception:
            last_data = {}
        items.append(
            {
                "order_id": order_id,
                "label_data": label_data,
                "ext": ext,
                "last_order_data": last_data,
            }
        )
    return items


def save_queue(items):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM label_queue")
    for item in items:
        cur.execute(
            "INSERT INTO label_queue(order_id, label_data, ext, last_order_data) VALUES (?, ?, ?, ?)",
            (
                item.get("order_id"),
                item.get("label_data"),
                item.get("ext"),
                json.dumps(item.get("last_order_data", {})),
            ),
        )
    conn.commit()
    conn.close()


def call_api(method, parameters=None):
    parameters = parameters or {}
    try:
        payload = {"method": method, "parameters": json.dumps(parameters)}
        response = requests.post(
            BASE_URL, headers=HEADERS, data=payload, timeout=10
        )
        response.raise_for_status()
        logger.info(f"[{method}] {response.status_code}")
        return response.json()
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error in call_api({method}): {e}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error in call_api({method}): {e}")
    except Exception as e:
        logger.error(f"Błąd w call_api({method}): {e}")
    return {}


def get_orders():
    response = call_api("getOrders", {"status_id": STATUS_ID})
    logger.info(
        "🔁 Surowa odpowiedź:\n%s",
        json.dumps(response, indent=2, ensure_ascii=False),
    )
    orders = response.get("orders", [])
    logger.info(f"🔍 Zamówień znalezionych: {len(orders)}")
    return orders


def get_order_packages(order_id):
    response = call_api("getOrderPackages", {"order_id": order_id})
    return response.get("packages", [])


def get_label(courier_code, package_id):
    response = call_api(
        "getLabel", {"courier_code": courier_code, "package_id": package_id}
    )
    return response.get("label"), response.get("extension", "pdf")


def print_label(base64_data, extension, order_id):
    try:
        file_path = f"/tmp/label_{order_id}.{extension}"
        pdf_data = base64.b64decode(base64_data)
        with open(file_path, "wb") as f:
            f.write(pdf_data)
        cmd = ["lp"]
        host = None
        if CUPS_SERVER or CUPS_PORT:
            server = CUPS_SERVER or "localhost"
            host = f"{server}:{CUPS_PORT}" if CUPS_PORT else server
        if host:
            cmd.extend(["-h", host])
        cmd.extend(["-d", PRINTER_NAME, file_path])
        result = subprocess.run(cmd, capture_output=True)
        os.remove(file_path)
        if result.returncode != 0:
            logger.error(
                "Błąd drukowania (kod %s): %s",
                result.returncode,
                result.stderr.decode().strip(),
            )
        else:
            logger.info(f"📨 Etykieta wydrukowana dla zamówienia {order_id}")
    except Exception as e:
        logger.error(f"Błąd drukowania: {e}")


def print_test_page():
    try:
        file_path = "/tmp/print_test.txt"
        with open(file_path, "w") as f:
            f.write("=== TEST PRINT ===\n")
        result = subprocess.run(
            ["lp", "-d", PRINTER_NAME, file_path], capture_output=True
        )
        os.remove(file_path)
        if result.returncode != 0:
            logger.error(
                "Błąd testowego druku (kod %s): %s",
                result.returncode,
                result.stderr.decode().strip(),
            )
            return False
        logger.info("🔧 Testowa strona została wysłana do drukarki.")
        return True
    except Exception as e:
        logger.error(f"Błąd testowego druku: {e}")
        return False


def shorten_product_name(full_name):
    words = full_name.strip().split()
    if len(words) >= 3:
        return f"{words[0]} {' '.join(words[-2:])}"
    return full_name


def send_messenger_message(data):
    try:
        message = (
            f"📦 Nowe zamówienie od: {data.get('name', '-')}\n"
            f"🛒 Produkty:\n"
            + "".join(
                f"- {shorten_product_name(p['name'])} (x{p['quantity']})\n"
                for p in data.get("products", [])
            )
            + f"🚚 Wysyłka: {data.get('shipping', '-')}\n"
            f"🌐 Platforma: {data.get('platform', '-')}\n"
            f"📎 ID: {data.get('order_id', '-')}"
        )

        response = requests.post(
            "https://graph.facebook.com/v17.0/me/messages",
            headers={
                "Authorization": f"Bearer {PAGE_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            data=json.dumps(
                {
                    "recipient": {"id": RECIPIENT_ID},
                    "message": {"text": message},
                }
            ),
        )
        logger.info(
            "📬 Messenger response: %s %s", response.status_code, response.text
        )
        response.raise_for_status()
        logger.info("✅ Wiadomość została wysłana przez Messengera.")
    except Exception as e:
        logger.error(f"Błąd wysyłania wiadomości: {e}")


def is_quiet_time():
    now = datetime.now(ZoneInfo(TIMEZONE)).time()
    start = QUIET_HOURS_START
    end = QUIET_HOURS_END
    if start <= end:
        return start <= now < end
    else:
        return now >= start or now < end


def _send_periodic_reports():
    global _last_weekly_report, _last_monthly_report
    now = datetime.now()
    if not _last_weekly_report or now - _last_weekly_report >= timedelta(
        days=7
    ):
        report = get_sales_summary(7)
        lines = [
            f"- {r['name']} {r['size']}: sprzedano {r['sold']}, zostalo {r['remaining']}"
            for r in report
        ]
        send_report("Raport tygodniowy", lines)
        _last_weekly_report = now
    if not _last_monthly_report or now - _last_monthly_report >= timedelta(
        days=30
    ):
        report = get_sales_summary(30)
        lines = [
            f"- {r['name']} {r['size']}: sprzedano {r['sold']}, zostalo {r['remaining']}"
            for r in report
        ]
        send_report("Raport miesieczny", lines)
        _last_monthly_report = now


def _agent_loop():
    while not _stop_event.is_set():
        _send_periodic_reports()
        clean_old_printed_orders()
        printed_entries = load_printed_orders()
        printed = {e["order_id"]: e["printed_at"] for e in printed_entries}
        queue = load_queue()

        if not is_quiet_time():
            grouped = {}
            for item in queue:
                grouped.setdefault(item["order_id"], []).append(item)

            new_queue = []
            for oid, items in grouped.items():
                try:
                    for it in items:
                        print_label(
                            it["label_data"],
                            it.get("ext", "pdf"),
                            it["order_id"],
                        )
                    consume_order_stock(
                        items[0].get("last_order_data", {}).get("products", [])
                    )
                    mark_as_printed(oid, items[0].get("last_order_data"))
                    printed[oid] = datetime.now()
                except Exception as e:
                    logger.error(f"Błąd przetwarzania z kolejki: {e}")
                    new_queue.extend(items)

            queue = new_queue
            save_queue(queue)

        try:
            orders = get_orders()
            for order in orders:
                order_id = str(order["order_id"])

                global last_order_data
                last_order_data = {
                    "order_id": order_id,
                    "name": order.get("delivery_fullname", "Nieznany klient"),
                    "platform": order.get("order_source", "brak"),
                    "shipping": order.get("delivery_method", "brak"),
                    "products": order.get("products", []),
                }

                if order_id in printed:
                    continue

                logger.info(
                    f"📜 Zamówienie {order_id} ({last_order_data['name']})"
                )
                packages = get_order_packages(order_id)
                labels = []

                for p in packages:
                    package_id = p.get("package_id")
                    courier_code = p.get("courier_code")
                    if not package_id or not courier_code:
                        logger.warning(
                            "  Brak danych: package_id lub courier_code"
                        )
                        continue

                    logger.info(
                        f"  📦 Paczka {package_id} (kurier: {courier_code})"
                    )

                    label_data, ext = get_label(courier_code, package_id)
                    if label_data:
                        labels.append((label_data, ext))
                    else:
                        logger.warning(
                            "  ❌ Brak etykiety (label_data = null)"
                        )

                if labels:
                    if is_quiet_time():
                        logger.info(
                            "🕒 Cisza nocna — etykiety nie zostaną wydrukowane teraz."
                        )
                        for label_data, ext in labels:
                            queue.append(
                                {
                                    "order_id": order_id,
                                    "label_data": label_data,
                                    "ext": ext,
                                    "last_order_data": last_order_data,
                                }
                            )
                        send_messenger_message(last_order_data)
                        mark_as_printed(order_id, last_order_data)
                        printed[order_id] = datetime.now()
                    else:
                        for label_data, ext in labels:
                            print_label(label_data, ext, order_id)
                        consume_order_stock(
                            last_order_data.get("products", [])
                        )
                        send_messenger_message(last_order_data)
                        mark_as_printed(order_id, last_order_data)
                        printed[order_id] = datetime.now()

        except Exception as e:
            logger.error(f"[BŁĄD GŁÓWNY] {e}")

        save_queue(queue)
        _stop_event.wait(POLL_INTERVAL)


def start_agent_thread():
    global _agent_thread, _stop_event
    if _agent_thread and _agent_thread.is_alive():
        return
    _stop_event = threading.Event()
    _agent_thread = threading.Thread(target=_agent_loop, daemon=True)
    _agent_thread.start()


def stop_agent_thread():
    """Signal the agent loop to stop and wait for it to finish."""
    global _agent_thread
    if _agent_thread and _agent_thread.is_alive():
        _stop_event.set()
        _agent_thread.join()
        _agent_thread = None
