
from flask import Flask, request, render_template_string
import sqlite3

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html lang="uz">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>USTA 24 — Andijon</title>
    <style>
        body { font-family: Arial; background: #f3f4f6; margin: 0; }
        header { background: #123b63; color: white; padding: 25px; text-align: center; }
        main { max-width: 500px; margin: 25px auto; padding: 20px; background: white; border-radius: 12px; }
        input, select, textarea, button {
            width: 100%; padding: 12px; margin: 8px 0;
            box-sizing: border-box; font-size: 16px;
        }
        button { background: #123b63; color: white; border: 0; cursor: pointer; }
        a { color: white; }
    </style>
</head>
<body>
<header>
    <h1>USTA 24</h1>
    <p>Andijondagi ishonchli ustalar xizmati</p>
    <p>Telefon: +998 77 069 00 03</p>
</header>
<main>
    <h2>Buyurtma berish</h2>
    {% if message %}<p>{{ message }}</p>{% endif %}
    <form method="POST">
        <input name="name" placeholder="Ismingiz" required>
        <input name="phone" placeholder="Telefon raqamingiz" required>
        <select name="service" required>
            <option value="">Xizmat turini tanlang</option>
            <option>Elektrik</option>
            <option>Santexnik</option>
            <option>Mebel ishlari</option>
            <option>Uy ta'miri</option>
            <option>Konditsioner</option>
            <option>Boshqa xizmat</option>
        </select>
        <input name="address" placeholder="Manzilingiz" required>
        <textarea name="details" placeholder="Qanday ish kerak?"></textarea>
        <button type="submit">Buyurtma yuborish</button>
    </form>
</main>
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def home():
    message = ""

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        service = request.form.get("service", "").strip()
        address = request.form.get("address", "").strip()
        details = request.form.get("details", "").strip()

        if name and phone and service and address:
            with sqlite3.connect("website_orders.db") as db:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS orders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT,
                        phone TEXT,
                        service TEXT,
                        address TEXT,
                        details TEXT
                    )
                """)
                db.execute(
                    "INSERT INTO orders (name, phone, service, address, details) VALUES (?, ?, ?, ?, ?)",
                    (name, phone, service, address, details)
                )
            message = "Buyurtmangiz qabul qilindi!"
        else:
            message = "Iltimos, barcha kerakli maydonlarni to‘ldiring."

    return render_template_string(HTML, message=message)

if __name__ == "__main__":
    app.run()
