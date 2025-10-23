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

    if msg_data.get("task"):
        msg_data["task"].cancel()

    if msg_data.get("status") != "active":
        msg_data["task"] = None
        return

    target_channel_id = msg_data.get("channel_id") or CHANNEL_ID
    channel = bot.get_channel(target_channel_id) if target_channel_id else None
    if not channel:
        msg_data["status"] = "stopped"
        msg_data["task"] = None
        save_messages()
        return

    async def task_func():
        count = 0
        repeat = msg_data.get("repeat", 0)
        interval = msg_data.get("interval", 0)
        if not start_immediately and interval > 0:
            await asyncio.sleep(interval * 60)

        while True:
            if repeat != 0 and count >= repeat:
                msg_data["status"] = "stopped"
                break

            try:
                await channel.send(msg_data.get("message", ""))
            except Exception as e:
                print(f"❌ Грешка при пращане на съобщение ({msg_id}): {e}")
                break

            count += 1
            if interval <= 0:
                msg_data["status"] = "stopped"
                break

            try:
                await asyncio.sleep(interval * 60)
            except asyncio.CancelledError:
                break

        msg_data["task"] = None
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
# === Embed & статус ===
def build_configuration_embed(msg_data: dict, show_channel_public: bool = False) -> discord.Embed:
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

    channel_id = msg_data.get("channel_id") or CHANNEL_ID
    if show_channel_public:
        channel = bot.get_channel(channel_id) if channel_id else None
        value = channel.mention if channel else (f"#{channel.name}" if channel else "—")
        embed.add_field(name="Channel", value=value, inline=False)
    else:
        embed.add_field(name="Channel", value="🔒 (видимо само когато натиснеш Edit)", inline=False)

    embed.timestamp = datetime.utcnow()
    return embed

async def update_embed_status(msg_id: str):
    msg_data = active_messages.get(msg_id)
    if not msg_data:
        return
    channel = bot.get_channel(CHANNEL_ID) if CHANNEL_ID else None
    if not channel:
        return
    embed = build_configuration_embed(msg_data, show_channel_public=False)
    view = MessageButtons(msg_id)
    embed_message_id = msg_data.get("embed_message_id")
    try:
        if embed_message_id:
            try:
                embed_msg = await channel.fetch_message(embed_message_id)
            except discord.NotFound:
                embed_msg = await channel.send(embed=embed, view=view)
                msg_data["embed_message_id"] = embed_msg.id
            else:
                await embed_msg.edit(embed=embed, view=view)
        else:
            embed_msg = await channel.send(embed=embed, view=view)
            msg_data["embed_message_id"] = embed_msg.id
    except Exception as e:
        print(f"❌ Грешка при обновяване на embed ({msg_id}): {e}")
    save_messages()

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
        await restart_message_task(self.msg_id, start_immediately=True)
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
        if msg.get("task"):
            msg["task"].cancel()
        msg["status"] = "stopped"
        msg["task"] = None
        await update_embed_status(self.msg_id)
        save_messages()
        await interaction.response.send_message(f"⏹️ '{self.msg_id}' е спряно.", ephemeral=True)

    @discord.ui.button(emoji="❌", style=discord.ButtonStyle.gray)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права за тази операция.", ephemeral=True)
            return
        msg = active_messages.pop(self.msg_id, None)
        if msg:
            if msg.get("task"):
                msg["task"].cancel()
            embed_channel = bot.get_channel(CHANNEL_ID) if CHANNEL_ID else None
            if embed_channel and msg.get("embed_message_id"):
                try:
                    embed_msg = await embed_channel.fetch_message(msg["embed_message_id"])
                    await embed_msg.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass
            save_messages()
            await interaction.response.send_message(f"❌ '{self.msg_id}' е изтрито.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Не е намерено.", ephemeral=True)

    @discord.ui.button(emoji="✏️", style=discord.ButtonStyle.secondary)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права да редактираш съобщения.", ephemeral=True)
            return
        msg = active_messages.get(self.msg_id)
        if not msg:
            await interaction.response.send_message("❌ Не е намерено.", ephemeral=True)
            return
        channel_id = msg.get("channel_id") or CHANNEL_ID
        channel = bot.get_channel(channel_id) if channel_id else None
        ephemeral_embed = build_configuration_embed(msg, show_channel_public=True)
        await interaction.response.send_message(
            content="Какво искаш да редактираш?",
            embed=ephemeral_embed,
            view=EditSelectView(self.msg_id),
            ephemeral=True
        )

