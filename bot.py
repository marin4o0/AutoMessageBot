import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
from typing import Optional
from datetime import datetime

import logging, sys
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
print("🚀 Стартирам Discord клиента...", flush=True)

# === КОНФИГУРАЦИЯ ===
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID")) if os.getenv("DISCORD_CHANNEL_ID") else None
GUILD_ID = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID") else None
SAVE_FILE = "active_messages.json"
ALLOWED_ROLES = ["Admin", "Moderator"]
print("🔍 Проверка на Environment Variables:")
print("DISCORD_TOKEN:", "✅ намерен" if TOKEN else "❌ липсва")
print("GUILD_ID:", GUILD_ID)
print("DISCORD_CHANNEL_ID:", CHANNEL_ID)

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
        try:
            msg_data["task"].cancel()
        except Exception:
            pass

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

def build_info_embed(msg_data: dict) -> discord.Embed:
    status = msg_data.get("status", "unknown")
    color = discord.Color.green() if status == "active" else discord.Color.red()
    repeat_display = "∞" if msg_data.get("repeat") == 0 else str(msg_data.get("repeat"))
    channel_id = msg_data.get("channel_id")
    channel_mention = f"<#{channel_id}>" if channel_id else "—"

    embed = discord.Embed(title=f"🆔 {msg_data.get('id')} ({status})", color=color)
    embed.add_field(name="Message", value=msg_data.get("message", "-"), inline=False)
    embed.add_field(name="Interval", value=f"{msg_data.get('interval', '-') } мин", inline=True)
    embed.add_field(name="Repeat", value=repeat_display, inline=True)
    embed.add_field(name="Creator", value=msg_data.get("creator", "-"), inline=False)
    embed.add_field(name="Channel", value=channel_mention, inline=False)
    embed.timestamp = datetime.utcnow()
    return embed

# === Edit Modal с Channel ID предварително попълнено ===
class EditModal(discord.ui.Modal):
    def __init__(self, msg_id: str, guild: discord.Guild):
        super().__init__(title="Edit Message")
        self.msg_id = msg_id
        self.guild = guild

        self.content_input = discord.ui.TextInput(label="Message", default=get_stored_message_content(msg_id)[:1900])
        self.interval_input = discord.ui.TextInput(label="Interval (minutes)", default=str(get_stored_interval(msg_id) or 0))
        self.repeat_input = discord.ui.TextInput(label="Repeat count (0=∞)", default=str(get_stored_repeat(msg_id) or 0))
        
        # ✅ Предварително попълване с текущ канал (ID)
        current_channel_id = get_stored_channel_id(msg_id) or CHANNEL_ID or ""
        self.channel_input = discord.ui.TextInput(label="Channel (ID)", default=str(current_channel_id))

        self.add_item(self.content_input)
        self.add_item(self.interval_input)
        self.add_item(self.repeat_input)
        self.add_item(self.channel_input)

    async def on_submit(self, interaction: discord.Interaction):
        update_message_content_value(self.msg_id, self.content_input.value)
        update_interval_value(self.msg_id, int(self.interval_input.value))
        update_repeat_value(self.msg_id, int(self.repeat_input.value))

        channel_value = self.channel_input.value.strip()
        new_channel_id = None
        if channel_value.isdigit():
            new_channel_id = int(channel_value)
            channel_obj = self.guild.get_channel(new_channel_id)
            if not channel_obj or not isinstance(channel_obj, discord.TextChannel):
                await interaction.response.send_message(f"❌ Канал с ID {new_channel_id} не съществува.", ephemeral=True)
                return
        elif channel_value:
            channel_obj = discord.utils.get(self.guild.text_channels, name=channel_value)
            if not channel_obj:
                await interaction.response.send_message(f"❌ Канал с име '{channel_value}' не е намерен.", ephemeral=True)
                return
            new_channel_id = channel_obj.id

        if new_channel_id:
            update_channel_value(self.msg_id, new_channel_id)

        msg = get_message_data(self.msg_id)
        if msg and msg.get("status") == "active":
            await restart_message_task(self.msg_id, start_immediately=False)

        await interaction.response.send_message("✅ Съобщението беше обновено.", ephemeral=True)
