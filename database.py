import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

DB_NAME = "hardware.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Table 1: Products Inventory & Prices
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            sku TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            unit TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER NOT NULL
        )
    """)

    # Table 2: Customers / Contractors
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact TEXT NOT NULL,
            customer_type TEXT NOT NULL
        )
    """)
    
    # Table 3: Sales & Credit Invoices
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_no TEXT NOT NULL,
            sku TEXT NOT NULL,
            product_name TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            qty_sold INTEGER NOT NULL,
            total_amount REAL NOT NULL,
            payment_method TEXT NOT NULL,
            payment_status TEXT NOT NULL,
            due_date TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (sku) REFERENCES products (sku)
        )
    """)

    # Table 4: System Users (Authentication)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)

    if cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        sample_users = [
            ("admin", "RK Store Manager", "Admin", generate_password_hash("admin123")),
            ("cashier", "Front Desk Cashier", "Cashier", generate_password_hash("cashier123")),
        ]
        cursor.executemany(
            "INSERT INTO users (username, full_name, role, password_hash) VALUES (?, ?, ?, ?)",
            sample_users
        )
    
    if cursor.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        sample_items = [
            ("HW-101", "Republic Portland Cement (40kg)", "Construction", "Bag", 245.00, 45),
            ("HW-102", "Deformed Steel Bar 10mm x 6m", "Construction", "Piece", 185.00, 60),
            ("HW-103", "Marine Plywood 1/4 x 4 x 8", "Lumber & Boards", "Sheet", 460.00, 18),
            ("HW-104", "Common Wire Nails 2-inch", "Fasteners", "Kilo", 75.00, 25),
            ("HW-105", "Neltex PVC Pipe 1/2-inch Blue", "Plumbing", "Length", 110.00, 30),
            ("HW-106", "Boysen Permacoat Latex White", "Paint & Finish", "Gallon", 695.00, 4),
            ("HW-107", "Phelps Dodge THHN Wire #12", "Electrical", "Meter", 42.00, 120),
            ("HW-108", "Stanley Claw Hammer 16oz", "Hand Tools", "Piece", 380.00, 3),
        ]
        cursor.executemany(
            "INSERT INTO products (sku, name, category, unit, price, stock) VALUES (?, ?, ?, ?, ?, ?)",
            sample_items
        )

    if cursor.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
        sample_customers = [
            ("Walk-in Cash Customer", "N/A", "Retail"),
            ("Engr. Marco Reyes (Reyes Builders)", "0917-555-0192", "Contractor"),
            ("San Fernando Construction Corp.", "0918-442-8831", "Wholesale"),
            ("Juan Dela Cruz", "0920-331-7740", "Retail"),
        ]
        cursor.executemany(
            "INSERT INTO customers (name, contact, customer_type) VALUES (?, ?, ?)",
            sample_customers
        )

    if cursor.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0:
        sample_sales = [
            ("RCP-1001", "HW-101", "Republic Portland Cement (40kg)", "Engr. Marco Reyes (Reyes Builders)", 10, 2450.00, "Cash", "Paid", "N/A", "2026-11-12 09:15 AM"),
            ("RCP-1002", "HW-102", "Deformed Steel Bar 10mm x 6m", "San Fernando Construction Corp.", 15, 2775.00, "Cash", "Paid", "N/A", "2026-11-13 02:30 PM"),
            ("RCP-1003", "HW-103", "Marine Plywood 1/4 x 4 x 8", "Walk-in Cash Customer", 4, 1840.00, "Cash", "Paid", "N/A", "2026-11-14 11:05 AM"),
            ("INV-1004", "HW-106", "Boysen Permacoat Latex White", "Engr. Marco Reyes (Reyes Builders)", 6, 4170.00, "Credit Invoice", "Unpaid (Loan)", "2026-12-01", "2026-11-15 04:20 PM"),
            ("RCP-1005", "HW-107", "Phelps Dodge THHN Wire #12", "San Fernando Construction Corp.", 80, 3360.00, "Cash", "Paid", "N/A", "2026-11-16 10:45 AM"),
            ("RCP-1006", "HW-101", "Republic Portland Cement (40kg)", "Juan Dela Cruz", 22, 5390.00, "Cash", "Paid", "N/A", "2026-11-17 01:10 PM"),
        ]
        cursor.executemany(
            """INSERT INTO sales 
               (invoice_no, sku, product_name, customer_name, qty_sold, total_amount, payment_method, payment_status, due_date, timestamp) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            sample_sales
        )
        
    conn.commit()
    conn.close()

# --- USER AUTHENTICATION ---
def verify_user(username, password):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip().lower(),)).fetchone()
    conn.close()
    if user and check_password_hash(user["password_hash"], password):
        return dict(user)
    return None

# --- PRODUCT CRUD ---
def get_all_products():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM products").fetchall()
    conn.close()
    return [dict(row) for row in rows]

def add_or_update_product(sku, name, category, unit, price, stock):
    conn = sqlite3.connect(DB_NAME)
    conn.execute(
        "INSERT OR REPLACE INTO products (sku, name, category, unit, price, stock) VALUES (?, ?, ?, ?, ?, ?)",
        (sku.upper(), name, category, unit, float(price), int(stock))
    )
    conn.commit()
    conn.close()

def update_price(sku, new_price):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("UPDATE products SET price = ? WHERE sku = ?", (float(new_price), sku.upper()))
    conn.commit()
    conn.close()

def update_stock(sku, new_stock):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("UPDATE products SET stock = ? WHERE sku = ?", (int(new_stock), sku.upper()))
    conn.commit()
    conn.close()

def delete_product(sku):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM products WHERE sku = ?", (sku.upper(),))
    conn.commit()
    conn.close()

# --- CUSTOMER CRUD ---
def get_all_customers():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM customers ORDER BY customer_id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]

def add_customer(name, contact, customer_type):
    conn = sqlite3.connect(DB_NAME)
    conn.execute(
        "INSERT INTO customers (name, contact, customer_type) VALUES (?, ?, ?)",
        (name, contact, customer_type)
    )
    conn.commit()
    conn.close()

def delete_customer(customer_id):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM customers WHERE customer_id = ?", (customer_id,))
    conn.commit()
    conn.close()

# --- SALES & INVOICE CRUD ---
def record_sale(invoice_no, sku, product_name, customer_name, qty_sold, total_amount, payment_method, payment_status, due_date):
    conn = sqlite3.connect(DB_NAME)
    now = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    conn.execute(
        """INSERT INTO sales 
           (invoice_no, sku, product_name, customer_name, qty_sold, total_amount, payment_method, payment_status, due_date, timestamp) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (invoice_no, sku.upper(), product_name, customer_name, int(qty_sold), float(total_amount), payment_method, payment_status, due_date, now)
    )
    conn.commit()
    conn.close()

def mark_invoice_paid(sale_id):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("UPDATE sales SET payment_status = 'Paid', due_date = 'Settled' WHERE sale_id = ?", (sale_id,))
    conn.commit()
    conn.close()

def get_all_sales():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM sales ORDER BY sale_id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_sale_by_id(sale_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM sales WHERE sale_id = ?", (sale_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def delete_sale_by_id(sale_id):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM sales WHERE sale_id = ?", (sale_id,))
    conn.commit()
    conn.close()

def delete_last_sale():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM sales WHERE sale_id = (SELECT MAX(sale_id) FROM sales)")
    conn.commit()
    conn.close()