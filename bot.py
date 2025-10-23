import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
from typing import Optional

# === КОНФИГУРАЦИЯ ===
TOKEN = os.getenv("DISCORD_TOKEN")
# Тези env променливи служат за default канал / guild, но всяко съобщение може да има свой channel_id
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID")) if os.getenv("DISCORD_CHANNEL_ID") else None
GUILD_ID = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID") else None
SAVE_FILE = "active_messages.json"

# Роли с достъп до админ команди
ALLOWED_ROLES = ["Admin", "Moderator"]

# === Intents ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
guild = discord.Object(id=GUILD_ID) if GUILD_ID else None

active_messages = {}  # id -> {task, message, interval, repeat, id, creator, status, embed_message_id, channel_id}

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
            "message": msg.get("message"),
            "interval": msg.get("interval"),
            "repeat": msg.get("repeat"),
            "id": msg.get("id"),
            "creator": msg.get("creator"),
            "status": msg.get("status", "active"),
            "embed_message_id": msg.get("embed_message_id"),
            "channel_id": msg.get("channel_id", None)
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

def get_stored_channel_id(msg_id: str) -> Optional[int]:
    data = get_message_data(msg_id)
    if not data:
        return None
    return data.get("channel_id")

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
    """
    Рестартира/стартира задачата за дадено msg_id.
    Ако start_immediately == False -> първото изпращане ще изчака 'interval' минути.
    Това позволява при edit да не се изпраща веднага.
    """
    msg_data = active_messages.get(msg_id)
    if not msg_data:
        return

    existing_task = msg_data.get("task")
    if existing_task:
        existing_task.cancel()

    if msg_data.get("status") != "active":
        msg_data["task"] = None
        return

    # Определяме канал: ако съобщението има собствен channel_id, го ползваме; иначе default CHANNEL_ID
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
            # ако не искаме веднага да пращаме (напр. след edit), първо чакаме интервала
            interval_minutes = msg_data.get("interval", 0)
            first_wait = not start_immediately
            if first_wait and interval_minutes > 0:
                try:
                    await asyncio.sleep(interval_minutes * 60)
                except asyncio.CancelledError:
                    raise

            while True:
                # Проверка за repeat
                if msg_data.get("repeat", 0) != 0 and count >= msg_data.get("repeat", 0):
                    completed_naturally = True
                    break

                try:
                    await channel.send(msg_data.get("message", ""))
                except discord.Forbidden:
                    print(f"❌ Нямам права да пусна съобщение в канал {target_channel_id}.")
                    # спирам, за да не зацикля
                    completed_naturally = True
                    break
                except Exception as e:
                    print(f"❌ Грешка при пращане на съобщение ({msg_id}): {e}")
                    # продължаваме, може да е временна
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
        # Възстановяване
        active_messages[msg_id] = msg
        active_messages[msg_id]["task"] = None
        # Ако е active, рестартирам, но започвам с първо изпращане веднага (поведение при рестарт да продължи както е било)
        await restart_message_task(msg_id, start_immediately=True)
        await update_embed_status(msg_id)

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

    # Показваме канал само ако е разрешено (public embed го показваме като заключено)
    channel_id = msg_data.get("channel_id") or CHANNEL_id_or_none()
    if show_channel_public:
        channel = bot.get_channel(channel_id) if channel_id else None
        value = channel.mention if channel else (str(channel_id) if channel_id else "—")
        embed.add_field(name="Channel", value=value, inline=False)
    else:
        # public embed: указваме, че каналът е скрит (видим само при edit)
        embed.add_field(name="Channel", value="🔒 (видимо само когато натиснеш Edit)", inline=False)

    embed.timestamp = datetime.utcnow()
    return embed

def CHANNEL_id_or_none():
    return CHANNEL_ID

async def update_embed_status(msg_id):
    msg_data = active_messages.get(msg_id)
    if not msg_data:
        return

    # Публичния канал, в който публикуваме embed-ите със състоянието, е global CHANNEL_ID
    channel = bot.get_channel(CHANNEL_ID) if CHANNEL_ID else None
    if not channel:
        print(f"⚠️ Нямам channel ({CHANNEL_ID}) за обновяване на embed за {msg_id}.")
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
        # Инициализацията на custom_id-ата се прави в __init__ (за да не се дублира)
        # бутоните са дефинирани като методи с декоратор по-долу

    # Start - зелено
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
        # При старт искаме да пуснем веднага (как беше досега)
        await restart_message_task(self.msg_id, start_immediately=True)
        await update_embed_status(self.msg_id)
        save_messages()
        await interaction.response.send_message(f"▶️ '{self.msg_id}' стартира отново.", ephemeral=True)

    # Stop - blurple (default)
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

    # Delete - сив, за да се вижда emoji-то
    @discord.ui.button(emoji="❌", style=discord.ButtonStyle.gray)
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
            channel = bot.get_channel(CHANNEL_ID) if CHANNEL_ID else None
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

    # Edit - вторичен бутон (ephemeral меню)
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

        # Първо изпращаме ephemeral embed с детайли (включително реалния канал), видим само за редактора
        channel_id = msg.get("channel_id") or CHANNEL_id_or_none()
        channel = bot.get_channel(channel_id) if channel_id else None
        ephemeral_embed = build_configuration_embed(msg, show_channel_public=True)
        # Тъй като build_configuration_embed със show_channel_public=True използва channel.mention, всичко е наред.

        view = EditSelectView(self.msg_id)
        await interaction.response.send_message(
            content="Какво искаш да редактираш? (информацията за канала е видима само за теб)",
            embed=ephemeral_embed,
            view=view,
            ephemeral=True
        )

