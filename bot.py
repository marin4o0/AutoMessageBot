import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json

# === КОНФИГУРАЦИЯ ===
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
GUILD_ID = int(os.getenv("GUILD_ID"))
SAVE_FILE = "active_messages.json"

# Роли с достъп до админ команди
ALLOWED_ROLES = ["Admin", "Moderator"]

# === Intents ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
guild = discord.Object(id=GUILD_ID)

active_messages = {}  # ID → {данни, task, status, message_ref}

# === Помощни функции ===
def has_permission(user: discord.Member) -> bool:
    if user.guild_permissions.administrator:
        return True
    for role in user.roles:
        if role.name in ALLOWED_ROLES:
            return True
    return False

def save_messages():
    data = {}
    for msg_id, msg in active_messages.items():
        data[msg_id] = {
            "message": msg["message"],
            "interval": msg["interval"],
            "repeat": msg["repeat"],
            "id": msg["id"],
            "creator": msg["creator"],
            "status": msg.get("status", "active"),
            "embed_message_id": msg.get("embed_message_id")
        }
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

async def restart_message_task(msg_id, msg_data):
    if msg_data.get("status") != "active":
        return
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print(f"⚠️ Каналът с ID {CHANNEL_ID} не е намерен.")
        return

    async def task_func():
        count = 0
        while True:
            if msg_data["repeat"] != 0 and count >= msg_data["repeat"]:
                break
            await channel.send(msg_data["message"])
            count += 1
            await asyncio.sleep(msg_data["interval"] * 60)
        active_messages[msg_id]["status"] = "stopped"
        await update_embed_status(msg_id)
        save_messages()

    task = asyncio.create_task(task_func())
    active_messages[msg_id]["task"] = task

async def load_messages():
    if not os.path.exists(SAVE_FILE):
        return
    with open(SAVE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    for msg_id, msg in data.items():
        active_messages[msg_id] = msg
        active_messages[msg_id]["task"] = None
        await restart_message_task(msg_id, msg)

async def update_embed_status(msg_id):
    msg_data = active_messages.get(msg_id)
    if not msg_data or not msg_data.get("embed_message_id"):
        return
    channel = bot.get_channel(CHANNEL_ID)
    try:
        embed_msg = await channel.fetch_message(msg_data["embed_message_id"])
    except discord.NotFound:
        return
    embed = discord.Embed(
        title=f"🆔 {msg_data['id']} ({msg_data['status']})",
        description=f"💬 {msg_data['message']}\n⏱️ Интервал: {msg_data['interval']} мин\n🔁 Повторения: {'∞' if msg_data['repeat']==0 else msg_data['repeat']}\n👤 От: {msg_data['creator']}",
        color=discord.Color.green() if msg_data['status']=="active" else discord.Color.red()
    )
    await embed_msg.edit(embed=embed, view=MessageButtons(msg_id))

# === View с бутони ===
class MessageButtons(discord.ui.View):
    def __init__(self, msg_id):
        super().__init__(timeout=None)
        self.msg_id = msg_id

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.green)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права за тази операция.", ephemeral=True)
            return
        msg = active_messages.get(self.msg_id)
        if not msg:
            await interaction.response.send_message("❌ Не е намерено.", ephemeral=True)
            return
        if msg["status"] == "active":
            await interaction.response.send_message("⚠️ Вече е активно.", ephemeral=True)
            return
        msg["status"] = "active"
        await restart_message_task(self.msg_id, msg)
        await update_embed_status(self.msg_id)
        save_messages()
        await interaction.response.send_message(f"▶️ '{self.msg_id}' стартира отново.", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.blurple)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права за тази операция.", ephemeral=True)
            return
        msg = active_messages.get(self.msg_id)
        if not msg:
            await interaction.response.send_message("❌ Не е намерено.", ephemeral=True)
            return
        task = msg.get("task")
        if task:
            task.cancel()
        msg["status"] = "stopped"
        msg["task"] = None
        await update_embed_status(self.msg_id)
        save_messages()
        await interaction.response.send_message(f"⏹️ '{self.msg_id}' е спряно.", ephemeral=True)

    @discord.ui.button(emoji="❌", style=discord.ButtonStyle.red)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права за тази операция.", ephemeral=True)
            return
        msg = active_messages.pop(self.msg_id, None)
        if msg:
            task = msg.get("task")
            if task:
                task.cancel()
            save_messages()
            await interaction.response.send_message(f"❌ '{self.msg_id}' е изтрито.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Не е намерено.", ephemeral=True)

