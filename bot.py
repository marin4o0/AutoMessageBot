import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json

# === Environment Variables и проверки ===
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID_ENV = os.getenv("DISCORD_CHANNEL_ID")
GUILD_ID_ENV = os.getenv("GUILD_ID")  # ново

if not TOKEN:
    raise ValueError("❌ DISCORD_TOKEN не е зададено в environment variables")
if not CHANNEL_ID_ENV:
    raise ValueError("❌ DISCORD_CHANNEL_ID не е зададено в environment variables")
if not GUILD_ID_ENV:
    raise ValueError("❌ GUILD_ID не е зададено в environment variables")

try:
    CHANNEL_ID = int(CHANNEL_ID_ENV)
except ValueError:
    raise ValueError(f"❌ DISCORD_CHANNEL_ID трябва да е число, а е '{CHANNEL_ID_ENV}'")

try:
    GUILD_ID = int(GUILD_ID_ENV)
except ValueError:
    raise ValueError(f"❌ GUILD_ID трябва да е число, а е '{GUILD_ID_ENV}'")

guild = discord.Object(id=GUILD_ID)

print(f"✅ Env variables заредени успешно. Канал ID: {CHANNEL_ID}, Guild ID: {GUILD_ID}")

# === Intents ===
intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.message_content = True  # нужно за командите и четене на съобщения

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# === Конфигурация и променливи ===
SAVE_FILE = "active_messages.json"
ALLOWED_ROLES = ["Admin", "Moderator"]
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
            try:
                channel = bot.get_channel(CHANNEL_ID)
                embed_msg = await channel.fetch_message(msg["embed_message_id"])
                await embed_msg.delete()
            except Exception:
                pass
            await interaction.response.send_message(f"❌ '{self.msg_id}' е изтрито.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Не е намерено.", ephemeral=True)

# === Команди ===
@bot.event
async def on_ready():
    print(f"✅ Влязъл съм като {bot.user}")
    await tree.sync(guild=guild)  # локален sync за твоя сървър
    await load_messages()
    print("🔁 Възстановени активни съобщения.")
