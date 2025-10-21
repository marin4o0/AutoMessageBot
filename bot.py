import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
from typing import Optional

# === КОНФИГУРАЦИЯ ===
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
GUILD_ID = int(os.getenv("GUILD_ID"))
SAVE_FILE = "active_messages.json"

ALLOWED_ROLES = ["Admin", "Moderator"]

# === INTENTS ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
guild = discord.Object(id=GUILD_ID)

active_messages = {}

# === ПОМОЩНИ ФУНКЦИИ ===
def has_permission(user: discord.Member) -> bool:
    if user.guild_permissions.administrator:
        return True
    return any(role.name in ALLOWED_ROLES for role in user.roles)

def has_edit_permission(member: discord.Member) -> bool:
    return has_permission(member)

def save_messages():
    data = {
        msg_id: {
            "message": msg["message"],
            "interval": msg["interval"],
            "repeat": msg["repeat"],
            "id": msg["id"],
            "creator": msg["creator"],
            "status": msg.get("status", "active"),
            "embed_message_id": msg.get("embed_message_id")
        }
        for msg_id, msg in active_messages.items()
    }
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def record_embed_message_id(msg_id: str, message_id: Optional[int]):
    msg_data = active_messages.get(msg_id)
    if msg_data and msg_data.get("embed_message_id") != message_id:
        msg_data["embed_message_id"] = message_id
        save_messages()

def get_message_data(msg_id: str) -> Optional[dict]:
    return active_messages.get(msg_id)

# === EMBED ===
def build_configuration_embed(msg_data: dict) -> discord.Embed:
    status = msg_data.get("status", "unknown")
    color = discord.Color.green() if status == "active" else discord.Color.red()
    repeat_display = "∞" if msg_data.get("repeat") == 0 else str(msg_data.get("repeat", "-"))
    embed = discord.Embed(
        title=f"🆔 {msg_data.get('id', 'unknown')} ({status})",
        color=color
    )
    embed.add_field(name="Message", value=msg_data.get("message", "-"), inline=False)
    embed.add_field(name="Interval", value=f"{msg_data.get('interval', '-') } мин", inline=True)
    embed.add_field(name="Repeat", value=repeat_display, inline=True)
    embed.add_field(name="Creator", value=msg_data.get("creator", "-") or "-", inline=False)
    embed.timestamp = discord.utils.utcnow()
    embed.set_footer(text="Последна промяна")
    return embed

# === ОБНОВЯВАНЕ НА EMBED ===
async def update_embed_status(msg_id):
    msg_data = active_messages.get(msg_id)
    if not msg_data:
        return
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print(f"⚠️ Каналът {CHANNEL_ID} не е намерен.")
        return
    embed = build_configuration_embed(msg_data)
    view = MessageButtons(msg_id)
    embed_message_id = msg_data.get("embed_message_id")
    try:
        if embed_message_id:
            try:
                embed_msg = await channel.fetch_message(embed_message_id)
                await embed_msg.edit(embed=embed, view=view)
            except discord.NotFound:
                embed_msg = await channel.send(embed=embed, view=view)
                record_embed_message_id(msg_id, embed_msg.id)
        else:
            embed_msg = await channel.send(embed=embed, view=view)
            record_embed_message_id(msg_id, embed_msg.id)
    except discord.HTTPException as e:
        print(f"❌ Грешка при обновяване на embed: {e}")

# === РЕСТАРТ НА СЪОБЩЕНИЕ ===
async def restart_message_task(msg_id: str):
    msg_data = active_messages.get(msg_id)
    if not msg_data:
        return
    existing_task = msg_data.get("task")
    if existing_task:
        existing_task.cancel()
    if msg_data.get("status") != "active":
        msg_data["task"] = None
        return
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        msg_data["status"] = "stopped"
        msg_data["task"] = None
        save_messages()
        return

    async def task_func():
        count = 0
        try:
            while True:
                if msg_data["repeat"] != 0 and count >= msg_data["repeat"]:
                    break
                await channel.send(msg_data["message"])
                count += 1
                interval = msg_data.get("interval", 0)
                if interval <= 0:
                    break
                await asyncio.sleep(interval * 60)
        except asyncio.CancelledError:
            pass
        finally:
            msg_data["task"] = None
            msg_data["status"] = "stopped"
            await update_embed_status(msg_id)
            save_messages()

    msg_data["task"] = asyncio.create_task(task_func())
    save_messages()

