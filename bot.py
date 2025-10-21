import os
import discord
from discord.ext import commands
from discord import app_commands
from discord import Color, Embed
import asyncio
import json
from typing import Optional

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

def has_edit_permission(member: discord.Member) -> bool:
    """Return True if the member can access edit operations."""
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

def build_configuration_embed(msg_data: dict) -> Embed:
    status = msg_data.get("status", "unknown")
    color = Color.green() if status == "active" else Color.red()
    repeat_display = "∞" if msg_data.get("repeat") == 0 else str(msg_data.get("repeat", "-"))
    embed = Embed(
        title=f"🆔 {msg_data.get('id', 'unknown')} ({status})",
        color=color
    )
    embed.add_field(name="Message", value=msg_data.get("message", "-"), inline=False)
    embed.add_field(name="Interval", value=f"{msg_data.get('interval', '-') } мин", inline=True)
    embed.add_field(name="Repeat", value=repeat_display, inline=True)
    embed.add_field(name="Creator", value=msg_data.get("creator", "-") or "-", inline=False)
    embed.set_timestamp()
    return embed

async def update_embed_status(msg_id):
    msg_data = active_messages.get(msg_id)
    if not msg_data:
        return

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print(f"⚠️ Каналът с ID {CHANNEL_ID} не е намерен за обновяване на {msg_id}.")
        return

    embed = build_configuration_embed(msg_data)
    view = MessageButtons(msg_id)
    embed_message_id = msg_data.get("embed_message_id")

    try:
        if embed_message_id:
            try:
                embed_msg = await channel.fetch_message(embed_message_id)
            except discord.NotFound:
                embed_msg = await channel.send(embed=embed, view=view)
                record_embed_message_id(msg_id, embed_msg.id)
            else:
                await embed_msg.edit(embed=embed, view=view)
        else:
            embed_msg = await channel.send(embed=embed, view=view)
            record_embed_message_id(msg_id, embed_msg.id)
    except discord.Forbidden:
        print(f"❌ Нямам права да обновя embed за {msg_id} в канал {CHANNEL_ID}.")
    except discord.HTTPException as error:
        print(f"❌ Неуспешно обновяване на embed за {msg_id}: {error}")

# === View с бутони ===
class MessageButtons(discord.ui.View):
    def __init__(self, msg_id):
        super().__init__(timeout=None)
        self.msg_id = msg_id
        self.start_button.custom_id = f"start_message_{msg_id}"
        self.stop_button.custom_id = f"stop_message_{msg_id}"
        self.delete_button.custom_id = f"delete_message_{msg_id}"
        self.edit_button.custom_id = f"edit_message_{msg_id}"

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.green)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права за тази операция.", ephemeral=True)
            return
        record_embed_message_id(self.msg_id, interaction.message.id)
        msg = active_messages.get(self.msg_id)
        if not msg:
            await interaction.response.send_message("❌ Не е намерено.", ephemeral=True)
            return
        if msg["status"] == "active":
            await interaction.response.send_message("⚠️ Вече е активно.", ephemeral=True)
            return
        msg["status"] = "active"
        await restart_message_task(self.msg_id)
        await update_embed_status(self.msg_id)
        save_messages()
        await interaction.response.send_message(f"▶️ '{self.msg_id}' стартира отново.", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.blurple)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права за тази операция.", ephemeral=True)
            return
        record_embed_message_id(self.msg_id, interaction.message.id)
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
        record_embed_message_id(self.msg_id, interaction.message.id)
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

    @discord.ui.button(emoji="✏️", style=discord.ButtonStyle.secondary)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_edit_permission(interaction.user):
            print(f"🚫 {interaction.user} опита да отвори меню за редакция без права ({self.msg_id})")
            await interaction.response.send_message("🚫 Нямаш права да редактираш съобщения.", ephemeral=True)
            return

        msg = active_messages.get(self.msg_id)
        if not msg:
            await interaction.response.send_message("❌ Не е намерено.", ephemeral=True)
            return

        record_embed_message_id(self.msg_id, interaction.message.id)

        view = EditSelectView(self.msg_id)
        await interaction.response.send_message(
            "Какво искаш да редактираш?",
            view=view,
            ephemeral=True
        )