# === Edit select (какво да редактираме) ===
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
                label="Repeat Count",
                description="Edit how many times the message repeats (0 = ∞)",
                value="edit_repeat",
                emoji="🔁"
            ),
            discord.SelectOption(
                label="Channel",
                description="Избор на канал (ChannelSelect)",
                value="edit_channel",
                emoji="💬"
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
        elif selected_option == "edit_repeat":
            await interaction.response.send_modal(RepeatEditModal(self.msg_id))
        elif selected_option == "edit_channel":
            # Отваряме ChannelSelect view (ephemeral)
            view = ChannelSelectView(self.msg_id)
            await interaction.response.send_message("Избери канал от списъка:", view=view, ephemeral=True)

class EditSelectView(discord.ui.View):
    def __init__(self, msg_id: str):
        super().__init__(timeout=120)
        self.msg_id = msg_id
        self.add_item(EditSelect(msg_id))

# === Modals за съдържание/интервал/повторения ===
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
            # При редакция не изпращаме веднага: restart с start_immediately=False
            if msg.get("status") == "active":
                await restart_message_task(self.msg_id, start_immediately=False)

            await update_embed_status(self.msg_id)

            await interaction.response.send_message(
                "✅ Съобщението беше обновено. (Следващото изпращане ще изчака интервала.)",
                ephemeral=True
            )
        except Exception as error:  # pylint: disable=broad-except
            print(f"❌ Грешка при редакция на съдържание ({self.msg_id}): {error}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Възникна грешка при обработката. Опитай отново.",
                    ephemeral=True
                )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
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
                # при редакция: НЕ изпращаме веднага
                await restart_message_task(self.msg_id, start_immediately=False)

            await update_embed_status(self.msg_id)

            await interaction.response.send_message(
                "✅ Интервалът беше обновен. (Следващото изпращане ще изчака новия интервал.)",
                ephemeral=True
            )
        except Exception as error:  # pylint: disable=broad-except
            print(f"❌ Грешка при редакция на интервал ({self.msg_id}): {error}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Възникна грешка при обработката. Опитай отново.",
                    ephemeral=True
                )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        print(f"❌ Неочаквана грешка в IntervalEditModal ({self.msg_id}): {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Възникна грешка при обработката. Опитай отново.",
                ephemeral=True
            )

class RepeatEditModal(discord.ui.Modal):
    def __init__(self, msg_id: str):
        super().__init__(title="Edit Repeat Count", custom_id=f"repeat_modal_{msg_id}")
        self.msg_id = msg_id
        current_repeat = get_stored_repeat(msg_id)

        default_value = str(current_repeat) if current_repeat is not None else ""
        self.new_repeat: discord.ui.TextInput = discord.ui.TextInput(
            label="Repeat Count (0 = ∞)",
            placeholder="Напр. 5",
            default=default_value,
            style=discord.TextStyle.short,
            required=True,
            custom_id="new_repeat"
        )
        self.add_item(self.new_repeat)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if not has_edit_permission(interaction.user):
                print(f"🚫 {interaction.user} опита да редактира повторения без права ({self.msg_id})")
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
                new_repeat = int(self.new_repeat.value)
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
                await restart_message_task(self.msg_id, start_immediately=False)

            await update_embed_status(self.msg_id)

            await interaction.response.send_message(
                "✅ Настройката на повторенията беше обновена. (Следващото изпращане ще изчака интервала.)",
                ephemeral=True
            )
        except Exception as error:  # pylint: disable=broad-except
            print(f"❌ Грешка при редакция на повторения ({self.msg_id}): {error}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Възникна грешка при обработката. Опитай отново.",
                    ephemeral=True
                )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        print(f"❌ Неочаквана грешка в RepeatEditModal ({self.msg_id}): {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Възникна грешка при обработката. Опитай отново.",
                ephemeral=True
            )

# === ChannelSelect view (за избор на канал) ===
class ChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, msg_id: str):
        super().__init__(custom_id=f"channel_select_{msg_id}", placeholder="Избери текстов канал", channel_types=[discord.ChannelType.text])
        self.msg_id = msg_id

    async def callback(self, interaction: discord.Interaction):
        if not has_edit_permission(interaction.user):
            await interaction.response.send_message("🚫 Нямаш права да редактираш канала.", ephemeral=True)
            return

        # ChannelSelect връща list на избраните канали под attribute self.values (в discord.py)
        try:
            selected_channel = self.values[0]  # това е обект канал
            new_channel_id = selected_channel.id
        except Exception:
            # Ако няма избран канал (рядко), плавно се връщаме
            await interaction.response.send_message("⚠️ Няма избран канал.", ephemeral=True)
            return

        try:
            update_channel_value(self.msg_id, new_channel_id)

            msg = get_message_data(self.msg_id)
            if msg and msg.get("status") == "active":
                # При редакция на канала: пак не пращаме веднага в новия канал,
                # стартираме задачата така че първото изпращане да изчака интервала
                await restart_message_task(self.msg_id, start_immediately=False)

            await update_embed_status(self.msg_id)

            await interaction.response.send_message(f"✅ Каналът беше обновен на <#{new_channel_id}>. (Следващото изпращане ще изчака интервала.)", ephemeral=True)
        except Exception as e:
            print(f"❌ Грешка при update channel ({self.msg_id}): {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Възникна грешка при обновяване на канала.", ephemeral=True)