# === Edit select ===
class EditSelect(discord.ui.Select):
    def __init__(self, msg_id: str):
        options = [
            discord.SelectOption(label="Message Content", value="edit_content", emoji="📝"),
            discord.SelectOption(label="Time Interval", value="edit_interval", emoji="⏱️"),
            discord.SelectOption(label="Repeat Count", value="edit_repeat", emoji="🔁"),
            discord.SelectOption(label="Channel", value="edit_channel", emoji="💬")
        ]
        super().__init__(placeholder="Избери какво да редактираш", min_values=1, max_values=1, options=options)
        self.msg_id = msg_id

    async def callback(self, interaction: discord.Interaction):
        msg = active_messages.get(self.msg_id)
        if not msg:
            await interaction.response.send_message("❌ Тази задача липсва.", ephemeral=True)
            return
        choice = self.values[0]
        if choice == "edit_content":
            await interaction.response.send_modal(ContentEditModal(self.msg_id))
        elif choice == "edit_interval":
            await interaction.response.send_modal(IntervalEditModal(self.msg_id))
        elif choice == "edit_repeat":
            await interaction.response.send_modal(RepeatEditModal(self.msg_id))
        elif choice == "edit_channel":
            await interaction.response.send_message("Избери канал:", view=ChannelSelectView(self.msg_id), ephemeral=True)

class EditSelectView(discord.ui.View):
    def __init__(self, msg_id: str):
        super().__init__(timeout=120)
        self.add_item(EditSelect(msg_id))

# === Modal-и ===
class ContentEditModal(discord.ui.Modal):
    def __init__(self, msg_id: str):
        super().__init__(title="Edit Message Content")
        self.msg_id = msg_id
        current_content = get_stored_message_content(msg_id)
        self.new_content = discord.ui.TextInput(label="New Content", default=current_content[:1900])
        self.add_item(self.new_content)

    async def on_submit(self, interaction: discord.Interaction):
        update_message_content_value(self.msg_id, self.new_content.value)
        await restart_message_task(self.msg_id, start_immediately=False)
        await update_embed_status(self.msg_id)
        await interaction.response.send_message("✅ Съобщението беше обновено.", ephemeral=True)

class IntervalEditModal(discord.ui.Modal):
    def __init__(self, msg_id: str):
        super().__init__(title="Edit Interval")
        self.msg_id = msg_id
        current = get_stored_interval(msg_id) or 0
        self.new_interval = discord.ui.TextInput(label="Interval (min)", default=str(current))
        self.add_item(self.new_interval)

    async def on_submit(self, interaction: discord.Interaction):
        update_interval_value(self.msg_id, int(self.new_interval.value))
        await restart_message_task(self.msg_id, start_immediately=False)
        await update_embed_status(self.msg_id)
        await interaction.response.send_message("✅ Интервалът беше обновен.", ephemeral=True)

class RepeatEditModal(discord.ui.Modal):
    def __init__(self, msg_id: str):
        super().__init__(title="Edit Repeat Count")
        self.msg_id = msg_id
        current = get_stored_repeat(msg_id) or 0
        self.new_repeat = discord.ui.TextInput(label="Repeat Count (0 = ∞)", default=str(current))
        self.add_item(self.new_repeat)

    async def on_submit(self, interaction: discord.Interaction):
        update_repeat_value(self.msg_id, int(self.new_repeat.value))
        await restart_message_task(self.msg_id, start_immediately=False)
        await update_embed_status(self.msg_id)
        await interaction.response.send_message("✅ Настройката на повторенията беше обновена.", ephemeral=True)

# === ChannelSelect ===
class ChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, msg_id: str):
        super().__init__(placeholder="Избери текстов канал", channel_types=[discord.ChannelType.text])
        self.msg_id = msg_id

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        update_channel_value(self.msg_id, channel.id)
        await restart_message_task(self.msg_id, start_immediately=False)
        await update_embed_status(self.msg_id)
        await interaction.response.send_message(f"✅ Каналът беше обновен на {channel.mention}.", ephemeral=True)

class ChannelSelectView(discord.ui.View):
    def __init__(self, msg_id: str):
        super().__init__(timeout=120)
        self.add_item(ChannelSelect(msg_id))
        self.add_item(CancelButton())

class CancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Отказ", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("❌ Отказано.", ephemeral=True)

# === Команди ===
@tree.command(name="create", description="Създай автоматично съобщение.")
@app_commands.describe(message="Текст на съобщението", interval="Интервал в минути (>0)",
                       repeat="Брой повторения (0 = безкрайно)", id="Уникален идентификатор",
                       channel="Канал (по избор)")
async def create(interaction: discord.Interaction, message: str, interval: int, repeat: int, id: str, channel: Optional[discord.TextChannel] = None):
    if not has_permission(interaction.user):
        await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
        return
    if id in active_messages:
        await interaction.response.send_message(f"⚠️ '{id}' вече съществува.", ephemeral=True)
        return
    if interval <= 0:
        await interaction.response.send_message("❌ Интервалът трябва да е > 0.", ephemeral=True)
        return

    if not channel and CHANNEL_ID:
        channel = bot.get_channel(CHANNEL_ID)

    if not channel:
        await interaction.response.send_message("❌ Няма канал.", ephemeral=True)
        return

    msg_data = {
        "task": None,
        "message": message,
        "interval": interval,
        "repeat": repeat,
        "id": id,
        "creator": interaction.user.name,
        "status": "active",
        "channel_id": channel.id
    }
    active_messages[id] = msg_data
    save_messages()
    await restart_message_task(id, start_immediately=True)
    await update_embed_status(id)
    await interaction.response.send_message(f"✅ Създадено съобщение '{id}' в канал {channel.mention}.", ephemeral=True)
