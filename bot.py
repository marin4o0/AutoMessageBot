# bot.py — FIXED full version
import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
from typing import Optional

# CONFIG
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
GUILD_ID = int(os.getenv("GUILD_ID"))
SAVE_FILE = "active_messages.json"

ALLOWED_ROLES = ["Admin", "Moderator"]

# INTENTS
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
guild = discord.Object(id=GUILD_ID)

# In-memory: msg_id -> dict
active_messages: dict = {}

# Helpers
def has_permission(user: discord.Member) -> bool:
    if user.guild_permissions.administrator:
        return True
    return any(role.name in ALLOWED_ROLES for role in user.roles)

def save_messages():
    data = {}
    for msg_id, msg in active_messages.items():
        # Do not store task objects
        data[msg_id] = {
            "message": msg.get("message"),
            "interval": msg.get("interval"),
            "repeat": msg.get("repeat"),
            "id": msg.get("id"),
            "creator": msg.get("creator"),
            "status": msg.get("status", "active"),
            "posted_message_id": msg.get("posted_message_id")
        }
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_saved_messages_to_memory():
    if not os.path.exists(SAVE_FILE):
        return
    with open(SAVE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    for msg_id, msg in data.items():
        # restore fields, mark task None (we'll restart)
        active_messages[msg_id] = {
            "task": None,
            "message": msg.get("message"),
            "interval": msg.get("interval"),
            "repeat": msg.get("repeat"),
            "id": msg.get("id"),
            "creator": msg.get("creator"),
            "status": msg.get("status", "active"),
            "posted_message_id": msg.get("posted_message_id")
        }

def get_message_data(msg_id: str) -> Optional[dict]:
    return active_messages.get(msg_id)

# Embed builder (for ephemeral displays)
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

# Core task: sends messages repeatedly.
# skip_first_send: when True, the task will NOT send immediately the first iteration,
# because /create already sent the first visible message.
async def restart_message_task(msg_id: str, skip_first_send: bool = False):
    msg_data = active_messages.get(msg_id)
    if not msg_data:
        return

    # cancel existing
    existing = msg_data.get("task")
    if existing:
        existing.cancel()

    # only if active
    if msg_data.get("status") != "active":
        msg_data["task"] = None
        save_messages()
        return

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print(f"⚠️ Channel {CHANNEL_ID} not found.")
        msg_data["status"] = "stopped"
        msg_data["task"] = None
        save_messages()
        return

    first_send = skip_first_send  # local flag we can mutate

    async def task_func():
        nonlocal first_send
        count = 0
        try:
            while True:
                # stop condition for repeat
                if msg_data.get("repeat", 0) != 0 and count >= msg_data.get("repeat", 0):
                    break

                if first_send:
                    # first public send already done by /create
                    first_send = False
                else:
                    try:
                        await channel.send(msg_data["message"])
                    except Exception as e:
                        print(f"❌ Failed to send message for {msg_id}: {e}")

                count += 1
                interval = msg_data.get("interval", 0)
                if interval <= 0:
                    break
                await asyncio.sleep(interval * 60)
        except asyncio.CancelledError:
            pass
        finally:
            # task finished naturally or cancelled
            msg_data["task"] = None
            # if completed naturally, mark stopped
            if msg_data.get("repeat", 0) != 0 and count >= msg_data.get("repeat", 0):
                msg_data["status"] = "stopped"
            save_messages()

    # create and store task
    msg_data["task"] = asyncio.create_task(task_func())
    save_messages()

# VIEW / BUTTONS
class MessageButtons(discord.ui.View):
    def __init__(self, msg_id: str):
        super().__init__(timeout=None)
        self.msg_id = msg_id

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.green)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
        msg = get_message_data(self.msg_id)
        if not msg:
            return await interaction.response.send_message("❌ Не е намерено.", ephemeral=True)

        msg["status"] = "active"
        # If the message was previously posted, we don't want to resend it immediately:
        # start task but do NOT skip_first_send (since /create already sent first only)
        await restart_message_task(self.msg_id, skip_first_send=False)
        save_messages()
        # show updated ephemeral embed
        embed = build_configuration_embed(msg)
        await interaction.response.send_message("✅ Стартирано.", embed=embed, view=MessageButtons(self.msg_id), ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.blurple)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
        msg = get_message_data(self.msg_id)
        if not msg:
            return await interaction.response.send_message("❌ Не е намерено.", ephemeral=True)

        task = msg.get("task")
        if task:
            task.cancel()
        msg["status"] = "stopped"
        msg["task"] = None
        save_messages()
        embed = build_configuration_embed(msg)
        await interaction.response.send_message("⏹️ Спиране успешно.", embed=embed, view=MessageButtons(self.msg_id), ephemeral=True)

    @discord.ui.button(emoji="❌", style=discord.ButtonStyle.red)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
        msg = active_messages.pop(self.msg_id, None)
        if msg and (task := msg.get("task")):
            task.cancel()
        # try deleting the original posted public message (if exists)
        posted_id = msg.get("posted_message_id") if msg else None
        if posted_id:
            ch = bot.get_channel(CHANNEL_ID)
            if ch:
                try:
                    m = await ch.fetch_message(posted_id)
                    await m.delete()
                except Exception:
                    pass
        save_messages()
        await interaction.response.send_message("🗑️ Изтрито успешно.", ephemeral=True)

    @discord.ui.button(emoji="✏️", style=discord.ButtonStyle.secondary)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            return await interaction.response.send_message("🚫 Нямаш права за редакция.", ephemeral=True)
        msg = get_message_data(self.msg_id)
        if not msg:
            return await interaction.response.send_message("❌ Не е намерено.", ephemeral=True)
        # show selection menu (ephemeral)
        await interaction.response.send_message("Избери какво да редактираш:", view=EditSelectView(self.msg_id), ephemeral=True)

