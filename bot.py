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

# === Helpers за embed ===
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

# === Views и модали ===
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
        await interaction.response.send_message(f"▶️ '{self.msg_id}' стартирано.", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.blurple)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
            return
        msg = active_messages.get(self.msg_id)
        msg["status"] = "stopped"
        await interaction.response.send_message(f"⏹️ '{self.msg_id}' е спряно.", ephemeral=True)

    @discord.ui.button(emoji="❌", style=discord.ButtonStyle.gray)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
            return
        active_messages.pop(self.msg_id, None)
        await interaction.response.send_message(f"❌ '{self.msg_id}' изтрито.", ephemeral=True)

# Модали за edit
class ContentEditModal(discord.ui.Modal):
    def __init__(self, msg_id: str):
        super().__init__(title="Edit Message Content")
        self.msg_id = msg_id
        self.new_content = discord.ui.TextInput(label="New Message Content", default=get_stored_message_content(msg_id)[:1900])
        self.add_item(self.new_content)

    async def on_submit(self, interaction: discord.Interaction):
        update_message_content_value(self.msg_id, self.new_content.value)
        await interaction.response.send_message("✅ Съобщението беше обновено.", ephemeral=True)

class IntervalEditModal(discord.ui.Modal):
    def __init__(self, msg_id: str):
        super().__init__(title="Edit Interval")
        self.msg_id = msg_id
        self.new_interval = discord.ui.TextInput(label="Interval (minutes)", default=str(get_stored_interval(msg_id) or 0))
        self.add_item(self.new_interval)

    async def on_submit(self, interaction: discord.Interaction):
        update_interval_value(self.msg_id, int(self.new_interval.value))
        await interaction.response.send_message("✅ Интервалът беше обновен.", ephemeral=True)

class RepeatEditModal(discord.ui.Modal):
    def __init__(self, msg_id: str):
        super().__init__(title="Edit Repeat Count")
        self.msg_id = msg_id
        self.new_repeat = discord.ui.TextInput(label="Repeat count (0=∞)", default=str(get_stored_repeat(msg_id) or 0))
        self.add_item(self.new_repeat)

    async def on_submit(self, interaction: discord.Interaction):
        update_repeat_value(self.msg_id, int(self.new_repeat.value))
        await interaction.response.send_message("✅ Повторенията бяха обновени.", ephemeral=True)

class ChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, msg_id: str):
        super().__init__(custom_id=f"channel_select_{msg_id}", placeholder="Избери текстов канал", channel_types=[discord.ChannelType.text])
        self.msg_id = msg_id

    async def callback(self, interaction: discord.Interaction):
        update_channel_value(self.msg_id, self.values[0].id)
        await interaction.response.send_message(f"✅ Каналът беше обновен.", ephemeral=True)

class ChannelSelectView(discord.ui.View):
    def __init__(self, msg_id: str):
        super().__init__(timeout=120)
        self.add_item(ChannelSelect(msg_id))

# === Команди ===
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
        await interaction.followup.send(embed=embed, view=MessageButtons(msg['id']), ephemeral=True)

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