class ChannelSelectView(discord.ui.View):
    def __init__(self, msg_id: str):
        super().__init__(timeout=120)
        self.msg_id = msg_id
        self.add_item(ChannelSelect(msg_id))
        # Добавяме бутон за отказ
        self.add_item(CancelButton())

class CancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Отказ", style=discord.ButtonStyle.secondary, custom_id="cancel_channel_select")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("❌ Отказано.", ephemeral=True)

# === Команди ===
@bot.event
async def on_ready():
    print(f"✅ Влязъл съм като {bot.user}")
    try:
        if guild:
            await tree.sync(guild=guild)
            print(f"🔁 Командите са синхронизирани за guild {GUILD_ID}")
        else:
            await tree.sync()
            print("🔁 Командите са синхронизирани.")
    except Exception as e:
        print(f"❌ Грешка при синхронизиране на командите: {e}")
    await load_messages()
    print("🔁 Възстановени активни съобщения.")

@tree.command(name="create", description="Създай автоматично съобщение.")
@app_commands.describe(
    message="Текст на съобщението",
    interval="Интервал в минути (>0)",
    repeat="Брой повторения (0 = безкрайно)",
    id="Уникален идентификатор",
    channel="Канал (по избор) - ако не е зададен, се ползва default"
)
async def create(interaction: discord.Interaction, message: str, interval: int, repeat: int, id: str, channel: Optional[discord.TextChannel] = None):
    if not has_permission(interaction.user):
        await interaction.response.send_message("🚫 Нямаш права да създаваш съобщения.", ephemeral=True)
        return
    if id in active_messages:
        await interaction.response.send_message(f"⚠️ '{id}' вече съществува.", ephemeral=True)
        return
    if interval <= 0:
        await interaction.response.send_message("❌ Интервалът трябва да е > 0.", ephemeral=True)
        return

    # Определяме channel_id: ако командата подаде канал, използваме него
    channel_id_for_task = channel.id if channel else (CHANNEL_ID if CHANNEL_ID else None)
    if channel_id_for_task is None:
        await interaction.response.send_message(
            f"❌ Няма зададен default канал и не избра канал в командата.",
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
        "embed_message_id": None,
        "channel_id": channel_id_for_task
    }
    active_messages[id] = msg_data
    save_messages()
    # При създаване - оставяме старото поведение: изпраща веднага
    await restart_message_task(id, start_immediately=True)
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
        # Публично в /list не показваме канала (по изискване) - указваме, че е видим само при edit
        embed.add_field(name="Channel", value="🔒 (видимо само когато натиснеш Edit)", inline=False)
        await interaction.followup.send(embed=embed, view=MessageButtons(msg["id"]), ephemeral=True)

@tree.command(name="help_create", description="Показва пример за /create")
async def help_create(interaction: discord.Interaction):
    if not has_permission(interaction.user):
        await interaction.response.send_message("🚫 Нямаш права за тази команда.", ephemeral=True)
        return
    example = (
        "🧠 **Пример:**\n"
        "```\n"
        "/create message:\"Райд след 1 час!\" interval:120 repeat:0 id:\"raid\" channel:#general\n"
        "```\n"
        "- `message`: Текст на съобщението\n"
        "- `interval`: Интервал в минути\n"
        "- `repeat`: Повторения (0 = безкрайно)\n"
        "- `id`: Име на съобщението\n"
        "- `channel`: (по избор) канал за изпращане"
    )
    await interaction.response.send_message(example, ephemeral=True)

# === Стартиране на бота ===
if not TOKEN:
    print("❌ Грешка: Не е зададен DISCORD_TOKEN като env променлива.")
else:
    bot.run(TOKEN)