# === FullMessageButtons с callback функции ===
class FullMessageButtons(discord.ui.View):
    def __init__(self, msg_id: str, guild: discord.Guild):
        super().__init__(timeout=None)
        self.msg_id = msg_id
        self.guild = guild

    @discord.ui.button(label="▶️ Start", style=discord.ButtonStyle.green)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
            return
        msg = active_messages.get(self.msg_id)
        if not msg:
            await interaction.response.send_message("❌ Съобщението не е намерено.", ephemeral=True)
            return
        if msg["status"] == "active":
            await interaction.response.send_message("⚠️ Вече е активно.", ephemeral=True)
            return
        msg["status"] = "active"
        await restart_message_task(self.msg_id)
        await interaction.response.send_message(f"✅ '{self.msg_id}' стартирано.", ephemeral=True)

    @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.blurple)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
            return
        msg = active_messages.get(self.msg_id)
        if not msg:
            await interaction.response.send_message("❌ Съобщението не съществува.", ephemeral=True)
            return
        msg["status"] = "stopped"
        task = msg.get("task")
        if task:
            try:
                task.cancel()
            except Exception:
                pass
        save_messages()
        await interaction.response.send_message(f"⏸️ '{self.msg_id}' е спряно.", ephemeral=True)

    @discord.ui.button(label="🗑️ Delete", style=discord.ButtonStyle.red)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
            return
        msg = active_messages.pop(self.msg_id, None)
        if msg and msg.get("task"):
            try:
                msg["task"].cancel()
            except Exception:
                pass
        save_messages()
        await interaction.response.send_message(f"🗑️ '{self.msg_id}' изтрито.", ephemeral=True)

    @discord.ui.button(label="✏️ Edit", style=discord.ButtonStyle.gray)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
            return
        await interaction.response.send_modal(EditModal(self.msg_id, self.guild))
# === Commands ===
@tree.command(name="create", description="Създай ново автоматично съобщение.")
@app_commands.describe(
    message="Текст на съобщението",
    interval="Интервал в минути",
    repeat="Брой повторения (0 = безкрайно)",
    id="Уникален идентификатор",
    channel="Канал за съобщението"
)
async def create(interaction: discord.Interaction, message: str, interval: int, repeat: int, id: str, channel: Optional[discord.TextChannel] = None):
    if not has_permission(interaction.user):
        await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
        return
    if id in active_messages:
        await interaction.response.send_message(f"⚠️ Съобщение с ID '{id}' вече съществува.", ephemeral=True)
        return

    channel_id_for_task = channel.id if channel else (CHANNEL_ID if CHANNEL_ID else None)
    if not channel_id_for_task:
        await interaction.response.send_message("❌ Не е зададен канал. Можете да подадете канал като параметър или да зададете CHANNEL_ID в env.", ephemeral=True)
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


@tree.command(name="list", description="Покажи всички автоматични съобщения.")
async def list_messages(interaction: discord.Interaction):
    if not has_permission(interaction.user):
        await interaction.response.send_message("🚫 Нямаш права.", ephemeral=True)
        return
    if not active_messages:
        await interaction.response.send_message("ℹ️ Няма съобщения.", ephemeral=True)
        return

    # Пращаме първо едно кратко епhemeral съобщение, след това followup-ите с embed-ите
    await interaction.response.send_message("📋 Всички автоматични съобщения:", ephemeral=True)
    for msg in active_messages.values():
        embed = build_info_embed(msg)
        # followup.send - използваме try/except в случай че followup не може да бъде изпълнен
        try:
            await interaction.followup.send(embed=embed, view=FullMessageButtons(msg['id'], interaction.guild), ephemeral=True)
        except Exception as e:
            print(f"❌ Не успя да се изпрати followup за {msg.get('id')}: {e}")


