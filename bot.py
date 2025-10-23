import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
from typing import Optional
from datetime import datetime

# === КОНФИГУРАЦИЯ ===
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID")) if os.getenv("DISCORD_CHANNEL_ID") else None
GUILD_ID = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID") else None
SAVE_FILE = "active_messages.json"
ALLOWED_ROLES = ["Admin", "Moderator"]

# === Intents ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
guild = discord.Object(id=GUILD_ID) if GUILD_ID else None

active_messages = {}

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
            "message": msg.get("message"),
            "interval": msg.get("interval"),
            "repeat": msg.get("repeat"),
            "id": msg.get("id"),
            "creator": msg.get("creator"),
            "status": msg.get("status", "active"),
            "channel_id": msg.get("channel_id", None)
        }
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def get_message_data(msg_id: str) -> Optional[dict]:
    return active_messages.get(msg_id)

def get_stored_message_content(msg_id: str) -> str:
    data = get_message_data(msg_id)
    return data.get("message", "") if data else ""

def get_stored_interval(msg_id: str) -> Optional[int]:
    data = get_message_data(msg_id)
    return data.get("interval") if data else None

def get_stored_repeat(msg_id: str) -> Optional[int]:
    data = get_message_data(msg_id)
    return data.get("repeat") if data else None

def get_stored_channel_id(msg_id: str) -> Optional[int]:
    data = get_message_data(msg_id)
    return data.get("channel_id") if data else None

def update_message_content_value(msg_id: str, new_content: str) -> None:
    data = get_message_data(msg_id)
    if not data:
        raise KeyError(msg_id)
    data["message"] = new_content
    save_messages()

def update_interval_value(msg_id: str, new_interval: int) -> None:
    data = get_message_data(msg_id)
    if not data:
        raise KeyError(msg_id)
    data["interval"] = new_interval
    save_messages()

def update_repeat_value(msg_id: str, new_repeat: int) -> None:
    data = get_message_data(msg_id)
    if not data:
        raise KeyError(msg_id)
    data["repeat"] = new_repeat
    save_messages()

def update_channel_value(msg_id: str, new_channel_id: Optional[int]) -> None:
    data = get_message_data(msg_id)
    if not data:
        raise KeyError(msg_id)
    data["channel_id"] = new_channel_id
    save_messages()

# === Task за автоматични съобщения ===
async def restart_message_task(msg_id: str, start_immediately: bool = True):
    msg_data = active_messages.get(msg_id)
    if not msg_data:
        return

    existing_task = msg_data.get("task")
    if existing_task:
        existing_task.cancel()

    if msg_data.get("status") != "active":
        msg_data["task"] = None
        return

    target_channel_id = msg_data.get("channel_id") or CHANNEL_ID
    channel = bot.get_channel(target_channel_id) if target_channel_id else None
    if not channel:
        print(f"⚠️ Каналът с ID {target_channel_id} не е намерен за задача {msg_id}.")
        msg_data["status"] = "stopped"
        msg_data["task"] = None
        save_messages()
        return

    async def task_func():
        count = 0
        completed_naturally = False
        try:
            interval_minutes = msg_data.get("interval", 0)
            if not start_immediately and interval_minutes > 0:
                try:
                    await asyncio.sleep(interval_minutes * 60)
                except asyncio.CancelledError:
                    raise

            while True:
                if msg_data.get("repeat", 0) != 0 and count >= msg_data.get("repeat", 0):
                    completed_naturally = True
                    break
                try:
                    await channel.send(msg_data.get("message", ""))
                except Exception as e:
                    print(f"❌ Грешка при пращане на съобщение ({msg_id}): {e}")
                count += 1
                if interval_minutes <= 0:
                    completed_naturally = True
                    break
                try:
                    await asyncio.sleep(interval_minutes * 60)
                except asyncio.CancelledError:
                    raise
        except asyncio.CancelledError:
            pass
        finally:
            current_data = active_messages.get(msg_id)
            if current_data:
                current_data["task"] = None
                if completed_naturally:
                    current_data["status"] = "stopped"
                    save_messages()

    msg_data["task"] = asyncio.create_task(task_func())
    save_messages()

