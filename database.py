import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash

DB_NAME = "database.db"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Farmers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS farmers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            mobile TEXT NOT NULL,
            village TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Customers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            mobile TEXT NOT NULL,
            address TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Products table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            stock_kg REAL DEFAULT 0.0,
            opening_stock_kg REAL DEFAULT 0.0
        )
    ''')

    # Purchases table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            farmer_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            lots REAL NOT NULL,
            kg REAL NOT NULL,
            rate_per_kg REAL NOT NULL,
            quality TEXT,
            moisture REAL DEFAULT 0,
            lot_number TEXT,
            transport_charges REAL DEFAULT 0,
            other_charges REAL DEFAULT 0,
            gross_amount REAL NOT NULL,
            net_payable REAL NOT NULL,
            paid_amount REAL DEFAULT 0,
            remaining_amount REAL NOT NULL,
            payment_status TEXT NOT NULL,
            payment_method TEXT,
            notes TEXT,
            FOREIGN KEY (farmer_id) REFERENCES farmers(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    ''')

    # Sales table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            customer_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            lots REAL NOT NULL,
            kg REAL NOT NULL,
            selling_rate_per_kg REAL NOT NULL,
            purchase_cost_per_kg REAL NOT NULL,
            gross_amount REAL NOT NULL,
            discount REAL DEFAULT 0,
            transport_charges REAL DEFAULT 0,
            other_charges REAL DEFAULT 0,
            final_amount REAL NOT NULL,
            paid_amount REAL DEFAULT 0,
            remaining_amount REAL NOT NULL,
            payment_status TEXT NOT NULL,
            payment_method TEXT,
            profit REAL NOT NULL,
            notes TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    ''')

    # Stock Transactions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            type TEXT NOT NULL, -- 'Opening', 'Purchase', 'Sale', 'Adjustment'
            ref_id INTEGER,
            inward_kg REAL DEFAULT 0,
            outward_kg REAL DEFAULT 0,
            balance_kg REAL NOT NULL,
            notes TEXT,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    ''')

    # Ledger table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            party_type TEXT NOT NULL, -- 'Farmer' or 'Customer'
            party_id INTEGER NOT NULL,
            type TEXT NOT NULL, -- 'Purchase', 'Sale', 'Payment', 'Adjustment'
            ref_id INTEGER,
            description TEXT,
            debit REAL DEFAULT 0,
            credit REAL DEFAULT 0,
            balance REAL NOT NULL
        )
    ''')

    # Payments table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            party_type TEXT NOT NULL, -- 'Farmer' or 'Customer'
            party_id INTEGER NOT NULL,
            ref_type TEXT NOT NULL, -- 'Purchase' or 'Sale'
            ref_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            method TEXT NOT NULL,
            ref_number TEXT,
            notes TEXT
        )
    ''')

    # Initial default settings
    default_settings = {
        'business_name': 'RAMDEV',
        'shop_no': '230/D',
        'market': 'Unjha APMC',
        'business_type': 'Jeera & Variyali Trading',
        'location': 'Unjha APMC, Gujarat, India',
        'mobile': '+91 98765 43210',
        'email': 'contact@ramdevmandi.com',
        'gst_no': '24AAAAA0000A1Z5',
        'lot_weight_kg': '20'
    }

    for key, val in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, val))

    # Initial Users
    admin_pw = generate_password_hash("admin123")
    cursor.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)", ("admin", admin_pw, "Admin"))
    staff_pw = generate_password_hash("staff123")
    cursor.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)", ("staff", staff_pw, "Staff"))

    # Initial Products
    cursor.execute("INSERT OR IGNORE INTO products (id, name, stock_kg, opening_stock_kg) VALUES (1, 'Jeera', 1000.0, 1000.0)")
    cursor.execute("INSERT OR IGNORE INTO products (id, name, stock_kg, opening_stock_kg) VALUES (2, 'Variyali', 800.0, 800.0)")

    # Seed Sample Data if empty
    cursor.execute("SELECT COUNT(*) FROM farmers")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO farmers (name, mobile, village) VALUES ('Ramesh Patel', '9898012345', 'Unjha')")
        cursor.execute("INSERT INTO farmers (name, mobile, village) VALUES ('Mahesh Patel', '9898023456', 'Bhandu')")
        cursor.execute("INSERT INTO farmers (name, mobile, village) VALUES ('Dinesh Chaudhary', '9898034567', 'Visnagar')")

        cursor.execute("INSERT INTO customers (name, mobile, address) VALUES ('Shree Trading Co.', '9727011111', 'Ahmedabad')")
        cursor.execute("INSERT INTO customers (name, mobile, address) VALUES ('Patel Spices', '9727022222', 'Unjha')")
        cursor.execute("INSERT INTO customers (name, mobile, address) VALUES ('Gujarat Masala', '9727033333', 'Rajkot')")

        # Stock Trans for opening
        cursor.execute("INSERT INTO stock_transactions (date, product_id, type, inward_kg, balance_kg, notes) VALUES (?, 1, 'Opening', 1000, 1000, 'Initial Stock')", (datetime.now().strftime("%Y-%m-%d"),))
        cursor.execute("INSERT INTO stock_transactions (date, product_id, type, inward_kg, balance_kg, notes) VALUES (?, 2, 'Opening', 800, 800, 'Initial Stock')", (datetime.now().strftime("%Y-%m-%d"),))

    conn.commit()
    conn.close()

def get_setting(key, default=""):
    conn = get_db_connection()
    res = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return res['value'] if res else default

def get_lot_weight():
    try:
        return float(get_setting('lot_weight_kg', '20'))
    except ValueError:
        return 20.0

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")