# EDIT UI: select + modals
class EditSelect(discord.ui.Select):
    def __init__(self, msg_id: str):
        options = [
            discord.SelectOption(label="Message Content", value="edit_content", emoji="📝"),
            discord.SelectOption(label="Time Interval", value="edit_interval", emoji="⏱️"),
            discord.SelectOption(label="Repeat Count", value="edit_repeat", emoji="🔁")
        ]
        super().__init__(placeholder="Избери какво да редактираш", min_values=1, max_values=1, options=options)
        self.msg_id = msg_id

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]
        if choice == "edit_content":
            await interaction.response.send_modal(ContentEditModal(self.msg_id))
        elif choice == "edit_interval":
            await interaction.response.send_modal(IntervalEditModal(self.msg_id))
        elif choice == "edit_repeat":
            await interaction.response.send_modal(RepeatEditModal(self.msg_id))

class EditSelectView(discord.ui.View):
    def __init__(self, msg_id: str):
        super().__init__(timeout=120)
        self.add_item(EditSelect(msg_id))

class ContentEditModal(discord.ui.Modal):
    def __init__(self, msg_id: str):
        super().__init__(title="Edit Message Content")
        self.msg_id = msg_id
        current = get_message_data(msg_id).get("message", "")
        self.new_content = discord.ui.TextInput(label="New Message", style=discord.TextStyle.long, default=current, custom_id="new_content")
        self.add_item(self.new_content)

    async def on_submit(self, interaction: discord.Interaction):
        new_text = self.new_content.value.strip()
        if not new_text:
            return await interaction.response.send_message("⚠️ Съдържанието не може да бъде празно.", ephemeral=True)

        # update stored message
        msg = get_message_data(self.msg_id)
        if not msg:
            return await interaction.response.send_message("❌ Задачата не е намерена.", ephemeral=True)

        msg["message"] = new_text
        save_messages()

        # edit the original posted public message (if exists)
        posted_id = msg.get("posted_message_id")
        if posted_id:
            ch = bot.get_channel(CHANNEL_ID)
            if ch:
                try:
                    m = await ch.fetch_message(posted_id)
                    await m.edit(content=new_text)
                except Exception:
                    # ignore if cannot fetch/edit
                    pass

        # If active, restart task so new content is used next time
        if msg.get("status") == "active":
            await restart_message_task(self.msg_id, skip_first_send=False)

        embed = build_configuration_embed(msg)
        await interaction.response.send_message("✅ Съдържанието е обновено.", embed=embed, view=MessageButtons(self.msg_id), ephemeral=True)