class EditSelect(discord.ui.Select):
    def __init__(self, msg_id: str):
        options = [
            discord.SelectOption(
                label="Message Content",
                description="Edit the message text",
                value="edit_content",
                emoji="📝"
            ),
            discord.SelectOption(
                label="Time Interval",
                description="Edit the interval between messages",
                value="edit_interval",
                emoji="⏱️"
            ),
            discord.SelectOption(
                label="Timer/Schedule",
                description="Edit the schedule settings",
                value="edit_timer",
                emoji="📅"
            )
        ]
        super().__init__(
            placeholder="Избери какво да редактираш",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"edit_select_{msg_id}"
        )
        self.msg_id = msg_id

    async def callback(self, interaction: discord.Interaction):
        if not has_edit_permission(interaction.user):
            print(f"🚫 {interaction.user} няма права за редакция {self.msg_id}")
            await interaction.response.send_message(
                "🚫 Нямаш права да редактираш съобщения.",
                ephemeral=True
            )
            return

        msg = active_messages.get(self.msg_id)
        if not msg:
            await interaction.response.send_message("❌ Тази задача липсва.", ephemeral=True)
            return

        selected_option = self.values[0]

        if selected_option == "edit_content":
            await interaction.response.send_modal(ContentEditModal(self.msg_id))
        elif selected_option == "edit_interval":
            await interaction.response.send_modal(IntervalEditModal(self.msg_id))
        elif selected_option == "edit_timer":
            await interaction.response.send_modal(TimerEditModal(self.msg_id))


class EditSelectView(discord.ui.View):
    def __init__(self, msg_id: str):
        super().__init__(timeout=120)
        self.msg_id = msg_id
        self.add_item(EditSelect(msg_id))


class ContentEditModal(discord.ui.Modal):
    def __init__(self, msg_id: str):
        super().__init__(title="Edit Message Content", custom_id=f"content_modal_{msg_id}")
        self.msg_id = msg_id

        current_content = get_stored_message_content(msg_id)
        self.new_content: discord.ui.TextInput = discord.ui.TextInput(
            label="New Message Content",
            placeholder="Въведи новия текст",
            default=current_content[:1900],
            style=discord.TextStyle.long,
            required=True,
            custom_id="new_content"
        )
        self.add_item(self.new_content)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if not has_edit_permission(interaction.user):
                print(f"🚫 {interaction.user} опита да редактира без права ({self.msg_id})")
                await interaction.response.send_message(
                    "🚫 Нямаш права да редактираш съобщения.",
                    ephemeral=True
                )
                return

            msg = get_message_data(self.msg_id)
            if not msg:
                await interaction.response.send_message("❌ Задачата не е намерена.", ephemeral=True)
                return

            new_content = self.new_content.value.strip()
            if not new_content:
                await interaction.response.send_message(
                    "⚠️ Съдържанието не може да бъде празно.",
                    ephemeral=True
                )
                return

            update_message_content_value(self.msg_id, new_content)
            await update_embed_status(self.msg_id)

            await interaction.response.send_message(
                "✅ Съобщението беше обновено.",
                ephemeral=True
            )
        except Exception as error:  # pylint: disable=broad-except
            print(f"❌ Грешка при редакция на съдържание ({self.msg_id}): {error}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Възникна грешка при обработката. Опитай отново.",
                    ephemeral=True
                )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:  # type: ignore[override]
        print(f"❌ Неочаквана грешка в ContentEditModal ({self.msg_id}): {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Възникна грешка при обработката. Опитай отново.",
                ephemeral=True
            )