async def load_messages():
    if not os.path.exists(SAVE_FILE):
        return
    with open(SAVE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    for msg_id, msg in data.items():
        active_messages[msg_id] = msg
        active_messages[msg_id]["task"] = None
        await restart_message_task(msg_id, start_immediately=True)

# === Embed Helper ===
def build_info_embed(msg_data: dict) -> discord.Embed:
    status = msg_data.get("status", "unknown")
    color = discord.Color.green() if status == "active" else discord.Color.red()
    repeat_display = '∞' if msg_data.get('repeat', 0) == 0 else str(msg_data.get('repeat'))
    channel_id = msg_data.get('channel_id')
    channel_mention = f'<#{channel_id}>' if channel_id else '—'

    embed = discord.Embed(title=f"🆔 {msg_data.get('id')} ({status})", color=color)
    embed.add_field(name="Message", value=msg_data.get('message', '-'), inline=False)
    embed.add_field(name="Interval", value=f"{msg_data.get('interval', '-') } мин", inline=True)
    embed.add_field(name="Repeat", value=repeat_display, inline=True)
    embed.add_field(name="Creator", value=f"{msg_data.get('creator', '-')}", inline=False)
    embed.add_field(name="Channel", value=channel_mention, inline=False)
    embed.timestamp = datetime.utcnow()
    return embed

# === Edit Modal и ChannelSelect ===
class EditModal(discord.ui.Modal):
    def __init__(self, msg_id: str):
        super().__init__(title="Edit Message")
        self.msg_id = msg_id
        self.content_input = discord.ui.TextInput(label="Message", default=get_stored_message_content(msg_id)[:1900])
        self.interval_input = discord.ui.TextInput(label="Interval (minutes)", default=str(get_stored_interval(msg_id) or 0))
        self.repeat_input = discord.ui.TextInput(label="Repeat count (0=∞)", default=str(get_stored_repeat(msg_id) or 0))
        self.add_item(self.content_input)
        self.add_item(self.interval_input)
        self.add_item(self.repeat_input)

    async def on_submit(self, interaction: discord.Interaction):
        update_message_content_value(self.msg_id, self.content_input.value)
        update_interval_value(self.msg_id, int(self.interval_input.value))
        update_repeat_value(self.msg_id, int(self.repeat_input.value))
        await interaction.response.send_message("✅ Съобщението беше обновено.", ephemeral=True)

class ChannelSelect(discord.ui.Select):
    def __init__(self, msg_id: str):
        self.msg_id = msg_id
        options = []
        for guild_channel in bot.get_all_channels():
            if isinstance(guild_channel, discord.TextChannel):
                options.append(discord.SelectOption(label=guild_channel.name, value=str(guild_channel.id)))
        super().__init__(placeholder="Избери канал", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        update_channel_value(self.msg_id, int(self.values[0]))
        await interaction.response.send_message("✅ Каналът беше обновен.", ephemeral=True)

# === FullMessageButtons с Edit бутон ===
class FullMessageButtons(discord.ui.View):
    def __init__(self, msg_id: str):
        super().__init__(timeout=None)
        self.msg_id = msg_id
        # Старт, стоп и изтриване
        self.add_item(discord.ui.Button(label="Start", style=discord.ButtonStyle.green, custom_id=f"start_{msg_id}"))
        self.add_item(discord.ui.Button(label="Stop", style=discord.ButtonStyle.blurple, custom_id=f"stop_{msg_id}"))
        self.add_item(discord.ui.Button(label="Delete", style=discord.ButtonStyle.red, custom_id=f"delete_{msg_id}"))
        # Edit бутон
        self.add_item(discord.ui.Button(label="Edit", style=discord.ButtonStyle.blurple, custom_id=f"edit_{msg_id}"))

# === Commands /create and /list ===
@tree.command(name="create", description="Създай ново автоматично съобщение.")
@app_commands.describe(
    message="Текст на съобщението",
    interval="Интервал в минути",
    repeat="Брой повторения (0=∞)",
    id="Уникален идентификатор",
    channel="Канал за съобщението"
)
async def create(interaction: discord.Interaction, message: str, interval: int, repeat: int, id: str, channel: Optional[discord.TextChannel] = None):
    if not has_permission(interaction.user):
        await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
        return
    if id in active_messages:
        await interaction.response.send_message(f"⚠️ Съобщение с id '{id}' вече съществува.", ephemeral=True)
        return
    channel_id_for_task = channel.id if channel else (CHANNEL_ID if CHANNEL_ID else None)
    if channel_id_for_task is None:
        await interaction.response.send_message("❌ Не е зададен канал.", ephemeral=True)
        return
    msg_data = {
        "task": None,
        "message": message,
        "interval": interval,
        "repeat": repeat,
        "id": id,
        "creator": interaction.user.name,
        "status": "active",
        "channel_id": channel_id_for_task
    }
    active_messages[id] = msg_data
    save_messages()
    await restart_message_task(id, start_immediately=True)
    await interaction.response.send_message(f"✅ Създадено съобщение '{id}'.", ephemeral=True)

@tree.command(name="list", description="Покажи всички съобщения с бутони.")
async def list_messages(interaction: discord.Interaction):
    if not has_permission(interaction.user):
        await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
        return
    if not active_messages:
        await interaction.response.send_message("ℹ️ Няма съобщения.", ephemeral=True)
        return
    await interaction.response.send_message("📋 Всички съобщения:", ephemeral=True)
    for msg in active_messages.values():
        embed = build_info_embed(msg)
        await interaction.followup.send(embed=embed, view=FullMessageButtons(msg['id']), ephemeral=True)

# === Стартиране на бота ===
@bot.event
async def on_ready():
    print(f"✅ Влязъл съм като {bot.user}")
    if guild:
        await tree.sync(guild=guild)
    else:
        await tree.sync()
    await load_messages()

if not TOKEN:
    print("❌ Не е зададен DISCORD_TOKEN.")
else:
    bot.run(TOKEN)
