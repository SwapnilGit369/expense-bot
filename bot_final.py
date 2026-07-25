import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from datetime import datetime
import requests
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============= CONFIGURATION =============
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
SUPABASE_URL = "YOUR_SUPABASE_PROJECT_URL"
SUPABASE_KEY = "YOUR_SUPABASE_ANON_KEY"
GROQ_API_KEY = "YOUR_GROQ_API_KEY"

groq_client = Groq(api_key=GROQ_API_KEY)

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

# ============= SUPABASE REST =============

def sb_get(table, params=""):
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
    r = requests.get(url, headers=HEADERS)
    return r.json()

def sb_post(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    r = requests.post(url, headers=HEADERS, json=data)
    return r.json()

def sb_delete(table, row_id):
    url = f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{row_id}"
    r = requests.delete(url, headers=HEADERS)
    return r.status_code

# ============= HELPERS =============

def get_category_id(category_name):
    data = sb_get("categories", f"name=ilike.{category_name}&select=id,name")
    if data and isinstance(data, list) and len(data) > 0:
        return data[0]['id']
    data = sb_get("categories", "name=eq.Other&select=id")
    if data and len(data) > 0:
        return data[0]['id']
    return None

def get_all_categories():
    data = sb_get("categories", "select=id,name&order=name")
    return data if isinstance(data, list) else []

def add_expense_db(amount, category_id, description, source="telegram"):
    data = {
        "amount": amount,
        "category_id": category_id,
        "description": description,
        "date": datetime.now().date().isoformat(),
        "source": source
    }
    return sb_post("expenses", data)

def get_last_expense():
    data = sb_get("expenses", "select=id,amount,description&order=created_at.desc&limit=1")
    if data and isinstance(data, list) and len(data) > 0:
        return data[0]
    return None

def parse_quick_expense(text):
    parts = text.strip().split(maxsplit=2)
    if len(parts) < 2:
        return None
    try:
        amount = float(parts[0])
        category = parts[1]
        description = parts[2] if len(parts) > 2 else ""
        return {"amount": amount, "category": category, "description": description}
    except:
        return None

def get_monthly_summary():
    today = datetime.now()
    month_start = today.replace(day=1).date().isoformat()
    data = sb_get("expenses", f"select=amount,categories(name)&date=gte.{month_start}")

    if not data or not isinstance(data, list) or len(data) == 0:
        return "Is mahine koi expense nahi hai abhi tak."

    total = sum(float(exp['amount']) for exp in data)
    cat_summary = {}
    for exp in data:
        cat = exp['categories']['name'] if exp.get('categories') else "Other"
        cat_summary[cat] = cat_summary.get(cat, 0) + float(exp['amount'])

    text = f"Is Mahine ka Summary ({today.strftime('%B %Y')})\n\n"
    text += f"Total Kharch: Rs.{total:,.0f}\n\n"
    text += "Category Wise:\n"
    for cat, amt in sorted(cat_summary.items(), key=lambda x: x[1], reverse=True):
        text += f"  {cat}: Rs.{amt:,.0f}\n"
    return text

def get_today_summary():
    today = datetime.now().date().isoformat()
    data = sb_get("expenses", f"select=amount,description,categories(name)&date=eq.{today}&order=created_at.desc")

    if not data or not isinstance(data, list) or len(data) == 0:
        return "Aaj koi expense nahi hai."

    total = sum(float(exp['amount']) for exp in data)
    text = f"Aaj ka Kharch ({today})\n\n"
    for exp in data:
        cat = exp['categories']['name'] if exp.get('categories') else "Other"
        desc = f" - {exp['description']}" if exp.get('description') else ""
        text += f"  Rs.{float(exp['amount']):,.0f} ({cat}){desc}\n"
    text += f"\nTotal: Rs.{total:,.0f}"
    return text

def get_ai_response(query):
    try:
        today = datetime.now()
        month_start = today.replace(day=1).date().isoformat()
        data = sb_get("expenses", f"select=amount,description,date,categories(name)&date=gte.{month_start}&order=date.desc&limit=100")

        expenses_text = "Is mahine ke expenses:\n"
        if data and isinstance(data, list):
            for exp in data:
                cat = exp['categories']['name'] if exp.get('categories') else "Other"
                expenses_text += f"- {exp['date']}: Rs.{exp['amount']} ({cat}) {exp.get('description','')}\n"
        else:
            expenses_text += "Koi data nahi mila.\n"

        prompt = f"""You are a helpful personal finance assistant.
Answer in the same language as the user's query (Hindi/Hinglish/English).
Be concise and helpful. Max 150 words.

{expenses_text}

User query: {query}"""

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300
        )
        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"Groq error: {e}")
        return "AI se response nahi mila. Baad mein try karo."

