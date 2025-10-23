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

def has_edit_permission(member: discord.Member) -> bool:
    return has_permission(member)

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
                except discord.Forbidden:
                    print(f"❌ Нямам права да пусна съобщение в канал {target_channel_id}.")
                    completed_naturally = True
                    break
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

# === Views и Modals ===
class MessageButtons(discord.ui.View):
    def __init__(self, msg_id):
        super().__init__(timeout=None)
        self.msg_id = msg_id

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.green)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
            return
        msg = active_messages.get(self.msg_id)
        if msg["status"] == "active":
            await interaction.response.send_message("⚠️ Вече е активно.", ephemeral=True)
            return
        msg["status"] = "active"
        await restart_message_task(self.msg_id, start_immediately=True)
        await interaction.response.send_message(f"▶️ '{self.msg_id}' стартирано.", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.blurple)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
            return
        msg = active_messages.get(self.msg_id)
        task = msg.get("task")
        if task: task.cancel()
        msg["status"] = "stopped"
        msg["task"] = None
        await interaction.response.send_message(f"⏹️ '{self.msg_id}' е спряно.", ephemeral=True)

    @discord.ui.button(emoji="❌", style=discord.ButtonStyle.gray)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
            return
        msg = active_messages.pop(self.msg_id, None)
        if msg:
            task = msg.get("task")
            if task: task.cancel()
        await interaction.response.send_message(f"❌ '{self.msg_id}' изтрито.", ephemeral=True)

    @discord.ui.button(emoji="✏️", style=discord.ButtonStyle.secondary)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_edit_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права за редакция.", ephemeral=True)
            return
        msg = active_messages.get(self.msg_id)
        ephemeral_embed = discord.Embed(title=f"Редакция: {self.msg_id}", description=f"Съобщение: {msg['message']}", color=discord.Color.blue())
        await interaction.response.send_message(embed=ephemeral_embed, view=EditSelectView(self.msg_id), ephemeral=True)

class EditSelect(discord.ui.Select):
    def __init__(self, msg_id: str):
        options = [
            discord.SelectOption(label="Message Content", value="edit_content"),
            discord.SelectOption(label="Interval", value="edit_interval"),
            discord.SelectOption(label="Repeat", value="edit_repeat"),
            discord.SelectOption(label="Channel", value="edit_channel")
        ]
        super().__init__(placeholder="Избери какво да редактираш", min_values=1, max_values=1, options=options)
        self.msg_id = msg_id

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        if selected == "edit_content":
            await interaction.response.send_modal(ContentEditModal(self.msg_id))
        elif selected == "edit_interval":
            await interaction.response.send_modal(IntervalEditModal(self.msg_id))
        elif selected == "edit_repeat":
            await interaction.response.send_modal(RepeatEditModal(self.msg_id))
        elif selected == "edit_channel":
            await interaction.response.send_message("Избери канал:", view=ChannelSelectView(self.msg_id), ephemeral=True)

class EditSelectView(discord.ui.View):
    def __init__(self, msg_id: str):
        super().__init__(timeout=120)
        self.add_item(EditSelect(msg_id))

# === Modals за съдържание, интервал, repeat и канал (епhemeral) ===
class ContentEditModal(discord.ui.Modal):
    def __init__(self, msg_id: str):
        super().__init__(title="Edit Message Content")
        self.msg_id = msg_id
        self.new_content = discord.ui.TextInput(label="New Message Content", default=get_stored_message_content(msg_id)[:1900])
        self.add_item(self.new_content)

    async def on_submit(self, interaction: discord.Interaction):
        update_message_content_value(self.msg_id, self.new_content.value)
        msg = active_messages.get(self.msg_id)
        if msg.get("status") == "active":
            await restart_message_task(self.msg_id, start_immediately=False)
        await interaction.response.send_message("✅ Съобщението беше обновено.", ephemeral=True)

class IntervalEditModal(discord.ui.Modal):
    def __init__(self, msg_id: str):
        super().__init__(title="Edit Interval")
        self.msg_id = msg_id
        self.new_interval = discord.ui.TextInput(label="Interval (minutes)", default=str(get_stored_interval(msg_id) or 0))
        self.add_item(self.new_interval)

    async def on_submit(self, interaction: discord.Interaction):
        update_interval_value(self.msg_id, int(self.new_interval.value))
        msg = active_messages.get(self.msg_id)
        if msg.get("status") == "active":
            await restart_message_task(self.msg_id, start_immediately=False)
        await interaction.response.send_message("✅ Интервалът беше обновен.", ephemeral=True)

class RepeatEditModal(discord.ui.Modal):
    def __init__(self, msg_id: str):
        super().__init__(title="Edit Repeat Count")
        self.msg_id = msg_id
        self.new_repeat = discord.ui.TextInput(label="Repeat count (0=∞)", default=str(get_stored_repeat(msg_id) or 0))
        self.add_item(self.new_repeat)

    async def on_submit(self, interaction: discord.Interaction):
        update_repeat_value(self.msg_id, int(self.new_repeat.value))
        msg = active_messages.get(self.msg_id)
        if msg.get("status") == "active":
            await restart_message_task(self.msg_id, start_immediately=False)
        await interaction.response.send_message("✅ Повторенията бяха обновени.", ephemeral=True)

class ChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, msg_id: str):
        super().__init__(custom_id=f"channel_select_{msg_id}", placeholder="Избери текстов канал", channel_types=[discord.ChannelType.text])
        self.msg_id = msg_id

    async def callback(self, interaction: discord.Interaction):
        update_channel_value(self.msg_id, self.values[0].id)
        msg = active_messages.get(self.msg_id)
        if msg.get("status") == "active":
            await restart_message_task(self.msg_id, start_immediately=False)
        await interaction.response.send_message(f"✅ Каналът беше обновен.", ephemeral=True)

class ChannelSelectView(discord.ui.View):
    def __init__(self, msg_id: str):
        super().__init__(timeout=120)
        self.add_item(ChannelSelect(msg_id))

# === Команди ===
@bot.event
async def on_ready():
    print(f"✅ Влязъл съм като {bot.user}")
    if guild:
        await tree.sync(guild=guild)
    else:
        await tree.sync()
    await load_messages()

@tree.command(name="create", description="Създай автоматично съобщение.")
@app_commands.describe(message="Текст", interval="Интервал", repeat="Повторения", id="Идентификатор", channel="Канал")
async def create(interaction: discord.Interaction, message: str, interval: int, repeat: int, id: str, channel: Optional[discord.TextChannel] = None):
    if not has_permission(interaction.user):
        await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
        return
    if id in active_messages:
        await interaction.response.send_message(f"⚠️ '{id}' вече съществува.", ephemeral=True)
        return
    channel_id_for_task = channel.id if channel else (CHANNEL_ID if CHANNEL_ID else None)
    if channel_id_for_task is None:
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
        color = discord.Color.green() if msg["status"] == "active" else discord.Color.red()
        embed = discord.Embed(title=f"🆔 {msg['id']} ({msg['status']})", description=msg['message'], color=color)
        embed.add_field(name="Channel", value="🔒 (само при edit)", inline=False)
        await interaction.followup.send(embed=embed, view=MessageButtons(msg["id"]), ephemeral=True)

# === Стартиране на бота ===
if not TOKEN:
    print("❌ Не е зададен DISCORD_TOKEN.")
else:
    bot.run(TOKEN)