class IntervalEditModal(discord.ui.Modal):
    def __init__(self, msg_id: str):
        super().__init__(title="Edit Time Interval", custom_id=f"interval_modal_{msg_id}")
        self.msg_id = msg_id
        current_interval = get_stored_interval(msg_id)

        default_value = str(current_interval) if current_interval is not None else ""
        self.new_interval: discord.ui.TextInput = discord.ui.TextInput(
            label="Interval (in minutes)",
            placeholder="Напр. 30",
            default=default_value,
            style=discord.TextStyle.short,
            required=True,
            custom_id="new_interval"
        )
        self.add_item(self.new_interval)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if not has_edit_permission(interaction.user):
                print(f"🚫 {interaction.user} опита да редактира интервал без права ({self.msg_id})")
                await interaction.response.send_message(
                    "🚫 Нямаш права да редактираш съобщения.",
                    ephemeral=True
                )
                return

            msg = get_message_data(self.msg_id)
            if not msg:
                await interaction.response.send_message("❌ Задачата не е намерена.", ephemeral=True)
                return

            try:
                new_interval = int(self.new_interval.value)
            except ValueError:
                await interaction.response.send_message(
                    "⚠️ Моля, въведи валидно цяло число за интервала.",
                    ephemeral=True
                )
                return

            if new_interval <= 0:
                await interaction.response.send_message(
                    "⚠️ Интервалът трябва да е по-голям от 0.",
                    ephemeral=True
                )
                return

            update_interval_value(self.msg_id, new_interval)

            if msg.get("status") == "active":
                await restart_message_task(self.msg_id)

            await update_embed_status(self.msg_id)

            await interaction.response.send_message(
                "✅ Интервалът беше обновен.",
                ephemeral=True
            )
        except Exception as error:  # pylint: disable=broad-except
            print(f"❌ Грешка при редакция на интервал ({self.msg_id}): {error}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Възникна грешка при обработката. Опитай отново.",
                    ephemeral=True
                )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:  # type: ignore[override]
        print(f"❌ Неочаквана грешка в IntervalEditModal ({self.msg_id}): {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Възникна грешка при обработката. Опитай отново.",
                ephemeral=True
            )


class TimerEditModal(discord.ui.Modal):
    def __init__(self, msg_id: str):
        super().__init__(title="Edit Timer/Schedule", custom_id=f"timer_modal_{msg_id}")
        self.msg_id = msg_id
        current_repeat = get_stored_repeat(msg_id)

        default_value = str(current_repeat) if current_repeat is not None else ""
        self.new_timer: discord.ui.TextInput = discord.ui.TextInput(
            label="Repeat Count (0 = ∞)",
            placeholder="Напр. 5",
            default=default_value,
            style=discord.TextStyle.short,
            required=True,
            custom_id="new_timer"
        )
        self.add_item(self.new_timer)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if not has_edit_permission(interaction.user):
                print(f"🚫 {interaction.user} опита да редактира таймера без права ({self.msg_id})")
                await interaction.response.send_message(
                    "🚫 Нямаш права да редактираш съобщения.",
                    ephemeral=True
                )
                return

            msg = get_message_data(self.msg_id)
            if not msg:
                await interaction.response.send_message("❌ Задачата не е намерена.", ephemeral=True)
                return

            try:
                new_repeat = int(self.new_timer.value)
            except ValueError:
                await interaction.response.send_message(
                    "⚠️ Въведи валидно цяло число за повторенията.",
                    ephemeral=True
                )
                return

            if new_repeat < 0:
                await interaction.response.send_message(
                    "⚠️ Повторенията не могат да са отрицателни.",
                    ephemeral=True
                )
                return

            update_repeat_value(self.msg_id, new_repeat)

            if msg.get("status") == "active":
                await restart_message_task(self.msg_id)

            await update_embed_status(self.msg_id)

            await interaction.response.send_message(
                "✅ Настройката на повторенията беше обновена.",
                ephemeral=True
            )
        except Exception as error:  # pylint: disable=broad-except
            print(f"❌ Грешка при редакция на повторения ({self.msg_id}): {error}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Възникна грешка при обработката. Опитай отново.",
                    ephemeral=True
                )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:  # type: ignore[override]
        print(f"❌ Неочаквана грешка в TimerEditModal ({self.msg_id}): {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Възникна грешка при обработката. Опитай отново.",
                ephemeral=True
            )

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
    if not channel:
        await interaction.response.send_message(
            f"❌ Каналът с ID {CHANNEL_ID} не е намерен.",
            ephemeral=True
        )
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
    await update_embed_status(id)
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