# === VIEW С БУТОНИ ===
class MessageButtons(discord.ui.View):
    def __init__(self, msg_id):
        super().__init__(timeout=None)
        self.msg_id = msg_id

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.green)
    async def start_button(self, interaction, button):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
        msg = active_messages.get(self.msg_id)
        if not msg:
            return await interaction.response.send_message("❌ Не е намерено.", ephemeral=True)
        msg["status"] = "active"
        await restart_message_task(self.msg_id)
        await update_embed_status(self.msg_id)
        save_messages()
        await interaction.response.send_message("✅ Стартирано.", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.blurple)
    async def stop_button(self, interaction, button):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
        msg = active_messages.get(self.msg_id)
        if not msg:
            return await interaction.response.send_message("❌ Не е намерено.", ephemeral=True)
        task = msg.get("task")
        if task:
            task.cancel()
        msg["status"] = "stopped"
        await update_embed_status(self.msg_id)
        save_messages()
        await interaction.response.send_message("⏹️ Спиране успешно.", ephemeral=True)

    @discord.ui.button(emoji="❌", style=discord.ButtonStyle.red)
    async def delete_button(self, interaction, button):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
        msg = active_messages.pop(self.msg_id, None)
        if msg and (task := msg.get("task")):
            task.cancel()
        save_messages()
        await interaction.response.send_message("🗑️ Изтрито успешно.", ephemeral=True)

# === КОМАНДИ ===
@bot.event
async def on_ready():
    print(f"✅ Влязъл съм като {bot.user}")
    await tree.sync(guild=guild)
    print(f"🔁 Командите са синхронизирани за guild {GUILD_ID}")

@tree.command(name="create", description="Създай автоматично съобщение.")
@app_commands.describe(message="Текст", interval="Интервал (в минути)", repeat="Повторения (0=∞)", id="Уникално ID")
async def create(interaction, message: str, interval: int, repeat: int, id: str):
    if not has_permission(interaction.user):
        return await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
    if id in active_messages:
        return await interaction.response.send_message("⚠️ ID вече съществува.", ephemeral=True)
    if interval <= 0:
        return await interaction.response.send_message("⚠️ Интервалът трябва да е > 0.", ephemeral=True)

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return await interaction.response.send_message("⚠️ Каналът не е намерен.", ephemeral=True)

    sent_msg = await channel.send(message)  # 👈 само самото съобщение е видимо

    msg_data = {
        "task": None,
        "message": message,
        "interval": interval,
        "repeat": repeat,
        "id": id,
        "creator": interaction.user.name,
        "status": "active",
        "embed_message_id": None
    }
    active_messages[id] = msg_data
    save_messages()
    await restart_message_task(id)

    # embed само за админа (ephemeral)
    embed = build_configuration_embed(msg_data)
    view = MessageButtons(id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@tree.command(name="list", description="Покажи всички активни съобщения.")
async def list_messages(interaction):
    if not has_permission(interaction.user):
        return await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
    if not active_messages:
        return await interaction.response.send_message("ℹ️ Няма активни съобщения.", ephemeral=True)
    for msg in active_messages.values():
        embed = build_configuration_embed(msg)
        await interaction.followup.send(embed=embed, view=MessageButtons(msg["id"]), ephemeral=True)
    await interaction.response.send_message("📋 Списък с активни съобщения:", ephemeral=True)

# === СТАРТ ===
bot.run(TOKEN)
