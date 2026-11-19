from flask import Flask, render_template, request, redirect, url_for, session, Response
from functools import wraps
import re
import csv
import io
from datetime import datetime
import database
import dsa_engine

app = Flask(__name__)
app.secret_key = "rk_hardware_dsa_secret_key"
database.init_db()

undo_stack = []
CREDIT_LIMIT_PER_CUSTOMER = 50000.00

# --- LOGIN REQUIRED DECORATOR ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", err="Please sign in to access RK HARDWARE."))
        return f(*args, **kwargs)
    return decorated_function

# --- AUTHENTICATION ROUTES ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = database.verify_user(username, password)
        if user:
            session["user_id"] = user["user_id"]
            session["username"] = user["username"]
            session["full_name"] = user["full_name"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard", msg=f"Welcome back, {user['full_name']}!"))
        return render_template("login.html", error="Invalid username or password.")

    return render_template(
        "login.html",
        message=request.args.get("msg"),
        error=request.args.get("err")
    )

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login", msg="You have been signed out safely."))

# --- DASHBOARD ---
@app.route("/")
@login_required
def dashboard():
    products = database.get_all_products()
    sales = database.get_all_sales()
    customers = database.get_all_customers()

    total_valuation = sum(p["price"] * p["stock"] for p in products)
    collected_revenue = sum(s["total_amount"] for s in sales if s["payment_status"] == "Paid")
    unpaid_receivables = sum(s["total_amount"] for s in sales if s["payment_status"] != "Paid")
    low_stock_items = [p for p in products if p["stock"] <= 5]

    daily_totals = {}
    for s in reversed(sales):
        date_label = s["timestamp"].split(" ")[0]
        daily_totals[date_label] = daily_totals.get(date_label, 0.0) + s["total_amount"]

    chart_labels = list(daily_totals.keys())
    chart_values = list(daily_totals.values())

    if len(chart_values) >= 2:
        diff = chart_values[-1] - chart_values[-2]
        trend_status = "up" if diff >= 0 else "down"
        trend_diff = abs(diff)
    else:
        trend_status = "neutral"
        trend_diff = 0.0

    search_query = request.args.get("search", "").strip()
    search_mode = request.args.get("mode", "sku")
    search_result = None
    trie_results = []
    telemetry = None
    error = request.args.get("err")

    if "search" in request.args and not search_query:
        error = "Validation Error: Please enter a SKU, prefix, or product name before searching."
    elif search_query:
        if search_mode == "sku":
            search_result, telemetry = dsa_engine.hash_lookup_with_telemetry(products, search_query)
        elif search_mode == "trie":
            trie_results, telemetry = dsa_engine.trie_prefix_search_with_telemetry(products, search_query)
        else:
            search_result, telemetry = dsa_engine.binary_search_with_telemetry(products, search_query)

    return render_template(
        "dashboard.html",
        active_page="dashboard",
        total_valuation=total_valuation,
        collected_revenue=collected_revenue,
        unpaid_receivables=unpaid_receivables,
        total_customers=len(customers),
        low_stock_items=low_stock_items,
        chart_labels=chart_labels,
        chart_values=chart_values,
        trend_status=trend_status,
        trend_diff=trend_diff,
        search_query=search_query,
        search_mode=search_mode,
        search_result=search_result,
        trie_results=trie_results,
        telemetry=telemetry,
        can_undo=len(undo_stack) > 0,
        message=request.args.get("msg"),
        error=error
    )

# --- DIRECT POS SALES (CASH ONLY) ---
@app.route("/sales")
@login_required
def sales():
    products = database.get_all_products()
    customers = database.get_all_customers()
    all_sales = database.get_all_sales()
    pos_sales = [s for s in all_sales if s["payment_method"] != "Credit Invoice"]

    cart = session.get("pos_cart", [])
    cart_total = sum(item["subtotal"] for item in cart)

    return render_template(
        "sales.html",
        active_page="sales",
        products=products,
        customers=customers,
        pos_sales=pos_sales,
        cart=cart,
        cart_total=cart_total,
        can_undo=len(undo_stack) > 0,
        message=request.args.get("msg"),
        error=request.args.get("err")
    )

@app.route("/sales/cart/add", methods=["POST"])
@login_required
def add_to_cart():
    sku = request.form.get("sku", "").strip().upper()
    raw_qty = request.form.get("qty", "").strip()

    try:
        qty = int(raw_qty)
        if qty <= 0:
            return redirect(url_for("sales", err="Invalid Quantity: Quantity must be at least 1."))
    except ValueError:
        return redirect(url_for("sales", err="Invalid Input: Quantity must be a whole number."))

    products = database.get_all_products()
    item = dsa_engine.build_sku_hash_table(products).get(sku)
    if not item:
        return redirect(url_for("sales", err="Invalid Product: Selected SKU does not exist."))

    cart = session.get("pos_cart", [])
    already_in_cart = sum(c["qty"] for c in cart if c["sku"] == sku)

    if qty + already_in_cart > item["stock"]:
        return redirect(url_for("sales", err=f"Insufficient Stock: Only {item['stock']} {item['unit']}(s) available for {item['name']}."))

    for c in cart:
        if c["sku"] == sku:
            c["qty"] += qty
            c["subtotal"] = round(c["qty"] * c["price"], 2)
            break
    else:
        cart.append({
            "sku": sku,
            "name": item["name"],
            "unit": item["unit"],
            "price": item["price"],
            "qty": qty,
            "subtotal": round(qty * item["price"], 2)
        })

    session["pos_cart"] = cart
    return redirect(url_for("sales", msg=f"Added {qty}x {item['name']} to POS cart."))

@app.route("/sales/cart/remove/<sku>", methods=["POST"])
@login_required
def remove_from_cart(sku):
    cart = [c for c in session.get("pos_cart", []) if c["sku"] != sku.upper()]
    session["pos_cart"] = cart
    return redirect(url_for("sales", msg=f"Removed {sku} from POS cart."))

@app.route("/sales/cart/clear", methods=["POST"])
@login_required
def clear_cart():
    session["pos_cart"] = []
    return redirect(url_for("sales", msg="POS cart cleared."))

@app.route("/sales/checkout", methods=["POST"])
@login_required
def checkout_cart():
    cart = session.get("pos_cart", [])
    if not cart:
        return redirect(url_for("sales", err="Empty Cart: Please add at least one item to the cart before checking out."))

    customer_name = request.form.get("customer_name", "").strip()
    if not customer_name:
        return redirect(url_for("sales", err="Invalid Customer: Please select a customer."))

    products = database.get_all_products()
    sku_table = dsa_engine.build_sku_hash_table(products)

    for c in cart:
        live_item = sku_table.get(c["sku"])
        if not live_item or c["qty"] > live_item["stock"]:
            return redirect(url_for("sales", err=f"Stock Changed: Not enough stock left for {c['name']}."))

    receipt_no = f"RCP-{datetime.now().strftime('%H%M%S')}"
    grand_total = 0.0

    for c in cart:
        live_item = sku_table[c["sku"]]
        undo_stack.append({"type": "sale", "item": live_item.copy()})
        database.update_stock(c["sku"], live_item["stock"] - c["qty"])
        database.record_sale(
            receipt_no, c["sku"], c["name"], customer_name,
            c["qty"], c["subtotal"], "Cash", "Paid", "N/A"
        )
        grand_total += c["subtotal"]

    session["pos_cart"] = []
    return redirect(url_for("sales", msg=f"Cash Sale {receipt_no} completed — Total: ₱{grand_total:,.2f}"))

@app.route("/sales/delete/<int:sale_id>", methods=["POST"])
@login_required
def delete_sale(sale_id):
    sale = database.get_sale_by_id(sale_id)
    if not sale:
        return redirect(url_for("sales", err=f"Error: Sale record #{sale_id} does not exist."))

    products = database.get_all_products()
    item = dsa_engine.build_sku_hash_table(products).get(sale["sku"])
    if item:
        undo_stack.append({"type": "void_sale", "item": item.copy()})
        database.update_stock(sale["sku"], item["stock"] + sale["qty_sold"])

    database.delete_sale_by_id(sale_id)
    return redirect(url_for("sales", msg=f"Voided {sale['invoice_no']} and restored +{sale['qty_sold']} unit(s) to {sale['sku']}."))

# --- DEDICATED CREDIT INVOICES & LOANS ---
@app.route("/invoices")
@login_required
def invoices():
    products = database.get_all_products()
    customers = database.get_all_customers()
    all_sales = database.get_all_sales()
    today_str = datetime.now().strftime("%Y-%m-%d")

    credit_invoices = []
    for s in all_sales:
        if s["payment_method"] == "Credit Invoice":
            s["is_overdue"] = (s["payment_status"] != "Paid" and s["due_date"] < today_str)
            credit_invoices.append(s)

    inv_cart = session.get("invoice_cart", [])
    inv_cart_total = sum(item["subtotal"] for item in inv_cart)

    return render_template(
        "invoices.html",
        active_page="invoices",
        products=products,
        customers=customers,
        credit_invoices=credit_invoices,
        inv_cart=inv_cart,
        inv_cart_total=inv_cart_total,
        credit_limit=CREDIT_LIMIT_PER_CUSTOMER,
        can_undo=len(undo_stack) > 0,
        message=request.args.get("msg"),
        error=request.args.get("err")
    )

@app.route("/invoices/cart/add", methods=["POST"])
@login_required
def add_to_invoice_cart():
    sku = request.form.get("sku", "").strip().upper()
    raw_qty = request.form.get("qty", "").strip()

    try:
        qty = int(raw_qty)
        if qty <= 0:
            return redirect(url_for("invoices", err="Invalid Quantity: Quantity must be at least 1."))
    except ValueError:
        return redirect(url_for("invoices", err="Invalid Input: Quantity must be a whole number."))

    products = database.get_all_products()
    item = dsa_engine.build_sku_hash_table(products).get(sku)
    if not item:
        return redirect(url_for("invoices", err="Invalid Product: Selected SKU does not exist."))

    cart = session.get("invoice_cart", [])
    already_in_cart = sum(c["qty"] for c in cart if c["sku"] == sku)

    if qty + already_in_cart > item["stock"]:
        return redirect(url_for("invoices", err=f"Insufficient Stock: Only {item['stock']} {item['unit']}(s) available for {item['name']}."))

    for c in cart:
        if c["sku"] == sku:
            c["qty"] += qty
            c["subtotal"] = round(c["qty"] * c["price"], 2)
            break
    else:
        cart.append({
            "sku": sku,
            "name": item["name"],
            "unit": item["unit"],
            "price": item["price"],
            "qty": qty,
            "subtotal": round(qty * item["price"], 2)
        })

    session["invoice_cart"] = cart
    return redirect(url_for("invoices", msg=f"Added {qty}x {item['name']} to Credit Invoice cart."))

@app.route("/invoices/cart/remove/<sku>", methods=["POST"])
@login_required
def remove_from_invoice_cart(sku):
    cart = [c for c in session.get("invoice_cart", []) if c["sku"] != sku.upper()]
    session["invoice_cart"] = cart
    return redirect(url_for("invoices", msg=f"Removed {sku} from Credit Invoice cart."))

@app.route("/invoices/cart/clear", methods=["POST"])
@login_required
def clear_invoice_cart():
    session["invoice_cart"] = []
    return redirect(url_for("invoices", msg="Credit Invoice cart cleared."))

@app.route("/invoices/checkout", methods=["POST"])
@login_required
def checkout_invoice_cart():
    cart = session.get("invoice_cart", [])
    if not cart:
        return redirect(url_for("invoices", err="Empty Invoice Cart: Add at least one item before issuing a Credit Invoice."))

    customer_name = request.form.get("customer_name", "").strip()
    due_date = request.form.get("due_date", "").strip()

    if not customer_name or customer_name == "Walk-in Cash Customer":
        return redirect(url_for("invoices", err="Credit Policy Error: Select a registered customer or contractor for a Credit Invoice."))
    if not due_date:
        return redirect(url_for("invoices", err="Missing Due Date: Please specify a repayment due date."))

    all_sales = database.get_all_sales()
    existing_debt = sum(
        s["total_amount"] for s in all_sales
        if s["customer_name"] == customer_name and s["payment_status"] != "Paid"
    )
    new_order_total = sum(c["subtotal"] for c in cart)

    if existing_debt + new_order_total > CREDIT_LIMIT_PER_CUSTOMER:
        return redirect(
            url_for(
                "invoices",
                err=f"Credit Limit Exceeded: {customer_name} already owes ₱{existing_debt:,.2f}. Adding ₱{new_order_total:,.2f} exceeds the ₱{CREDIT_LIMIT_PER_CUSTOMER:,.2f} account limit."
            )
        )

    products = database.get_all_products()
    sku_table = dsa_engine.build_sku_hash_table(products)

    for c in cart:
        live_item = sku_table.get(c["sku"])
        if not live_item or c["qty"] > live_item["stock"]:
            return redirect(url_for("invoices", err=f"Stock Changed: Not enough stock left for {c['name']}."))

    invoice_no = f"INV-{datetime.now().strftime('%H%M%S')}"
    for c in cart:
        live_item = sku_table[c["sku"]]
        undo_stack.append({"type": "sale", "item": live_item.copy()})
        database.update_stock(c["sku"], live_item["stock"] - c["qty"])
        database.record_sale(
            invoice_no, c["sku"], c["name"], customer_name,
            c["qty"], c["subtotal"], "Credit Invoice", "Unpaid (Loan)", due_date
        )

    session["invoice_cart"] = []
    return redirect(url_for("invoices", msg=f"Credit Invoice {invoice_no} issued to {customer_name} — Total Loan: ₱{new_order_total:,.2f}"))

@app.route("/invoices/mark_paid/<int:sale_id>", methods=["POST"])
@login_required
def mark_paid(sale_id):
    sale = database.get_sale_by_id(sale_id)
    if not sale:
        return redirect(url_for("invoices", err="Error: Invoice record not found."))
    database.mark_invoice_paid(sale_id)
    return redirect(url_for("invoices", msg=f"Invoice {sale['invoice_no']} marked as PAID!"))

@app.route("/invoices/delete/<int:sale_id>", methods=["POST"])
@login_required
def delete_invoice(sale_id):
    sale = database.get_sale_by_id(sale_id)
    if not sale:
        return redirect(url_for("invoices", err=f"Error: Invoice record #{sale_id} does not exist."))

    products = database.get_all_products()
    item = dsa_engine.build_sku_hash_table(products).get(sale["sku"])
    if item:
        undo_stack.append({"type": "void_sale", "item": item.copy()})
        database.update_stock(sale["sku"], item["stock"] + sale["qty_sold"])

    database.delete_sale_by_id(sale_id)
    return redirect(url_for("invoices", msg=f"Voided {sale['invoice_no']} and restored +{sale['qty_sold']} unit(s) to {sale['sku']}."))

# --- INVENTORY ---
@app.route("/inventory")
@login_required
def inventory():
    products = database.get_all_products()
    categories = sorted(list({p["category"] for p in products}))
    selected_category = request.args.get("category", "").strip()
    search_text = request.args.get("q", "").strip()
    sort_by = request.args.get("sort")
    telemetry = None
    error = request.args.get("err")

    if selected_category:
        products = [p for p in products if p["category"] == selected_category]

    if search_text:
        products, telemetry = dsa_engine.trie_prefix_search_with_telemetry(products, search_text)

    if sort_by:
        if sort_by in ["name", "price", "stock"]:
            products, telemetry = dsa_engine.merge_sort_with_telemetry(products, sort_by)
        else:
            error = f"Invalid Sort Key: Cannot sort inventory by '{sort_by}'."

    return render_template(
        "inventory.html",
        active_page="inventory",
        products=products,
        categories=categories,
        selected_category=selected_category,
        search_text=search_text,
        telemetry=telemetry,
        can_undo=len(undo_stack) > 0,
        message=request.args.get("msg"),
        error=error
    )

@app.route("/inventory/add", methods=["POST"])
@login_required
def add_product():
    sku = request.form.get("sku", "").strip().upper()
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    unit = request.form.get("unit", "").strip()
    raw_price = request.form.get("price", "").strip()
    raw_stock = request.form.get("stock", "").strip()

    if not re.match(r"^[A-Z0-9\-]{3,15}$", sku):
        return redirect(url_for("inventory", err="Invalid SKU Format: Use 3–15 letters, numbers, or dashes (e.g., HW-109)."))

    existing_products = dsa_engine.build_sku_hash_table(database.get_all_products())
    if sku in existing_products:
        return redirect(url_for("inventory", err=f"Duplicate SKU Error: '{sku}' already exists in inventory."))

    if len(name) < 2:
        return redirect(url_for("inventory", err="Invalid Name: Product name must be at least 2 characters."))
    if not unit or any(char.isdigit() for char in unit):
        return redirect(url_for("inventory", err="Invalid Unit: Enter a valid unit label (e.g., Bag, Piece, Kilo, Meter)."))

    try:
        price = float(raw_price)
        if price <= 0:
            return redirect(url_for("inventory", err="Invalid Price: Unit price must be greater than ₱0.00."))
    except ValueError:
        return redirect(url_for("inventory", err="Invalid Price: Please enter a valid numeric amount."))

    try:
        stock = int(raw_stock)
        if stock < 0:
            return redirect(url_for("inventory", err="Invalid Stock: Initial quantity cannot be negative."))
    except ValueError:
        return redirect(url_for("inventory", err="Invalid Stock: Quantity must be a whole number."))

    database.add_or_update_product(sku, name, category, unit, price, stock)
    return redirect(url_for("inventory", msg=f"Product [{sku}] {name} added to catalog!"))

@app.route("/inventory/update_price/<sku>", methods=["POST"])
@login_required
def update_price(sku):
    raw_price = request.form.get("price", "").strip()
    try:
        new_price = float(raw_price)
        if new_price <= 0:
            return redirect(url_for("inventory", err=f"Invalid Price for {sku}: Price must be greater than ₱0.00."))
    except ValueError:
        return redirect(url_for("inventory", err=f"Invalid Price for {sku}: Please enter numbers only."))

    item = dsa_engine.build_sku_hash_table(database.get_all_products()).get(sku)
    if not item:
        return redirect(url_for("inventory", err=f"Error: SKU '{sku}' not found."))

    undo_stack.append({"type": "price_update", "item": item.copy()})
    database.update_price(sku, new_price)
    return redirect(url_for("inventory", msg=f"Updated price for {sku} to ₱{new_price:,.2f}"))

@app.route("/inventory/restock/<sku>", methods=["POST"])
@login_required
def restock(sku):
    try:
        add_qty = int(request.form.get("qty", 10))
        if add_qty <= 0:
            return redirect(url_for("inventory", err="Invalid Restock: Quantity must be greater than 0."))
    except ValueError:
        return redirect(url_for("inventory", err="Invalid Restock: Quantity must be a whole number."))

    item = dsa_engine.build_sku_hash_table(database.get_all_products()).get(sku)
    if not item:
        return redirect(url_for("inventory", err=f"Error: SKU '{sku}' not found."))

    undo_stack.append({"type": "restock", "item": item.copy()})
    database.update_stock(sku, item["stock"] + add_qty)
    return redirect(url_for("inventory", msg=f"Restocked +{add_qty} {item['unit']}(s) for {sku}"))

@app.route("/inventory/delete/<sku>", methods=["POST"])
@login_required
def delete_product(sku):
    item = dsa_engine.build_sku_hash_table(database.get_all_products()).get(sku)
    if not item:
        return redirect(url_for("inventory", err=f"Error: Cannot delete '{sku}' because it does not exist."))

    undo_stack.append({"type": "delete", "item": item.copy()})
    database.delete_product(sku)
    return redirect(url_for("inventory", msg=f"Deleted {sku} from inventory"))

# --- CUSTOMERS ---
@app.route("/customers", methods=["GET", "POST"])
@login_required
def customers():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        contact = request.form.get("contact", "").strip()
        customer_type = request.form.get("customer_type", "").strip()

        if len(name) < 2:
            return redirect(url_for("customers", err="Invalid Name: Customer or company name must be at least 2 characters."))
        if any(char.isdigit() for char in name):
            return redirect(url_for("customers", err="Invalid Name: Numbers are not allowed in the customer name."))
        if not re.match(r"^[A-Za-z\s.\-()]+$", name):
            return redirect(url_for("customers", err="Invalid Name: Please use alphabetic letters only."))

        if contact.upper() != "N/A":
            if not re.match(r"^[0-9\-\s]+$", contact):
                return redirect(url_for("customers", err="Invalid Contact: Phone number must contain digits only (e.g., 0917-555-0192)."))
            digits_only = re.sub(r"[\-\s]", "", contact)
            if not digits_only.startswith("0"):
                return redirect(url_for("customers", err="Invalid Contact: Mobile numbers must start with 0 (e.g., 0917-555-0192)."))
            if len(digits_only) != 11:
                return redirect(url_for("customers", err=f"Invalid Contact: Phone number must be exactly 11 digits (you entered {len(digits_only)})."))
            contact = f"{digits_only[:4]}-{digits_only[4:7]}-{digits_only[7:]}"

        if customer_type not in ["Retail", "Contractor", "Wholesale"]:
            return redirect(url_for("customers", err="Invalid Account Type selected."))

        database.add_customer(name, contact, customer_type)
        return redirect(url_for("customers", msg=f"Customer '{name}' ({contact}) added to directory!"))

    all_customers = database.get_all_customers()
    q = request.args.get("q", "").strip().lower()
    if q:
        all_customers = [c for c in all_customers if q in c["name"].lower() or q in c["contact"].lower()]

    return render_template(
        "customers.html",
        active_page="customers",
        customers=all_customers,
        search_text=q,
        can_undo=len(undo_stack) > 0,
        message=request.args.get("msg"),
        error=request.args.get("err")
    )

@app.route("/customers/delete/<int:cid>", methods=["POST"])
@login_required
def delete_customer(cid):
    database.delete_customer(cid)
    return redirect(url_for("customers", msg="Customer record removed."))

# --- REPORTS & CSV EXPORT ---
@app.route("/reports")
@login_required
def reports():
    products = database.get_all_products()
    sales = database.get_all_sales()
    sku_table = dsa_engine.build_sku_hash_table(products)

    sorted_by_price, _ = dsa_engine.merge_sort_with_telemetry(products, "price")
    total_valuation = sum(p["price"] * p["stock"] for p in products)
    collected_revenue = sum(s["total_amount"] for s in sales if s["payment_status"] == "Paid")
    unpaid_invoices = [s for s in sales if s["payment_status"] != "Paid"]
    total_units_sold = sum(s["qty_sold"] for s in sales)

    category_revenue = {}
    product_sales_agg = {}

    for s in sales:
        prod = sku_table.get(s["sku"])
        cat = prod["category"] if prod else "Other"
        category_revenue[cat] = category_revenue.get(cat, 0.0) + s["total_amount"]

        if s["sku"] not in product_sales_agg:
            product_sales_agg[s["sku"]] = {
                "sku": s["sku"],
                "name": s["product_name"],
                "units": 0,
                "revenue": 0.0
            }
        product_sales_agg[s["sku"]]["units"] += s["qty_sold"]
        product_sales_agg[s["sku"]]["revenue"] += s["total_amount"]

    top_sellers, _ = dsa_engine.merge_sort_with_telemetry(list(product_sales_agg.values()), "revenue")
    top_sellers = top_sellers[::-1][:5]

    return render_template(
        "reports.html",
        active_page="reports",
        products=products,
        sales=sales,
        unpaid_invoices=unpaid_invoices,
        top_sellers=top_sellers,
        highest_priced=sorted_by_price[-3:][::-1],
        cat_labels=list(category_revenue.keys()),
        cat_values=list(category_revenue.values()),
        total_valuation=total_valuation,
        collected_revenue=collected_revenue,
        total_units_sold=total_units_sold,
        can_undo=len(undo_stack) > 0
    )

@app.route("/export/csv/<report_type>")
@login_required
def export_csv(report_type):
    output = io.StringIO()
    writer = csv.writer(output)

    if report_type == "inventory":
        writer.writerow(["SKU", "Product Name", "Category", "Unit", "Unit Price", "Stock", "Total Value"])
        for p in database.get_all_products():
            writer.writerow([p["sku"], p["name"], p["category"], p["unit"], p["price"], p["stock"], round(p["price"] * p["stock"], 2)])
        filename = "hardware_inventory_report.csv"
    else:
        writer.writerow(["Invoice No", "SKU", "Product", "Customer", "Qty", "Total Amount", "Payment Method", "Status", "Due Date", "Timestamp"])
        for s in database.get_all_sales():
            writer.writerow([s["invoice_no"], s["sku"], s["product_name"], s["customer_name"], s["qty_sold"], s["total_amount"], s["payment_method"], s["payment_status"], s["due_date"], s["timestamp"]])
        filename = "hardware_sales_invoices.csv"

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )

@app.route("/undo", methods=["POST"])
@login_required
def undo():
    if not undo_stack:
        return redirect(request.referrer or url_for("dashboard", err="Nothing to undo: Action stack is empty."))

    last_action = undo_stack.pop()
    item = last_action["item"]
    database.add_or_update_product(
        item["sku"], item["name"], item["category"], item["unit"], item["price"], item["stock"]
    )
    if last_action["type"] == "sale":
        database.delete_last_sale()
    return redirect(request.referrer or url_for("dashboard", msg=f"Reverted last {last_action['type']} on {item['sku']}!"))

if __name__ == "__main__":
    app.run(debug=True)