# ============= HANDLERS =============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """Expense Tracker Bot

Quick Add - seedha type karo:
500 food lunch
200 fuel petrol

Commands:
/add 500 food lunch
/today - Aaj ka summary
/summary - Monthly summary
/undo - Last expense delete
/ask <question> - AI se poocho
/categories - All categories
/help - Help"""
    await update.message.reply_text(text)

async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Format: /add <amount> <category> <description>\nExample: /add 500 food lunch")
        return

    text = " ".join(context.args)
    parsed = parse_quick_expense(text)

    if not parsed:
        await update.message.reply_text("Format galat hai! Use: /add 500 food lunch")
        return

    category_id = get_category_id(parsed['category'])
    if not category_id:
        await update.message.reply_text(f"Category '{parsed['category']}' nahi mili! /categories se dekho.")
        return

    result = add_expense_db(parsed['amount'], category_id, parsed['description'])
    if result and isinstance(result, list):
        await update.message.reply_text(f"Added!\nRs.{parsed['amount']:,.0f} - {parsed['category'].capitalize()}\n{parsed['description']}")
    else:
        await update.message.reply_text("Error adding expense. Try again.")

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_today_summary())

async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_monthly_summary())

async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last = get_last_expense()
    if not last:
        await update.message.reply_text("Koi expense nahi mili delete karne ke liye.")
        return
    sb_delete("expenses", last['id'])
    await update.message.reply_text(f"Deleted!\nRs.{last['amount']} - {last.get('description','')}")

async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Example: /ask is mahine sabse zyada kharch kahan hua?")
        return
    query = " ".join(context.args)
    await update.message.reply_text("Soch raha hoon...")
    response = get_ai_response(query)
    await update.message.reply_text(response)

async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cats = get_all_categories()
    if not cats:
        await update.message.reply_text("Koi category nahi mili.")
        return
    text = "Categories:\n"
    for cat in cats:
        text += f"  {cat['name']}\n"
    await update.message.reply_text(text)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """Help

Quick Add (seedha type karo):
  500 food lunch
  200 fuel petrol
  1500 kirana weekly sabzi

Commands:
  /add <amount> <category> <desc>
  /today - Aaj ka kharch
  /summary - Monthly summary
  /undo - Last entry delete
  /ask <question> - AI se poocho
  /categories - All categories

Categories: Food, Fuel, Kirana, Clothes, Medical, Bills, SIP, EMI, Other"""
    await update.message.reply_text(text)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parsed = parse_quick_expense(text)

    if parsed and parsed['amount'] > 0:
        category_id = get_category_id(parsed['category'])
        if category_id:
            result = add_expense_db(parsed['amount'], category_id, parsed['description'])
            if result and isinstance(result, list):
                await update.message.reply_text(f"Added! Rs.{parsed['amount']:,.0f} - {parsed['category'].capitalize()}")
            else:
                await update.message.reply_text("DB error. Try again.")
        else:
            await update.message.reply_text(f"'{parsed['category']}' category nahi mili.\n/categories se valid category dekho.")
    else:
        await update.message.reply_text("Format samajh nahi aaya.\nTry: 500 food lunch\nYa /help dekho.")

# ============= MAIN =============

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("undo", cmd_undo))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(CommandHandler("categories", cmd_categories))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Bot starting...")
    app.run_polling()

if __name__ == '__main__':
    main()