# === HELP команда (пълна документация и как да копирате Channel ID) ===
@tree.command(name="help", description="Показва помощ и информация за командите.")
@app_commands.describe(command="(по избор) име на команда за подробна справка")
async def help_command(interaction: discord.Interaction, command: Optional[str] = None):
    # Няма нужда от права — позволяваме на всички да видят помощта
    # Ако е подадено конкретно име, показваме детайли, иначе общ преглед
    commands_info = {
        "create": {
            "description": "Създава ново автоматично съобщение.",
            "usage": "/create message:<текст> interval:<минути> repeat:<брой (0=∞)> id:<уникално> [channel:<канал>]",
            "example": "/create message:Здравей! interval:60 repeat:0 id:morning channel:#announcements"
        },
        "list": {
            "description": "Показва всички автоматични съобщения и бутони за управление.",
            "usage": "/list",
            "example": "/list"
        },
        "help": {
            "description": "Показва справка за командите.",
            "usage": "/help [command]",
            "example": "/help create"
        }
    }

    if command:
        cmd = command.lower()
        info = commands_info.get(cmd)
        if not info:
            await interaction.response.send_message(f"⚠️ Не разбирам команда '{command}'. Вижте /help за налични команди.", ephemeral=True)
            return
        embed = discord.Embed(title=f"/{cmd} — помощ", color=discord.Color.blue())
        embed.add_field(name="Описание", value=info["description"], inline=False)
        embed.add_field(name="Употреба", value=info["usage"], inline=False)
        embed.add_field(name="Пример", value=info["example"], inline=False)
        # Добавяме кратък блок с как да копирате Channel ID
        embed.add_field(
            name="Как да копирате Channel ID (Discord)",
            value=(
                "1) Отидете в Settings > Advanced и включете **Developer Mode**.\n"
                "2) Отидете на желания канал, натиснете десен бутон върху името му.\n"
                "3) Изберете **Copy ID** — това е числото, което можете да подадете като `channel`.\n\n"
                "Можете да подадете канал като mention (напр. #announcements) или директно като ID (напр. 123456789012345678)."
            ),
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Общ преглед
    embed = discord.Embed(title="Помощ — Команди", color=discord.Color.blue())
    for name, info in commands_info.items():
        embed.add_field(name=f"/{name}", value=f"{info['description']}\n`Usage:` {info['usage']}", inline=False)
    embed.set_footer(text="За детайли напишете /help <command>. За копиране на Channel ID — вижте детайлите при конкретна команда.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# === Обработчик за грешки на app commands (предотвратява големи tracebacks като CommandNotFound) ===
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # CommandNotFound се появява когато interaction съдържа команда, която вече не е регистрирана (cache / старо)
    if isinstance(error, app_commands.CommandNotFound):
        # кратко уведомление — не печатаме голям traceback
        try:
            await interaction.response.send_message("⚠️ Командата не е намерена (възможно е да е била премахната/променена). Опитайте да отворите менюто на slash командите отново.", ephemeral=True)
        except Exception:
            pass
        return

    # За останалите app command грешки — логваме и връщаме общо съобщение
    print(f"Unhandled app command error: {error}")
    try:
        await interaction.response.send_message("❌ Възникна грешка при изпълнение на командата.", ephemeral=True)
    except Exception:
        pass


# === Стартиране на бота ===
@bot.event
async def on_ready():
    print(f"✅ Влязъл съм като {bot.user} (ботът е онлайн)", flush=True)

    async def post_start_tasks():
        await asyncio.sleep(5)  # изчакваме Discord да е напълно готов

        # === Изчистване на стари команди ===
        try:
            if guild:
                existing = await tree.fetch_commands(guild=guild)
            else:
                existing = await tree.fetch_commands()

            for cmd in existing:
                if cmd.name not in ["create", "list", "help"]:
                    print(f"🧹 Премахвам стара команда: /{cmd.name}", flush=True)
                    try:
                        if guild:
                            await tree.remove_command(cmd.name, guild=guild)
                        else:
                            await tree.remove_command(cmd.name)
                    except Exception as inner:
                        print(f"⚠️ Неуспешно премахване на {cmd.name}: {inner}", flush=True)

            if guild:
                await tree.sync(guild=guild)
                print(f"🔁 Slash командите са синхронизирани с guild {guild.id}", flush=True)
            else:
                await tree.sync()
                print("🌍 Slash командите са синхронизирани глобално.", flush=True)
        except Exception as e:
            print(f"⚠️ Грешка при изчистване/синхронизиране на команди: {e}", flush=True)

        # === Зареждане на съобщения ===
        try:
            await load_messages()
            print("💬 Заредени са активните съобщения и задачите са рестартирани.", flush=True)
        except Exception as e:
            print(f"❌ Грешка при load_messages: {e}", flush=True)

    # Стартираме пост-инициализационните задачи без да блокираме on_ready()
    bot.loop.create_task(post_start_tasks())

