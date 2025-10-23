import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
from typing import Optional
from datetime import datetime  # fix за NameError

# === КОНФИГУРАЦИЯ ===
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
GUILD_ID = int(os.getenv("GUILD_ID"))
SAVE_FILE = "active_messages.json"

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

def has_edit_permission(member: discord.Member) -> bool:
    return has_permission(member)

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

def record_embed_message_id(msg_id: str, message_id: Optional[int]):
    msg_data = active_messages.get(msg_id)
    if not msg_data:
        return
    if msg_data.get("embed_message_id") == message_id:
        return
    msg_data["embed_message_id"] = message_id
    save_messages()

def get_message_data(msg_id: str) -> Optional[dict]:
    return active_messages.get(msg_id)

def get_stored_message_content(msg_id: str) -> str:
    data = get_message_data(msg_id)
    return data.get("message", "") if data else ""

def get_stored_interval(msg_id: str) -> Optional[int]:
    data = get_message_data(msg_id)
    if not data:
        return None
    return data.get("interval")

def get_stored_repeat(msg_id: str) -> Optional[int]:
    data = get_message_data(msg_id)
    if not data:
        return None
    return data.get("repeat")

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
        print(f"⚠️ Каналът с ID {CHANNEL_ID} не е намерен.")
        msg_data["status"] = "stopped"
        msg_data["task"] = None
        save_messages()
        return

    async def task_func():
        count = 0
        completed_naturally = False
        try:
            while True:
                if msg_data["repeat"] != 0 and count >= msg_data["repeat"]:
                    completed_naturally = True
                    break
                await channel.send(msg_data["message"])
                count += 1

                interval_minutes = msg_data.get("interval", 0)
                if interval_minutes <= 0:
                    completed_naturally = True
                    break
                try:
                    await asyncio.sleep(interval_minutes * 60)
                except asyncio.CancelledError:
                    raise
        except asyncio.CancelledError:
            pass
        else:
            completed_naturally = True
        finally:
            current_data = active_messages.get(msg_id)
            if not current_data:
                return
            current_data["task"] = None
            if completed_naturally:
                current_data["status"] = "stopped"
                await update_embed_status(msg_id)
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
        await restart_message_task(msg_id)
        await update_embed_status(msg_id)

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
    embed.timestamp = datetime.utcnow()
    return embed

async def update_embed_status(msg_id: str, interaction: Optional[discord.Interaction] = None):
    msg_data = active_messages.get(msg_id)
    if not msg_data:
        return

    embed = build_configuration_embed(msg_data)
    view = MessageButtons(msg_id)
    embed_message_id = msg_data.get("embed_message_id")

    try:
        if interaction:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            channel = bot.get_channel(CHANNEL_ID)
            if not channel:
                print(f"⚠️ Каналът с ID {CHANNEL_ID} не е намерен за обновяване на {msg_id}.")
                return
            if embed_message_id:
                try:
                    embed_msg = await channel.fetch_message(embed_message_id)
                except discord.NotFound:
                    return
                else:
                    await embed_msg.edit(embed=embed, view=view)
    except discord.Forbidden:
        print(f"❌ Нямам права да обновя embed за {msg_id}.")
    except discord.HTTPException as error:
        print(f"❌ Неуспешно обновяване на embed за {msg_id}: {error}")

# === View с бутони ===
class MessageButtons(discord.ui.View):
    def __init__(self, msg_id: str):
        super().__init__(timeout=None)
        self.msg_id = msg_id

        # Създаваме бутоните
        self.start_button = discord.ui.Button(emoji="▶️", style=discord.ButtonStyle.green, custom_id=f"start_message_{msg_id}")
        self.stop_button = discord.ui.Button(emoji="⏹️", style=discord.ButtonStyle.blurple, custom_id=f"stop_message_{msg_id}")
        self.delete_button = discord.ui.Button(emoji="❌", style=discord.ButtonStyle.red, custom_id=f"delete_message_{msg_id}")
        self.edit_button = discord.ui.Button(emoji="✏️", style=discord.ButtonStyle.secondary, custom_id=f"edit_message_{msg_id}")

        # Добавяме бутоните към view
        self.add_item(self.start_button)
        self.add_item(self.stop_button)
        self.add_item(self.delete_button)
        self.add_item(self.edit_button)

        # Свързваме callback функции
        self.start_button.callback = self.start_callback
        self.stop_button.callback = self.stop_callback
        self.delete_button.callback = self.delete_callback
        self.edit_button.callback = self.edit_callback

    # === Callbacks ===
    async def start_callback(self, interaction: discord.Interaction):
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
        await restart_message_task(self.msg_id)
        await update_embed_status(self.msg_id, interaction=interaction)
        save_messages()
        await interaction.followup.send(f"▶️ '{self.msg_id}' стартира отново.", ephemeral=True)

    async def stop_callback(self, interaction: discord.Interaction):
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
        await update_embed_status(self.msg_id, interaction=interaction)
        save_messages()
        await interaction.followup.send(f"⏹️ '{self.msg_id}' е спряно.", ephemeral=True)

    async def delete_callback(self, interaction: discord.Interaction):
        if not has_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права за тази операция.", ephemeral=True)
            return
        msg = active_messages.pop(self.msg_id, None)
        if msg:
            task = msg.get("task")
            if task:
                task.cancel()
            channel = bot.get_channel(CHANNEL_ID)
            embed_message_id = msg.get("embed_message_id")
            if channel and embed_message_id:
                try:
                    embed_msg = await channel.fetch_message(embed_message_id)
                    await embed_msg.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass
                except discord.HTTPException as error:
                    print(f"❌ Неуспешно изтриване на embed за {self.msg_id}: {error}")
            save_messages()
            await interaction.response.send_message(f"❌ '{self.msg_id}' е изтрито.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Не е намерено.", ephemeral=True)

    async def edit_callback(self, interaction: discord.Interaction):
        if not has_edit_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права да редактираш съобщения.", ephemeral=True)
            return
        msg = active_messages.get(self.msg_id)
        if not msg:
            await interaction.response.send_message("❌ Не е намерено.", ephemeral=True)
            return
        view = EditSelectView(self.msg_id)
        await interaction.response.send_message("Какво искаш да редактираш?", view=view, ephemeral=True)

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
    await update_embed_status(msg_id=id, interaction=interaction)

# === Стартиране на бота ===
bot.run(TOKEN)
