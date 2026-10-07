#!/usr/bin/env python3
"""Local demo API for the Harbor & Bean café POS. Uses only Python's standard library."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import argparse
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "cafe_pos.db"
HTML_PATH = ROOT / "cafe-pos-prototype.html"

MENU = [
    ("espresso", "Espresso", "Coffee", 850, "☕", "Single shot"),
    ("americano", "Americano", "Coffee", 1050, "☕", "Smooth & bold"),
    ("cappuccino", "Cappuccino", "Coffee", 1450, "🥛", "Foam & espresso"),
    ("icedlatte", "Iced Latte", "Coffee", 1650, "🧋", "Chilled coffee"),
    ("tea", "Ceylon Tea", "Tea", 650, "🍵", "Pure black tea"),
    ("matcha", "Iced Matcha", "Tea", 1750, "🍵", "Matcha & milk"),
    ("croissant", "Butter Croissant", "Bakery", 980, "🥐", "Freshly baked"),
    ("brownie", "Chocolate Brownie", "Bakery", 1100, "🍫", "Fudge brownie"),
    ("cake", "Cheesecake", "Bakery", 1550, "🍰", "Slice of the day"),
    ("club", "Club Sandwich", "Meals", 2450, "🥪", "Chicken · fries"),
    ("toast", "Avocado Toast", "Meals", 2200, "🥑", "Sourdough · greens"),
    ("bowl", "Harvest Bowl", "Meals", 2650, "🥗", "Seasonal vegetables"),
]
SERVICE_RATE = 0.05

@contextmanager
def connect_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def initialize_db():
    with connect_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS menu_items (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
                price_lkr INTEGER NOT NULL CHECK(price_lkr >= 0), emoji TEXT NOT NULL,
                description TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY, order_type TEXT NOT NULL CHECK(order_type IN ('dinein','takeaway')),
                table_name TEXT, subtotal_lkr INTEGER NOT NULL, service_charge_lkr INTEGER NOT NULL,
                total_lkr INTEGER NOT NULL, status TEXT NOT NULL, payment_method TEXT NOT NULL,
                payment_status TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS order_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL REFERENCES orders(id),
                menu_item_id TEXT NOT NULL, item_name TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0),
                unit_price_lkr INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS payments (
                id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
                method TEXT NOT NULL, amount_lkr INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
            );
        """)
        count = db.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0]
        if count == 0:
            db.executemany("INSERT INTO menu_items(id,name,category,price_lkr,emoji,description) VALUES(?,?,?,?,?,?)", MENU)

def json_bytes(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")

class Handler(BaseHTTPRequestHandler):
    server_version = "CafePOSDemo/1.0"

    def send_json(self, status, value):
        body = json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 1_000_000:
                raise ValueError("Request body is empty or too large.")
            return json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Send a valid JSON request body.") from exc

    def do_GET(self):
        route = urlparse(self.path)
        if route.path == "/api/health":
            return self.send_json(200, {"status": "ok", "database": "SQLite local demo"})
        if route.path == "/api/menu":
            with connect_db() as db:
                rows = db.execute("SELECT id,name,category,price_lkr,emoji,description FROM menu_items WHERE active=1 ORDER BY category,name").fetchall()
            return self.send_json(200, [dict(row) for row in rows])
        if route.path == "/api/orders":
            params = parse_qs(route.query)
            limit = min(max(int(params.get("limit", ["50"])[0]), 1), 200)
            with connect_db() as db:
                orders = db.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
                result = []
                for order in orders:
                    item_rows = db.execute("SELECT menu_item_id,item_name,quantity,unit_price_lkr FROM order_lines WHERE order_id=?", (order["id"],)).fetchall()
                    result.append({**dict(order), "items": [dict(x) for x in item_rows]})
            return self.send_json(200, result)
        if route.path == "/":
            if not HTML_PATH.exists():
                return self.send_json(404, {"error": "POS page not found."})
            body = HTML_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return self.send_json(404, {"error": "Route not found."})

    def do_POST(self):
        if urlparse(self.path).path != "/api/orders":
            return self.send_json(404, {"error": "Route not found."})
        try:
            payload = self.read_json()
            order_type = payload.get("order_type")
            if order_type not in ("dinein", "takeaway"):
                raise ValueError("order_type must be dinein or takeaway.")
            table_name = payload.get("table_name") if order_type == "dinein" else None
            if order_type == "dinein" and not table_name:
                raise ValueError("Select a table for dine-in orders.")
            payment_method = payload.get("payment_method")
            if payment_method not in ("Cash", "Card terminal"):
                raise ValueError("Choose Cash or Card terminal.")
            requested = payload.get("items")
            if not isinstance(requested, list) or not requested:
                raise ValueError("Add at least one item to the order.")
            normalized = {}
            for line in requested:
                item_id = line.get("menu_item_id") if isinstance(line, dict) else None
                quantity = line.get("quantity") if isinstance(line, dict) else None
                if not isinstance(item_id, str) or not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 1000:
                    raise ValueError("Each item needs a valid menu_item_id and quantity from 1 to 1000.")
                normalized[item_id] = normalized.get(item_id, 0) + quantity
            order_id = "ORD-" + uuid.uuid4().hex[:8].upper()
            created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with connect_db() as db:
                db.execute("BEGIN IMMEDIATE")
                placeholders = ",".join("?" for _ in normalized)
                rows = db.execute("SELECT id,name,price_lkr FROM menu_items WHERE active=1 AND id IN (" + placeholders + ")", tuple(normalized)).fetchall()
                by_id = {row["id"]: row for row in rows}
                if len(by_id) != len(normalized):
                    raise ValueError("One or more menu items are unavailable. Refresh the menu and try again.")
                line_records = [(item_id, by_id[item_id]["name"], qty, by_id[item_id]["price_lkr"]) for item_id, qty in normalized.items()]
                subtotal = sum(qty * price for _, _, qty, price in line_records)
                service = round(subtotal * SERVICE_RATE) if order_type == "dinein" else 0
                total = subtotal + service
                db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?)", (order_id, order_type, table_name, subtotal, service, total, "completed", payment_method, "recorded_demo", created_at))
                db.executemany("INSERT INTO order_lines(order_id,menu_item_id,item_name,quantity,unit_price_lkr) VALUES(?,?,?,?,?)", [(order_id, *line) for line in line_records])
                db.execute("INSERT INTO payments VALUES(?,?,?,?,?,?)", (uuid.uuid4().hex, order_id, payment_method, total, "recorded_demo", created_at))
                db.commit()
            return self.send_json(201, {
                "id": order_id, "order_type": order_type, "table_name": table_name,
                "subtotal_lkr": subtotal, "service_charge_lkr": service, "total_lkr": total,
                "payment_method": payment_method, "payment_status": "recorded_demo", "created_at": created_at,
                "items": [{"menu_item_id": item_id, "item_name": name, "quantity": qty, "unit_price_lkr": price, "line_total_lkr": qty * price} for item_id, name, qty, price in line_records]
            })
        except ValueError as exc:
            return self.send_json(400, {"error": str(exc)})
        except Exception:
            return self.send_json(500, {"error": "Could not save the order. Check the server log."})

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

def main():
    parser = argparse.ArgumentParser(description="Run the local café POS API demo")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: local computer only)")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    initialize_db()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("Café POS demo running at http://%s:%s" % (args.host, args.port))
    print("Press Ctrl+C to stop. This demo is for local use; do not expose it to the internet.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping POS API.")
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
