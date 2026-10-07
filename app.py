from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
import sqlite3
from datetime import datetime, date
import io
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from database import init_db, get_db_connection, get_setting, get_lot_weight

app = Flask(__name__)
app.secret_key = "ramdev_mandi_secret_key_2026"

# Ensure DB initialized
init_db()

# Global Context Processor
@app.context_processor
def inject_global_vars():
    business_info = {
        'name': get_setting('business_name', 'RAMDEV'),
        'shop_no': get_setting('shop_no', '230/D'),
        'market': get_setting('market', 'Unjha APMC'),
        'type': get_setting('business_type', 'Jeera & Variyali Trading'),
        'location': get_setting('location', 'Unjha APMC, Gujarat, India'),
        'mobile': get_setting('mobile', ''),
        'email': get_setting('email', ''),
        'gst_no': get_setting('gst_no', ''),
        'lot_weight': get_lot_weight()
    }
    return dict(biz=business_info)

# Login Decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'Admin':
            flash("Access denied. Admin privileges required.", "danger")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# Helper: Recalculate Ledger Running Balance
def recalculate_ledger(party_type, party_id):
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT * FROM ledger 
        WHERE party_type = ? AND party_id = ? 
        ORDER BY date ASC, id ASC
    """, (party_type, party_id)).fetchall()

    balance = 0.0
    for row in rows:
        balance += (row['debit'] - row['credit'])
        conn.execute("UPDATE ledger SET balance = ? WHERE id = ?", (balance, row['id']))
    conn.commit()
    conn.close()

# --- AUTH ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()

        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid Username or Password.", "danger")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for('login'))

# --- DASHBOARD ---
@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    today_str = date.today().strftime('%Y-%m-%d')

    # Stock
    jeera = conn.execute("SELECT stock_kg FROM products WHERE name = 'Jeera'").fetchone()
    variyali = conn.execute("SELECT stock_kg FROM products WHERE name = 'Variyali'").fetchone()
    lot_w = get_lot_weight()

    jeera_kg = jeera['stock_kg'] if jeera else 0
    variyali_kg = variyali['stock_kg'] if variyali else 0

    jeera_lots = jeera_kg / lot_w
    variyali_lots = variyali_kg / lot_w

    # Today's Purchases
    today_purchases = conn.execute("SELECT COUNT(*) as count, SUM(kg) as total_kg, SUM(net_payable) as total_amt FROM purchases WHERE date = ?", (today_str,)).fetchone()
    # Today's Sales
    today_sales = conn.execute("SELECT COUNT(*) as count, SUM(kg) as total_kg, SUM(final_amount) as total_amt, SUM(profit) as total_profit FROM sales WHERE date = ?", (today_str,)).fetchone()

    # Pending Payments
    pending_p = conn.execute("SELECT SUM(remaining_amount) FROM purchases WHERE payment_status != 'Paid'").fetchone()[0] or 0
    pending_s = conn.execute("SELECT SUM(remaining_amount) FROM sales WHERE payment_status != 'Paid'").fetchone()[0] or 0

    # Counts
    total_farmers = conn.execute("SELECT COUNT(*) FROM farmers").fetchone()[0]
    total_customers = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]

    # Recent Purchases & Sales
    recent_purchases = conn.execute("""
        SELECT p.*, f.name as farmer_name, pr.name as product_name 
        FROM purchases p 
        JOIN farmers f ON p.farmer_id = f.id 
        JOIN products pr ON p.product_id = pr.id 
        ORDER BY p.id DESC LIMIT 5
    """).fetchall()

    recent_sales = conn.execute("""
        SELECT s.*, c.name as customer_name, pr.name as product_name 
        FROM sales s 
        JOIN customers c ON s.customer_id = c.id 
        JOIN products pr ON s.product_id = pr.id 
        ORDER BY s.id DESC LIMIT 5
    """).fetchall()

    conn.close()

    metrics = {
        'jeera_kg': jeera_kg, 'jeera_lots': jeera_lots,
        'variyali_kg': variyali_kg, 'variyali_lots': variyali_lots,
        'today_purchases_count': today_purchases['count'] or 0,
        'today_purchases_amt': today_purchases['total_amt'] or 0,
        'today_sales_count': today_sales['count'] or 0,
        'today_sales_amt': today_sales['total_amt'] or 0,
        'today_profit': today_sales['total_profit'] or 0,
        'pending_farmer_pay': pending_p,
        'pending_customer_pay': pending_s,
        'total_farmers': total_farmers,
        'total_customers': total_customers
    }

    return render_template('dashboard.html', metrics=metrics, recent_purchases=recent_purchases, recent_sales=recent_sales)

# --- FARMERS ---
@app.route('/farmers', methods=['GET', 'POST'])
@login_required
def farmers():
    conn = get_db_connection()
    if request.method == 'POST':
        name = request.form['name'].strip()
        mobile = request.form['mobile'].strip()
        village = request.form['village'].strip()
        if not name or not mobile:
            flash("Name and Mobile are required.", "danger")
        else:
            conn.execute("INSERT INTO farmers (name, mobile, village) VALUES (?, ?, ?)", (name, mobile, village))
            conn.commit()
            flash("Farmer added successfully!", "success")
            return redirect(url_for('farmers'))

    search = request.args.get('search', '').strip()
    if search:
        farmer_list = conn.execute("SELECT * FROM farmers WHERE name LIKE ? OR mobile LIKE ? OR village LIKE ? ORDER BY id DESC", 
                                   (f'%{search}%', f'%{search}%', f'%{search}%')).fetchall()
    else:
        farmer_list = conn.execute("SELECT * FROM farmers ORDER BY id DESC").fetchall()

    conn.close()
    return render_template('farmers.html', farmers=farmer_list, search=search)

@app.route('/farmers/<int:id>')
@login_required
def farmer_details(id):
    conn = get_db_connection()
    farmer = conn.execute("SELECT * FROM farmers WHERE id = ?", (id,)).fetchone()
    if not farmer:
        conn.close()
        flash("Farmer not found.", "danger")
        return redirect(url_for('farmers'))

    purchases = conn.execute("""
        SELECT p.*, pr.name as product_name 
        FROM purchases p 
        JOIN products pr ON p.product_id = pr.id 
        WHERE p.farmer_id = ? ORDER BY p.id DESC
    """, (id,)).fetchall()

    ledger = conn.execute("SELECT * FROM ledger WHERE party_type = 'Farmer' AND party_id = ? ORDER BY date ASC, id ASC", (id,)).fetchall()
    
    totals = conn.execute("""
        SELECT SUM(net_payable) as total_purchase, SUM(paid_amount) as total_paid, SUM(remaining_amount) as total_pending 
        FROM purchases WHERE farmer_id = ?
    """, (id,)).fetchone()

    conn.close()
    return render_template('farmer_details.html', farmer=farmer, purchases=purchases, ledger=ledger, totals=totals)

# --- CUSTOMERS ---
@app.route('/customers', methods=['GET', 'POST'])
@login_required
def customers():
    conn = get_db_connection()
    if request.method == 'POST':
        name = request.form['name'].strip()
        mobile = request.form['mobile'].strip()
        address = request.form['address'].strip()
        if not name or not mobile:
            flash("Name and Mobile are required.", "danger")
        else:
            conn.execute("INSERT INTO customers (name, mobile, address) VALUES (?, ?, ?)", (name, mobile, address))
            conn.commit()
            flash("Customer added successfully!", "success")
            return redirect(url_for('customers'))

    search = request.args.get('search', '').strip()
    if search:
        customer_list = conn.execute("SELECT * FROM customers WHERE name LIKE ? OR mobile LIKE ? OR address LIKE ? ORDER BY id DESC", 
                                     (f'%{search}%', f'%{search}%', f'%{search}%')).fetchall()
    else:
        customer_list = conn.execute("SELECT * FROM customers ORDER BY id DESC").fetchall()

    conn.close()
    return render_template('customers.html', customers=customer_list, search=search)

@app.route('/customers/<int:id>')
@login_required
def customer_details(id):
    conn = get_db_connection()
    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (id,)).fetchone()
    if not customer:
        conn.close()
        flash("Customer not found.", "danger")
        return redirect(url_for('customers'))

    sales = conn.execute("""
        SELECT s.*, pr.name as product_name 
        FROM sales s 
        JOIN products pr ON s.product_id = pr.id 
        WHERE s.customer_id = ? ORDER BY s.id DESC
    """, (id,)).fetchall()

    ledger = conn.execute("SELECT * FROM ledger WHERE party_type = 'Customer' AND party_id = ? ORDER BY date ASC, id ASC", (id,)).fetchall()

    totals = conn.execute("""
        SELECT SUM(final_amount) as total_sales, SUM(paid_amount) as total_received, SUM(remaining_amount) as total_pending 
        FROM sales WHERE customer_id = ?
    """, (id,)).fetchone()

    conn.close()
    return render_template('customer_details.html', customer=customer, sales=sales, ledger=ledger, totals=totals)

# --- PURCHASES ---
@app.route('/purchases')
@login_required
def purchases():
    conn = get_db_connection()
    search = request.args.get('search', '').strip()
    if search:
        query = """
            SELECT p.*, f.name as farmer_name, f.mobile, pr.name as product_name 
            FROM purchases p
            JOIN farmers f ON p.farmer_id = f.id
            JOIN products pr ON p.product_id = pr.id
            WHERE f.name LIKE ? OR f.mobile LIKE ? OR p.id LIKE ? OR pr.name LIKE ?
            ORDER BY p.id DESC
        """
        purchases_list = conn.execute(query, (f'%{search}%', f'%{search}%', f'%{search}%', f'%{search}%')).fetchall()
    else:
        purchases_list = conn.execute("""
            SELECT p.*, f.name as farmer_name, f.mobile, pr.name as product_name 
            FROM purchases p
            JOIN farmers f ON p.farmer_id = f.id
            JOIN products pr ON p.product_id = pr.id
            ORDER BY p.id DESC
        """).fetchall()

    conn.close()
    return render_template('purchases.html', purchases=purchases_list, search=search)

@app.route('/purchases/new', methods=['GET', 'POST'])
@login_required
def purchase_form():
    conn = get_db_connection()
    if request.method == 'POST':
        try:
            farmer_id = int(request.form['farmer_id'])
            product_id = int(request.form['product_id'])
            p_date = request.form['date']
            lots = float(request.form['lots'])
            rate = float(request.form['rate_per_kg'])
            quality = request.form.get('quality', '')
            moisture = float(request.form.get('moisture', 0) or 0)
            lot_number = request.form.get('lot_number', '')
            transport = float(request.form.get('transport_charges', 0) or 0)
            other = float(request.form.get('other_charges', 0) or 0)
            paid_amount = float(request.form.get('paid_amount', 0) or 0)
            payment_method = request.form.get('payment_method', 'Cash')
            notes = request.form.get('notes', '')

            lot_w = get_lot_weight()
            kg = lots * lot_w
            gross_amount = kg * rate
            net_payable = gross_amount + transport + other

            if paid_amount > net_payable:
                flash("Paid amount cannot exceed Net Payable.", "danger")
                return redirect(url_for('purchase_form'))

            remaining = net_payable - paid_amount
            status = 'Paid' if remaining == 0 else ('Partial' if paid_amount > 0 else 'Pending')

            # Insert Purchase
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO purchases (
                    date, farmer_id, product_id, lots, kg, rate_per_kg, quality, moisture, lot_number,
                    transport_charges, other_charges, gross_amount, net_payable, paid_amount,
                    remaining_amount, payment_status, payment_method, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (p_date, farmer_id, product_id, lots, kg, rate, quality, moisture, lot_number,
                  transport, other, gross_amount, net_payable, paid_amount, remaining, status, payment_method, notes))
            purchase_id = cursor.lastrowid

            # Update Product Stock
            cursor.execute("UPDATE products SET stock_kg = stock_kg + ? WHERE id = ?", (kg, product_id))
            new_stock = cursor.execute("SELECT stock_kg FROM products WHERE id = ?", (product_id,)).fetchone()['stock_kg']

            # Stock Transaction
            cursor.execute("""
                INSERT INTO stock_transactions (date, product_id, type, ref_id, inward_kg, balance_kg, notes)
                VALUES (?, ?, 'Purchase', ?, ?, ?, ?)
            """, (p_date, product_id, purchase_id, kg, new_stock, f"Farmer Purchase #{purchase_id}"))

            # Farmer Ledger Entry (Net payable is Credit/We owe farmer)
            cursor.execute("""
                INSERT INTO ledger (date, party_type, party_id, type, ref_id, description, credit, debit, balance)
                VALUES (?, 'Farmer', ?, 'Purchase', ?, ?, ?, 0, 0)
            """, (p_date, farmer_id, purchase_id, f"Purchase #{purchase_id}", net_payable))

            # Payment Record if paid > 0
            if paid_amount > 0:
                cursor.execute("""
                    INSERT INTO payments (date, party_type, party_id, ref_type, ref_id, amount, method, notes)
                    VALUES (?, 'Farmer', ?, 'Purchase', ?, ?, ?, 'Initial Purchase Payment')
                """, (p_date, farmer_id, purchase_id, paid_amount, payment_method))

                cursor.execute("""
                    INSERT INTO ledger (date, party_type, party_id, type, ref_id, description, credit, debit, balance)
                    VALUES (?, 'Farmer', ?, 'Payment', ?, ?, 0, ?, 0)
                """, (p_date, farmer_id, purchase_id, f"Payment for Purchase #{purchase_id}", paid_amount))

            conn.commit()
            recalculate_ledger('Farmer', farmer_id)
            conn.close()

            flash(f"Purchase #{purchase_id} recorded successfully!", "success")
            return redirect(url_for('purchase_receipt', id=purchase_id))

        except Exception as e:
            conn.rollback()
            conn.close()
            flash(f"Error saving purchase: {str(e)}", "danger")
            return redirect(url_for('purchase_form'))

    farmers_list = conn.execute("SELECT * FROM farmers ORDER BY name").fetchall()
    products_list = conn.execute("SELECT * FROM products").fetchall()
    conn.close()
    return render_template('purchase_form.html', farmers=farmers_list, products=products_list, today=date.today().strftime('%Y-%m-%d'))

@app.route('/purchases/<int:id>/receipt')
@login_required
def purchase_receipt(id):
    conn = get_db_connection()
    purchase = conn.execute("""
        SELECT p.*, f.name as farmer_name, f.mobile, f.village, pr.name as product_name
        FROM purchases p
        JOIN farmers f ON p.farmer_id = f.id
        JOIN products pr ON p.product_id = pr.id
        WHERE p.id = ?
    """, (id,)).fetchone()
    conn.close()

    if not purchase:
        flash("Purchase record not found.", "danger")
        return redirect(url_for('purchases'))

    return render_template('purchase_receipt.html', p=purchase)

# --- SALES ---
@app.route('/sales')
@login_required
def sales():
    conn = get_db_connection()
    search = request.args.get('search', '').strip()
    if search:
        query = """
            SELECT s.*, c.name as customer_name, c.mobile, pr.name as product_name 
            FROM sales s
            JOIN customers c ON s.customer_id = c.id
            JOIN products pr ON s.product_id = pr.id
            WHERE c.name LIKE ? OR c.mobile LIKE ? OR s.id LIKE ? OR pr.name LIKE ?
            ORDER BY s.id DESC
        """
        sales_list = conn.execute(query, (f'%{search}%', f'%{search}%', f'%{search}%', f'%{search}%')).fetchall()
    else:
        sales_list = conn.execute("""
            SELECT s.*, c.name as customer_name, c.mobile, pr.name as product_name 
            FROM sales s
            JOIN customers c ON s.customer_id = c.id
            JOIN products pr ON s.product_id = pr.id
            ORDER BY s.id DESC
        """).fetchall()

    conn.close()
    return render_template('sales.html', sales=sales_list, search=search)

@app.route('/sales/new', methods=['GET', 'POST'])
@login_required
def sale_form():
    conn = get_db_connection()
    if request.method == 'POST':
        try:
            customer_id = int(request.form['customer_id'])
            product_id = int(request.form['product_id'])
            s_date = request.form['date']
            lots = float(request.form['lots'])
            rate = float(request.form['selling_rate_per_kg'])
            discount = float(request.form.get('discount', 0) or 0)
            transport = float(request.form.get('transport_charges', 0) or 0)
            other = float(request.form.get('other_charges', 0) or 0)
            paid_amount = float(request.form.get('paid_amount', 0) or 0)
            payment_method = request.form.get('payment_method', 'Cash')
            notes = request.form.get('notes', '')

            lot_w = get_lot_weight()
            kg = lots * lot_w

            # Stock Validation Check
            product = conn.execute("SELECT name, stock_kg FROM products WHERE id = ?", (product_id,)).fetchone()
            if product['stock_kg'] < kg:
                flash(f"❌ Cannot complete sale. Insufficient Stock! Available {product['name']}: {product['stock_kg']} KG ({product['stock_kg']/lot_w:.1f} Lots), Required: {kg} KG ({lots} Lots).", "danger")
                customers_list = conn.execute("SELECT * FROM customers ORDER BY name").fetchall()
                products_list = conn.execute("SELECT * FROM products").fetchall()
                conn.close()
                return render_template('sale_form.html', customers=customers_list, products=products_list, today=s_date)

            # Purchase Cost Calculation for Profit (Weighted avg cost or recent purchase rate)
            avg_cost_row = conn.execute("SELECT AVG(rate_per_kg) as avg_cost FROM purchases WHERE product_id = ?", (product_id,)).fetchone()
            purchase_cost = avg_cost_row['avg_cost'] if avg_cost_row and avg_cost_row['avg_cost'] else (rate * 0.85)

            gross_amount = kg * rate
            final_amount = gross_amount - discount + transport + other
            profit = (rate - purchase_cost) * kg - discount

            if paid_amount > final_amount:
                flash("Paid amount cannot exceed Final Invoice Amount.", "danger")
                return redirect(url_for('sale_form'))

            remaining = final_amount - paid_amount
            status = 'Paid' if remaining == 0 else ('Partial' if paid_amount > 0 else 'Pending')

            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sales (
                    date, customer_id, product_id, lots, kg, selling_rate_per_kg, purchase_cost_per_kg,
                    gross_amount, discount, transport_charges, other_charges, final_amount, paid_amount,
                    remaining_amount, payment_status, payment_method, profit, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (s_date, customer_id, product_id, lots, kg, rate, purchase_cost, gross_amount, discount,
                  transport, other, final_amount, paid_amount, remaining, status, payment_method, profit, notes))
            sale_id = cursor.lastrowid

            # Deduct Stock
            cursor.execute("UPDATE products SET stock_kg = stock_kg - ? WHERE id = ?", (kg, product_id))
            new_stock = cursor.execute("SELECT stock_kg FROM products WHERE id = ?", (product_id,)).fetchone()['stock_kg']

            # Stock Transaction
            cursor.execute("""
                INSERT INTO stock_transactions (date, product_id, type, ref_id, outward_kg, balance_kg, notes)
                VALUES (?, ?, 'Sale', ?, ?, ?, ?)
            """, (s_date, product_id, sale_id, kg, new_stock, f"Customer Sale #{sale_id}"))

            # Customer Ledger (Final amount is Debit/Customer owes us)
            cursor.execute("""
                INSERT INTO ledger (date, party_type, party_id, type, ref_id, description, debit, credit, balance)
                VALUES (?, 'Customer', ?, 'Sale', ?, ?, ?, 0, 0)
            """, (s_date, customer_id, sale_id, f"Sale Invoice #{sale_id}", final_amount))

            # Payment Record if paid > 0
            if paid_amount > 0:
                cursor.execute("""
                    INSERT INTO payments (date, party_type, party_id, ref_type, ref_id, amount, method, notes)
                    VALUES (?, 'Customer', ?, 'Sale', ?, ?, ?, 'Initial Sale Payment')
                """, (s_date, customer_id, sale_id, paid_amount, payment_method))

                cursor.execute("""
                    INSERT INTO ledger (date, party_type, party_id, type, ref_id, description, debit, credit, balance)
                    VALUES (?, 'Customer', ?, 'Payment', ?, ?, 0, ?, 0)
                """, (s_date, customer_id, sale_id, f"Payment for Sale #{sale_id}", paid_amount))

            conn.commit()
            recalculate_ledger('Customer', customer_id)
            conn.close()

            flash(f"Sale Invoice #{sale_id} created successfully!", "success")
            return redirect(url_for('invoice', id=sale_id))

        except Exception as e:
            conn.rollback()
            conn.close()
            flash(f"Error creating sale: {str(e)}", "danger")
            return redirect(url_for('sale_form'))

    customers_list = conn.execute("SELECT * FROM customers ORDER BY name").fetchall()
    products_list = conn.execute("SELECT * FROM products").fetchall()
    conn.close()
    return render_template('sale_form.html', customers=customers_list, products=products_list, today=date.today().strftime('%Y-%m-%d'))

@app.route('/sales/<int:id>/invoice')
@login_required
def invoice(id):
    conn = get_db_connection()
    sale = conn.execute("""
        SELECT s.*, c.name as customer_name, c.mobile, c.address, pr.name as product_name
        FROM sales s
        JOIN customers c ON s.customer_id = c.id
        JOIN products pr ON s.product_id = pr.id
        WHERE s.id = ?
    """, (id,)).fetchone()
    conn.close()

    if not sale:
        flash("Sale invoice not found.", "danger")
        return redirect(url_for('sales'))

    return render_template('invoice.html', s=sale)

# --- STOCK MANAGEMENT ---
@app.route('/stock', methods=['GET', 'POST'])
@login_required
def stock():
    conn = get_db_connection()
    lot_w = get_lot_weight()

    if request.method == 'POST' and session.get('role') == 'Admin':
        product_id = int(request.form['product_id'])
        adj_type = request.form['adj_type'] # 'Add' or 'Subtract'
        adj_kg = float(request.form['adj_kg'])
        reason = request.form.get('reason', 'Stock Adjustment')

        current_stock = conn.execute("SELECT stock_kg FROM products WHERE id = ?", (product_id,)).fetchone()['stock_kg']
        
        if adj_type == 'Subtract' and adj_kg > current_stock:
            flash("Cannot reduce stock below 0.", "danger")
        else:
            inward = adj_kg if adj_type == 'Add' else 0
            outward = adj_kg if adj_type == 'Subtract' else 0
            new_stock = current_stock + inward - outward

            cursor = conn.cursor()
            cursor.execute("UPDATE products SET stock_kg = ? WHERE id = ?", (new_stock, product_id))
            cursor.execute("""
                INSERT INTO stock_transactions (date, product_id, type, inward_kg, outward_kg, balance_kg, notes)
                VALUES (?, ?, 'Stock Adjustment', ?, ?, ?, ?)
            """, (date.today().strftime('%Y-%m-%d'), product_id, inward, outward, new_stock, reason))
            conn.commit()
            flash("Stock adjusted successfully!", "success")

    products = conn.execute("SELECT * FROM products").fetchall()
    transactions = conn.execute("""
        SELECT st.*, pr.name as product_name 
        FROM stock_transactions st 
        JOIN products pr ON st.product_id = pr.id 
        ORDER BY st.id DESC LIMIT 100
    """).fetchall()

    conn.close()
    return render_template('stock.html', products=products, transactions=transactions, lot_w=lot_w)

# --- PAYMENTS ---
@app.route('/payments', methods=['GET', 'POST'])
@login_required
def payments():
    conn = get_db_connection()

    if request.method == 'POST':
        party_type = request.form['party_type']
        ref_id = int(request.form['ref_id'])
        amount = float(request.form['amount'])
        method = request.form['method']
        ref_num = request.form.get('ref_number', '')
        notes = request.form.get('notes', '')
        p_date = request.form['date']

        cursor = conn.cursor()

        if party_type == 'Farmer':
            purchase = cursor.execute("SELECT * FROM purchases WHERE id = ?", (ref_id,)).fetchone()
            if purchase and amount <= purchase['remaining_amount']:
                new_paid = purchase['paid_amount'] + amount
                new_rem = purchase['remaining_amount'] - amount
                new_status = 'Paid' if new_rem == 0 else 'Partial'

                cursor.execute("UPDATE purchases SET paid_amount = ?, remaining_amount = ?, payment_status = ? WHERE id = ?", 
                               (new_paid, new_rem, new_status, ref_id))
                
                cursor.execute("""
                    INSERT INTO payments (date, party_type, party_id, ref_type, ref_id, amount, method, ref_number, notes)
                    VALUES (?, 'Farmer', ?, 'Purchase', ?, ?, ?, ?, ?)
                """, (p_date, purchase['farmer_id'], ref_id, amount, method, ref_num, notes))

                cursor.execute("""
                    INSERT INTO ledger (date, party_type, party_id, type, ref_id, description, credit, debit, balance)
                    VALUES (?, 'Farmer', ?, 'Payment', ?, ?, 0, ?, 0)
                """, (p_date, purchase['farmer_id'], ref_id, f"Payment for Purchase #{ref_id}", amount))

                conn.commit()
                recalculate_ledger('Farmer', purchase['farmer_id'])
                flash("Payment recorded successfully!", "success")
            else:
                flash("Invalid payment amount or purchase not found.", "danger")

        elif party_type == 'Customer':
            sale = cursor.execute("SELECT * FROM sales WHERE id = ?", (ref_id,)).fetchone()
            if sale and amount <= sale['remaining_amount']:
                new_paid = sale['paid_amount'] + amount
                new_rem = sale['remaining_amount'] - amount
                new_status = 'Paid' if new_rem == 0 else 'Partial'

                cursor.execute("UPDATE sales SET paid_amount = ?, remaining_amount = ?, payment_status = ? WHERE id = ?", 
                               (new_paid, new_rem, new_status, ref_id))

                cursor.execute("""
                    INSERT INTO payments (date, party_type, party_id, ref_type, ref_id, amount, method, ref_number, notes)
                    VALUES (?, 'Customer', ?, 'Sale', ?, ?, ?, ?, ?)
                """, (p_date, sale['customer_id'], ref_id, amount, method, ref_num, notes))

                cursor.execute("""
                    INSERT INTO ledger (date, party_type, party_id, type, ref_id, description, debit, credit, balance)
                    VALUES (?, 'Customer', ?, 'Payment', ?, ?, 0, ?, 0)
                """, (p_date, sale['customer_id'], ref_id, f"Payment for Sale #{ref_id}", amount))

                conn.commit()
                recalculate_ledger('Customer', sale['customer_id'])
                flash("Payment recorded successfully!", "success")
            else:
                flash("Invalid payment amount or sale not found.", "danger")

        return redirect(url_for('payments'))

    payment_history = conn.execute("""
        SELECT p.*, 
               CASE WHEN p.party_type = 'Farmer' THEN f.name ELSE c.name END as party_name
        FROM payments p
        LEFT JOIN farmers f ON p.party_type = 'Farmer' AND p.party_id = f.id
        LEFT JOIN customers c ON p.party_type = 'Customer' AND p.party_id = c.id
        ORDER BY p.id DESC
    """).fetchall()

    pending_purchases = conn.execute("""
        SELECT p.id, p.date, f.name as farmer_name, p.net_payable, p.remaining_amount 
        FROM purchases p JOIN farmers f ON p.farmer_id = f.id WHERE p.remaining_amount > 0
    """).fetchall()

    pending_sales = conn.execute("""
        SELECT s.id, s.date, c.name as customer_name, s.final_amount, s.remaining_amount 
        FROM sales s JOIN customers c ON s.customer_id = c.id WHERE s.remaining_amount > 0
    """).fetchall()

    conn.close()
    return render_template('payments.html', payments=payment_history, pending_purchases=pending_purchases, pending_sales=pending_sales, today=date.today().strftime('%Y-%m-%d'))

# --- LEDGERS ---
@app.route('/ledger')
@login_required
def ledger():
    party_type = request.args.get('party_type', 'Farmer')
    party_id = request.args.get('party_id', type=int)

    conn = get_db_connection()
    farmers = conn.execute("SELECT id, name FROM farmers ORDER BY name").fetchall()
    customers = conn.execute("SELECT id, name FROM customers ORDER BY name").fetchall()

    ledger_entries = []
    party_details = None

    if party_id:
        if party_type == 'Farmer':
            party_details = conn.execute("SELECT * FROM farmers WHERE id = ?", (party_id,)).fetchone()
        else:
            party_details = conn.execute("SELECT * FROM customers WHERE id = ?", (party_id,)).fetchone()

        if party_details:
            recalculate_ledger(party_type, party_id)
            ledger_entries = conn.execute("""
                SELECT * FROM ledger WHERE party_type = ? AND party_id = ? ORDER BY date ASC, id ASC
            """, (party_type, party_id)).fetchall()

    conn.close()
    return render_template('ledger.html', party_type=party_type, party_id=party_id, farmers=farmers, customers=customers, entries=ledger_entries, party=party_details)

# --- REPORTS ---
@app.route('/reports')
@login_required
def reports():
    report_type = request.args.get('type', 'sales')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    conn = get_db_connection()
    query_params = []
    where_clause = ""

    if start_date and end_date:
        where_clause = " WHERE date BETWEEN ? AND ?"
        query_params = [start_date, end_date]

    report_data = []
    summary = {}

    if report_type == 'purchases':
        query = f"""
            SELECT p.*, f.name as farmer_name, pr.name as product_name
            FROM purchases p
            JOIN farmers f ON p.farmer_id = f.id
            JOIN products pr ON p.product_id = pr.id
            {where_clause} ORDER BY p.date DESC
        """
        report_data = conn.execute(query, query_params).fetchall()
        tot_kg = sum(r['kg'] for r in report_data)
        tot_amt = sum(r['net_payable'] for r in report_data)
        summary = {'total_records': len(report_data), 'total_kg': tot_kg, 'total_amount': tot_amt}

    elif report_type == 'sales':
        query = f"""
            SELECT s.*, c.name as customer_name, pr.name as product_name
            FROM sales s
            JOIN customers c ON s.customer_id = c.id
            JOIN products pr ON s.product_id = pr.id
            {where_clause} ORDER BY s.date DESC
        """
        report_data = conn.execute(query, query_params).fetchall()
        tot_kg = sum(r['kg'] for r in report_data)
        tot_amt = sum(r['final_amount'] for r in report_data)
        tot_profit = sum(r['profit'] for r in report_data)
        summary = {'total_records': len(report_data), 'total_kg': tot_kg, 'total_amount': tot_amt, 'total_profit': tot_profit}

    elif report_type == 'stock':
        report_data = conn.execute("""
            SELECT pr.name, pr.stock_kg, 
                   COALESCE(SUM(p.kg), 0) as total_purchased, 
                   COALESCE(SUM(s.kg), 0) as total_sold
            FROM products pr
            LEFT JOIN purchases p ON pr.id = p.product_id
            LEFT JOIN sales s ON pr.id = s.product_id
            GROUP BY pr.id
        """).fetchall()

    elif report_type == 'profit':
        query = f"""
            SELECT s.date, s.id as sale_id, c.name as customer_name, pr.name as product_name,
                   s.kg, s.gross_amount, s.discount, s.final_amount, (s.purchase_cost_per_kg * s.kg) as est_cost, s.profit
            FROM sales s
            JOIN customers c ON s.customer_id = c.id
            JOIN products pr ON s.product_id = pr.id
            {where_clause} ORDER BY s.date DESC
        """
        report_data = conn.execute(query, query_params).fetchall()
        tot_sales = sum(r['final_amount'] for r in report_data)
        tot_cost = sum(r['est_cost'] for r in report_data)
        tot_profit = sum(r['profit'] for r in report_data)
        summary = {'total_sales': tot_sales, 'total_cost': tot_cost, 'total_profit': tot_profit}

    conn.close()
    return render_template('reports.html', report_type=report_type, report_data=report_data, summary=summary, start_date=start_date, end_date=end_date)

# --- SETTINGS ---
@app.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    conn = get_db_connection()
    if request.method == 'POST':
        for key in ['business_name', 'shop_no', 'market', 'business_type', 'location', 'mobile', 'email', 'gst_no', 'lot_weight_kg']:
            if key in request.form:
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, request.form[key].strip()))
        conn.commit()
        flash("Settings updated successfully!", "success")
        return redirect(url_for('settings'))

    conn.close()
    return render_template('settings.html')

# --- PDF GENERATION ENGINE ---
def generate_pdf_document(title, headers, rows, metadata=None):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()

    elements = []

    # Business Header
    biz_name = get_setting('business_name', 'RAMDEV')
    shop_no = get_setting('shop_no', '230/D')
    market = get_setting('market', 'Unjha APMC')
    b_type = get_setting('business_type', 'Jeera & Variyali Trading')
    location = get_setting('location', 'Unjha APMC, Gujarat, India')

    title_style = ParagraphStyle(name='TitleStyle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=20, leading=24, alignment=1, textColor=colors.HexColor('#1b382b'))
    sub_style = ParagraphStyle(name='SubStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=14, alignment=1, textColor=colors.HexColor('#444444'))

    elements.append(Paragraph(biz_name, title_style))
    elements.append(Paragraph(f"Shop No. {shop_no}, {market} | {b_type}", sub_style))
    elements.append(Paragraph(location, sub_style))
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#1b382b'), spaceAfter=15))

    # Doc Title
    doc_title_style = ParagraphStyle(name='DocTitle', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=14, alignment=1, textColor=colors.HexColor('#2c3e50'))
    elements.append(Paragraph(title.upper(), doc_title_style))
    elements.append(Spacer(1, 10))

    # Optional Metadata Grid
    if metadata:
        meta_data = []
        meta_row = []
        for k, v in metadata.items():
            meta_row.append(Paragraph(f"<b>{k}:</b> {v}", styles['Normal']))
            if len(meta_row) == 2:
                meta_data.append(meta_row)
                meta_row = []
        if meta_row:
            meta_row.append(Paragraph("", styles['Normal']))
            meta_data.append(meta_row)

        meta_table = Table(meta_data, colWidths=[270, 270])
        meta_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8f9fa')),
            ('PADDING', (0,0), (-1,-1), 6),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#dddddd')),
        ]))
        elements.append(meta_table)
        elements.append(Spacer(1, 15))

    # Data Table
    table_content = [[Paragraph(f"<b>{h}</b>", styles['Normal']) for h in headers]]
    for r in rows:
        table_content.append([Paragraph(str(cell), styles['Normal']) for cell in r])

    t = Table(table_content)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e8f5e9')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#1b382b')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cccccc')),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))

    elements.append(t)
    doc.build(elements)
    buffer.seek(0)
    return buffer

@app.route('/pdf/purchase_receipt/<int:id>')
@login_required
def pdf_purchase_receipt(id):
    conn = get_db_connection()
    p = conn.execute("""
        SELECT p.*, f.name as farmer_name, f.mobile, f.village, pr.name as product_name
        FROM purchases p JOIN farmers f ON p.farmer_id = f.id JOIN products pr ON p.product_id = pr.id
        WHERE p.id = ?
    """, (id,)).fetchone()
    conn.close()

    if not p: return "Receipt not found", 404

    meta = {
        'Receipt ID': f"PUR-{p['id']}",
        'Date': p['date'],
        'Farmer Name': p['farmer_name'],
        'Mobile / Village': f"{p['mobile']} ({p['village']})",
        'Payment Status': p['payment_status']
    }

    headers = ['Product', 'Lots', 'KG', 'Rate / KG', 'Gross Amt', 'Charges', 'Net Payable', 'Paid', 'Remaining']
    rows = [[
        p['product_name'], f"{p['lots']} Lots", f"{p['kg']} KG", f"₹{p['rate_per_kg']}",
        f"₹{p['gross_amount']:.2f}", f"₹{p['transport_charges']+p['other_charges']:.2f}",
        f"₹{p['net_payable']:.2f}", f"₹{p['paid_amount']:.2f}", f"₹{p['remaining_amount']:.2f}"
    ]]

    pdf_buf = generate_pdf_document("FARMER PURCHASE RECEIPT", headers, rows, meta)
    return send_file(pdf_buf, mimetype='application/pdf', as_attachment=True, download_name=f'Receipt_PUR_{id}.pdf')

@app.route('/pdf/invoice/<int:id>')
@login_required
def pdf_invoice(id):
    conn = get_db_connection()
    s = conn.execute("""
        SELECT s.*, c.name as customer_name, c.mobile, c.address, pr.name as product_name
        FROM sales s JOIN customers c ON s.customer_id = c.id JOIN products pr ON s.product_id = pr.id
        WHERE s.id = ?
    """, (id,)).fetchone()
    conn.close()

    if not s: return "Invoice not found", 404

    meta = {
        'Invoice No': f"INV-{s['id']}",
        'Date': s['date'],
        'Customer Name': s['customer_name'],
        'Mobile / Address': f"{s['mobile']} ({s['address']})",
        'Payment Status': s['payment_status']
    }

    headers = ['Product', 'Lots', 'KG', 'Rate / KG', 'Gross Amt', 'Discount', 'Charges', 'Final Amount', 'Paid']
    rows = [[
        s['product_name'], f"{s['lots']} Lots", f"{s['kg']} KG", f"₹{s['selling_rate_per_kg']}",
        f"₹{s['gross_amount']:.2f}", f"₹{s['discount']:.2f}", f"₹{s['transport_charges']+s['other_charges']:.2f}",
        f"₹{s['final_amount']:.2f}", f"₹{s['paid_amount']:.2f}"
    ]]

    pdf_buf = generate_pdf_document("TAX / TRADING INVOICE", headers, rows, meta)
    return send_file(pdf_buf, mimetype='application/pdf', as_attachment=True, download_name=f'Invoice_INV_{id}.pdf')

# --- EXCEL EXPORT ENGINE ---
@app.route('/export/excel/<type_name>')
@login_required
def export_excel(type_name):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = type_name.capitalize()

    conn = get_db_connection()

    header_fill = PatternFill(start_color="1B382B", end_color="1B382B", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)

    if type_name == 'purchases':
        headers = ['ID', 'Date', 'Farmer Name', 'Product', 'Lots', 'KG', 'Rate/KG', 'Gross Amt', 'Net Payable', 'Paid', 'Status']
        ws.append(headers)
        rows = conn.execute("""
            SELECT p.id, p.date, f.name, pr.name, p.lots, p.kg, p.rate_per_kg, p.gross_amount, p.net_payable, p.paid_amount, p.payment_status
            FROM purchases p JOIN farmers f ON p.farmer_id = f.id JOIN products pr ON p.product_id = pr.id ORDER BY p.id DESC
        """).fetchall()
        for r in rows: ws.append(list(r))

    elif type_name == 'sales':
        headers = ['ID', 'Date', 'Customer Name', 'Product', 'Lots', 'KG', 'Rate/KG', 'Gross Amt', 'Final Amt', 'Paid', 'Profit', 'Status']
        ws.append(headers)
        rows = conn.execute("""
            SELECT s.id, s.date, c.name, pr.name, s.lots, s.kg, s.selling_rate_per_kg, s.gross_amount, s.final_amount, s.paid_amount, s.profit, s.payment_status
            FROM sales s JOIN customers c ON s.customer_id = c.id JOIN products pr ON s.product_id = pr.id ORDER BY s.id DESC
        """).fetchall()
        for r in rows: ws.append(list(r))

    elif type_name == 'stock':
        headers = ['Product ID', 'Product Name', 'Current Stock (KG)', 'Current Stock (Lots)']
        ws.append(headers)
        lot_w = get_lot_weight()
        rows = conn.execute("SELECT id, name, stock_kg FROM products").fetchall()
        for r in rows:
            ws.append([r['id'], r['name'], r['stock_kg'], r['stock_kg'] / lot_w])

    conn.close()

    # Style Header Row
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return send_file(buffer, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=f'{type_name}_export.xlsx')

if __name__ == '__main__':
    app.run(debug=True, port=5000)