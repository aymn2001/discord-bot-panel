import discord
from discord.ext import commands
import json
import os
import threading
from flask import Flask, request, jsonify, session, render_template

# ============================================================
#  الإعدادات - غيّرها
# ============================================================
TOKEN = "TOKEN_HERE"  # توكن البوت
ADMIN_USERS = {
    "admin": "password123",  # اسم المستخدم: كلمة السر
}
CONFIG_FILE = "roles_config.json"
# ============================================================

# Flask App
app = Flask(__name__)
app.secret_key = "super_secret_key_change_this"

# Bot
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
bot_thread = None
bot_running = False

# ============================================================
# Config Management
# ============================================================
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"roles": [], "stats": {}}

def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

# ============================================================
# Discord Bot
# ============================================================
@bot.event
async def on_ready():
    print(f"✅ البوت شغال: {bot.user}")

@bot.command(name="giverole")
async def give_role(ctx, member: discord.Member = None):
    if not member:
        await ctx.send("❌ حدد الشخص! مثال: `!giverole @شخص`")
        return

    config = load_config()
    author_role_names = [r.name for r in ctx.author.roles]

    matched = None
    for role_map in config["roles"]:
        if role_map["giver_role"] in author_role_names:
            matched = role_map
            break

    if not matched:
        await ctx.send("❌ ما عندك صلاحية إعطاء رتب.")
        return

    # Check limit
    giver_id = str(ctx.author.id)
    stats = config.get("stats", {})
    role_key = matched["giver_role"]
    role_stats = stats.get(role_key, {})
    count = role_stats.get(giver_id, 0)
    limit = matched.get("limit", 30)

    if count >= limit:
        await ctx.send(f"❌ وصلت للحد الأقصى ({limit} إعطاء).")
        return

    # Find target role
    target_role = discord.utils.get(ctx.guild.roles, name=matched["target_role"])
    if not target_role:
        await ctx.send(f"❌ الرتبة '{matched['target_role']}' ما موجودة في السيرفر.")
        return

    if target_role in member.roles:
        await ctx.send(f"⚠️ {member.mention} عنده الرتبة أصلاً.")
        return

    await member.add_roles(target_role)

    # Update stats
    if role_key not in stats:
        stats[role_key] = {}
    stats[role_key][giver_id] = count + 1
    config["stats"] = stats
    save_config(config)

    remaining = limit - (count + 1)
    await ctx.send(
        f"✅ تم إعطاء {member.mention} رتبة **{matched['target_role']}**!\n"
        f"📊 متبقي لك: {remaining}/{limit}"
    )

def run_bot():
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bot.start(TOKEN))

# ============================================================
# Flask Routes
# ============================================================
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

@app.route("/")
def index():
    if not session.get("logged_in"):
        return render_template("login.html")
    return render_template("panel.html", username=session.get("username"))

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    if ADMIN_USERS.get(data.get("username")) == data.get("password"):
        session["logged_in"] = True
        session["username"] = data.get("username")
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})

@app.route("/status")
@login_required
def status():
    global bot_running
    return jsonify({"running": bot_running and bot_thread and bot_thread.is_alive()})

@app.route("/start", methods=["POST"])
@login_required
def start():
    global bot_thread, bot_running
    if bot_thread and bot_thread.is_alive():
        return jsonify({"success": False, "message": "البوت شغال أصلاً"})
    try:
        bot_running = True
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        return jsonify({"success": True, "message": "تم تشغيل البوت ✅"})
    except Exception as e:
        bot_running = False
        return jsonify({"success": False, "message": str(e)})

@app.route("/stop", methods=["POST"])
@login_required
def stop():
    global bot_running
    import asyncio
    try:
        bot_running = False
        future = asyncio.run_coroutine_threadsafe(bot.close(), bot.loop)
        future.result(timeout=5)
        return jsonify({"success": True, "message": "تم إيقاف البوت 🛑"})
    except Exception as e:
        return jsonify({"success": False, "message": "تم الإيقاف"})

@app.route("/roles", methods=["GET"])
@login_required
def get_roles():
    config = load_config()
    return jsonify(config.get("roles", []))

@app.route("/roles", methods=["POST"])
@login_required
def add_role():
    data = request.json
    giver = data.get("giver_role", "").strip()
    target = data.get("target_role", "").strip()
    limit = int(data.get("limit", 30))
    if not giver or not target:
        return jsonify({"success": False, "message": "أدخل اسم الرتبتين"})
    config = load_config()
    # Check duplicate
    for r in config["roles"]:
        if r["giver_role"] == giver:
            return jsonify({"success": False, "message": f"الرتبة '{giver}' موجودة أصلاً"})
    config["roles"].append({"giver_role": giver, "target_role": target, "limit": limit})
    save_config(config)
    return jsonify({"success": True})

@app.route("/roles/<giver_role>", methods=["DELETE"])
@login_required
def delete_role(giver_role):
    config = load_config()
    config["roles"] = [r for r in config["roles"] if r["giver_role"] != giver_role]
    save_config(config)
    return jsonify({"success": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