# === Команди ===
@bot.event
async def on_ready():
    print(f"✅ Влязъл съм като {bot.user}")
    try:
        await tree.sync(guild=guild)
        print(f"🔁 Командите са синхронизирани за guild {GUILD_ID}")
    except Exception as e:
        print(f"❌ Грешка при синхронизиране на командите: {e}")
    await load_messages()
    print("🔁 Възстановени активни съобщения.")

@tree.command(name="create", description="Създай автоматично съобщение.")
@app_commands.describe(
    message="Текст на съобщението",
    interval="Интервал в минути (>0)",
    repeat="Брой повторения (0 = безкрайно)",
    id="Уникален идентификатор"
)
async def create(interaction: discord.Interaction, message: str, interval: int, repeat: int, id: str):
    if not has_permission(interaction.user):
        await interaction.response.send_message("🚫 Нямаш права да създаваш съобщения.", ephemeral=True)
        return
    if id in active_messages:
        await interaction.response.send_message(f"⚠️ '{id}' вече съществува.", ephemeral=True)
        return
    if interval <= 0:
        await interaction.response.send_message("❌ Интервалът трябва да е > 0.", ephemeral=True)
        return

    channel = bot.get_channel(CHANNEL_ID)
    async def task_func():
        count = 0
        while True:
            if repeat != 0 and count >= repeat:
                break
            await channel.send(message)
            count += 1
            await asyncio.sleep(interval * 60)
        active_messages[id]["status"] = "stopped"
        await update_embed_status(id)
        save_messages()

    task = asyncio.create_task(task_func())
    msg_data = {
        "task": task,
        "message": message,
        "interval": interval,
        "repeat": repeat,
        "id": id,
        "creator": interaction.user.name,
        "status": "active"
    }
    active_messages[id] = msg_data
    save_messages()
    await interaction.response.send_message(f"✅ Създадено съобщение '{id}'.", ephemeral=True)

@tree.command(name="list", description="Покажи всички съобщения с бутони.")
async def list_messages(interaction: discord.Interaction):
    if not has_permission(interaction.user):
        await interaction.response.send_message("🚫 Нямаш права за тази команда.", ephemeral=True)
        return
    if not active_messages:
        await interaction.response.send_message("ℹ️ Няма съобщения.", ephemeral=True)
        return

    await interaction.response.send_message("📋 Всички активни съобщения:", ephemeral=True)
    for msg in active_messages.values():
        color = discord.Color.green() if msg["status"] == "active" else discord.Color.red()
        embed = discord.Embed(
            title=f"🆔 {msg['id']} ({msg['status']})",
            description=(
                f"💬 {msg['message']}\n"
                f"⏱️ Интервал: {msg['interval']} мин\n"
                f"🔁 Повторения: {'∞' if msg['repeat']==0 else msg['repeat']}\n"
                f"👤 От: {msg['creator']}"
            ),
            color=color
        )
        await interaction.followup.send(embed=embed, view=MessageButtons(msg["id"]), ephemeral=True)

@tree.command(name="help_create", description="Показва пример за /create")
async def help_create(interaction: discord.Interaction):
    if not has_permission(interaction.user):
        await interaction.response.send_message("🚫 Нямаш права за тази команда.", ephemeral=True)
        return
    example = (
        "🧠 **Пример:**\n"
        "```\n"
        "/create message:\"Райд след 1 час!\" interval:120 repeat:0 id:\"raid\"\n"
        "```\n"
        "- `message`: Текст на съобщението\n"
        "- `interval`: Интервал в минути\n"
        "- `repeat`: Повторения (0 = безкрайно)\n"
        "- `id`: Име на съобщението"
    )
    await interaction.response.send_message(example, ephemeral=True)

# === Стартиране на бота ===
bot.run(TOKEN)