class IntervalEditModal(discord.ui.Modal):
    def __init__(self, msg_id: str):
        super().__init__(title="Edit Interval (minutes)")
        self.msg_id = msg_id
        current = get_message_data(msg_id).get("interval", "")
        self.new_interval = discord.ui.TextInput(label="Interval (minutes)", style=discord.TextStyle.short, default=str(current), custom_id="new_interval")
        self.add_item(self.new_interval)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.new_interval.value)
            if val <= 0:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("⚠️ Въведи валидно положително число.", ephemeral=True)

        msg = get_message_data(self.msg_id)
        if not msg:
            return await interaction.response.send_message("❌ Задачата не е намерена.", ephemeral=True)

        msg["interval"] = val
        save_messages()

        # If active, restart task so new interval takes effect (we don't skip first send)
        if msg.get("status") == "active":
            await restart_message_task(self.msg_id, skip_first_send=False)

        embed = build_configuration_embed(msg)
        await interaction.response.send_message("✅ Интервалът е обновен.", embed=embed, view=MessageButtons(self.msg_id), ephemeral=True)

class RepeatEditModal(discord.ui.Modal):
    def __init__(self, msg_id: str):
        super().__init__(title="Edit Repeat Count")
        self.msg_id = msg_id
        current = get_message_data(msg_id).get("repeat", "")
        self.new_repeat = discord.ui.TextInput(label="Repeat Count (0 = ∞)", style=discord.TextStyle.short, default=str(current), custom_id="new_repeat")
        self.add_item(self.new_repeat)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.new_repeat.value)
            if val < 0:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("⚠️ Въведи валидно число.", ephemeral=True)

        msg = get_message_data(self.msg_id)
        if not msg:
            return await interaction.response.send_message("❌ Задачата не е намерена.", ephemeral=True)

        msg["repeat"] = val
        save_messages()

        # restart if active
        if msg.get("status") == "active":
            await restart_message_task(self.msg_id, skip_first_send=False)

        embed = build_configuration_embed(msg)
        await interaction.response.send_message("✅ Повторенията са обновени.", embed=embed, view=MessageButtons(self.msg_id), ephemeral=True)

# Commands and lifecycle
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    # load stored messages, then restart tasks for those that are active
    load_saved_messages_to_memory()
    for mid, m in list(active_messages.items()):
        # ensure task slot
        active_messages[mid]["task"] = None
        if m.get("status") == "active":
            # if there is a posted_message_id we assume its first send happened already — do not resend immediately
            await restart_message_task(mid, skip_first_send=True)
    try:
        await tree.sync(guild=guild)
        print(f"🔁 Commands synced for guild {GUILD_ID}")
    except Exception as e:
        print(f"❌ Sync error: {e}")

@tree.command(name="create", description="Create automated message.")
@app_commands.describe(message="Text", interval="Interval in minutes", repeat="Repeat count (0 = ∞)", id="Unique ID")
async def create(interaction: discord.Interaction, message: str, interval: int, repeat: int, id: str):
    if not has_permission(interaction.user):
        return await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
    if id in active_messages:
        return await interaction.response.send_message("⚠️ ID already exists.", ephemeral=True)
    if interval <= 0:
        return await interaction.response.send_message("⚠️ Interval must be > 0.", ephemeral=True)

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return await interaction.response.send_message("⚠️ Channel not found.", ephemeral=True)

    # send first visible message once and store its ID
    try:
        sent = await channel.send(message)
        posted_id = sent.id
    except Exception as e:
        print(f"❌ Failed to send initial message: {e}")
        return await interaction.response.send_message("❌ Failed to post message.", ephemeral=True)

    msg_data = {
        "task": None,
        "message": message,
        "interval": interval,
        "repeat": repeat,
        "id": id,
        "creator": interaction.user.name,
        "status": "active",
        "posted_message_id": posted_id
    }
    active_messages[id] = msg_data
    save_messages()

    # start background task — skip_first_send True because we already posted once
    await restart_message_task(id, skip_first_send=True)

    # send ephemeral control embed to the user (only they see it)
    embed = build_configuration_embed(msg_data)
    view = MessageButtons(id)
    await interaction.response.send_message("✅ Created.", embed=embed, view=view, ephemeral=True)

@tree.command(name="list", description="Show all active messages (ephemeral).")
async def list_messages(interaction: discord.Interaction):
    if not has_permission(interaction.user):
        return await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
    if not active_messages:
        return await interaction.response.send_message("ℹ️ No active messages.", ephemeral=True)

    # primary response so followups are allowed
    await interaction.response.send_message("📋 Active messages:", ephemeral=True)
    for msg in active_messages.values():
        embed = build_configuration_embed(msg)
        await interaction.followup.send(embed=embed, view=MessageButtons(msg["id"]), ephemeral=True)

# Run
bot.run(TOKEN)
