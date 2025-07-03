import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import os
import json
import meshtastic
import meshtastic.serial_interface
from pubsub import pub
import asyncio
from datetime import datetime, timezone, timedelta
import secrets
import time
import logging
from logging.handlers import RotatingFileHandler

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[
        RotatingFileHandler('bot.log', maxBytes=10_000_000, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Retrieve environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
GUILD_ID = os.getenv('GUILD_ID')
MESHTASTIC_CHANNEL_ID = os.getenv('MESHTASTIC_CHANNEL_ID')
MESHTASTIC_NODE_CHANNEL_ID = os.getenv('MESHTASTIC_NODE_CHANNEL_ID')
ADMIN_ROLE_ID = os.getenv('ADMIN_ROLE_ID')
NODE_OWNER_ROLE_ID = os.getenv('NODE_OWNER_ROLE_ID')
MESHTASTIC_PORT = os.getenv('MESHTASTIC_PORT')
ADMIN_LOG_CHANNEL_ID = os.getenv('ADMIN_LOG_CHANNEL_ID')

# Debug: Log loaded environment variables
logger.debug(f"Loaded BOT_TOKEN: {BOT_TOKEN}")
logger.debug(f"Loaded GUILD_ID: {GUILD_ID}")
logger.debug(f"Loaded MESHTASTIC_CHANNEL_ID: {MESHTASTIC_CHANNEL_ID}")
logger.debug(f"Loaded MESHTASTIC_NODE_CHANNEL_ID: {MESHTASTIC_NODE_CHANNEL_ID}")
logger.debug(f"Loaded ADMIN_ROLE_ID: {ADMIN_ROLE_ID}")
logger.debug(f"Loaded NODE_OWNER_ROLE_ID: {NODE_OWNER_ROLE_ID}")
logger.debug(f"Loaded MESHTASTIC_PORT: {MESHTASTIC_PORT}")
logger.debug(f"Loaded ADMIN_LOG_CHANNEL_ID: {ADMIN_LOG_CHANNEL_ID}")

# Check required environment variables
required_vars = {
    'BOT_TOKEN': BOT_TOKEN,
    'GUILD_ID': GUILD_ID,
    'MESHTASTIC_CHANNEL_ID': MESHTASTIC_CHANNEL_ID,
    'MESHTASTIC_NODE_CHANNEL_ID': MESHTASTIC_NODE_CHANNEL_ID,
    'ADMIN_ROLE_ID': ADMIN_ROLE_ID,
    'NODE_OWNER_ROLE_ID': NODE_OWNER_ROLE_ID,
    'MESHTASTIC_PORT': MESHTASTIC_PORT
}
missing_vars = [key for key, value in required_vars.items() if value is None]
if missing_vars:
    raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Discord log handler
class DiscordLogHandler(logging.Handler):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.queue = asyncio.Queue()

    def emit(self, record):
        if not ADMIN_LOG_CHANNEL_ID:
            return
        log_message = self.format(record)
        embed_color = {
            logging.DEBUG: discord.Color.blue(),
            logging.INFO: discord.Color.green(),
            logging.WARNING: discord.Color.yellow(),
            logging.ERROR: discord.Color.red(),
            logging.CRITICAL: discord.Color.dark_red()
        }.get(record.levelno, discord.Color.greyple())
        embed = discord.Embed(
            title=record.levelname,
            description=log_message,
            color=embed_color,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Logged via Meshtastic Bot")
        asyncio.run_coroutine_threadsafe(
            self.queue.put(embed),
            self.bot.loop
        )

# Discord log message sender
async def discord_log_sender(bot, queue):
    channel = bot.get_channel(int(ADMIN_LOG_CHANNEL_ID)) if ADMIN_LOG_CHANNEL_ID else None
    if not channel:
        logger.warning("Admin log channel not found or not set; Discord logging disabled")
        return
    while True:
        embed = await queue.get()
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as e:
            logger.error(f"Failed to send log to Discord: {e}")
        await asyncio.sleep(0.2)  # Rate limit: 5 messages/second
        queue.task_done()

# Paths for persistent JSON storage
DATA_FILE = "data.json"
OWNERS_FILE = "owners.json"
MESSAGES_FILE = "messages.json"
ABOUT_FILE = "about.json"
ALERTS_FILE = "alerts.json"
PREFERENCES_FILE = "preferences.json"

# Message size limit (500MB in bytes)
MAX_MESSAGES_FILE_SIZE = 500_000_000
MAX_PREFERENCES_FILE_SIZE = 10_000_000

# Reboot tracking
reboot_in_progress = False
reboot_start_time = 0

# Initialize or load JSON data
def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"nodes": {}, "settings": {}}

def save_data(data):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        logger.error(f"Failed to save data to {DATA_FILE}: {e}")

def load_owners():
    try:
        with open(OWNERS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_owners(owners):
    try:
        with open(OWNERS_FILE, 'w') as f:
            json.dump(owners, f, indent=4)
    except IOError as e:
        logger.error(f"Failed to save owners to {OWNERS_FILE}: {e}")

def load_messages():
    try:
        with open(MESSAGES_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_messages(messages):
    try:
        with open(MESSAGES_FILE, 'w') as f:
            json.dump(messages, f, indent=4)
        while os.path.getsize(MESSAGES_FILE) > MAX_MESSAGES_FILE_SIZE and messages:
            messages.pop(0)
            with open(MESSAGES_FILE, 'w') as f:
                json.dump(messages, f, indent=4)
    except IOError as e:
        logger.error(f"Failed to save messages to {MESSAGES_FILE}: {e}")

def load_about():
    try:
        with open(ABOUT_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "bot_version": "1.0.0",
            "network_size": 0,
            "contact_info": "",
            "last_maintenance": "",
            "custom_message": ""
        }

def save_about(about):
    try:
        with open(ABOUT_FILE, 'w') as f:
            json.dump(about, f, indent=4)
    except IOError as e:
        logger.error(f"Failed to save about to {ABOUT_FILE}: {e}")

def load_alerts():
    try:
        with open(ALERTS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_alerts(alerts):
    try:
        with open(ALERTS_FILE, 'w') as f:
            json.dump(alerts, f, indent=4)
    except IOError as e:
        logger.error(f"Failed to save alerts to {ALERTS_FILE}: {e}")

def load_preferences():
    try:
        with open(PREFERENCES_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_preferences(preferences):
    try:
        with open(PREFERENCES_FILE, 'w') as f:
            json.dump(preferences, f, indent=4)
        while os.path.getsize(PREFERENCES_FILE) > MAX_PREFERENCES_FILE_SIZE and preferences:
            oldest_user = next(iter(preferences))
            del preferences[oldest_user]
            with open(PREFERENCES_FILE, 'w') as f:
                json.dump(preferences, f, indent=4)
    except IOError as e:
        logger.error(f"Failed to save preferences to {PREFERENCES_FILE}: {e}")

# Initialize data
data = load_data()
owners = load_owners()
pending_claims = {}
messages = load_messages()
about = load_about()
alerts = load_alerts()
preferences = load_preferences()

# Set up the bot with intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Add Discord log handler
discord_log_handler = DiscordLogHandler(bot)
discord_log_handler.setLevel(logging.DEBUG)
logger.addHandler(discord_log_handler)

# Meshtastic interface
try:
    meshtastic_interface = meshtastic.serial_interface.SerialInterface(MESHTASTIC_PORT)
except Exception as e:
    logger.error(f"Failed to connect to Meshtastic on {MESHTASTIC_PORT}: {e}")
    meshtastic_interface = None

# Background task to check node status after reboot
async def check_node_status():
    global reboot_in_progress, meshtastic_interface
    while True:
        if reboot_in_progress and meshtastic_interface:
            try:
                node_info = meshtastic_interface.getMyNodeInfo()
                if node_info:
                    reboot_in_progress = False
                    embed = discord.Embed(
                        title="Node Online",
                        description="Meshtastic node reconnected after reboot.",
                        color=discord.Color.green(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    embed.set_footer(text="Status via Meshtastic")
                    channel = bot.get_channel(int(ADMIN_LOG_CHANNEL_ID)) if ADMIN_LOG_CHANNEL_ID else None
                    if channel:
                        await discord_log_handler.queue.put(embed)
                    logger.info("Meshtastic node reconnected after reboot")
            except Exception as e:
                logger.error(f"Failed to check node status: {e}")
        await asyncio.sleep(10)

# Background task to handle scheduled alerts
async def check_alerts():
    while True:
        try:
            alerts = load_alerts()
            current_time = time.time()
            updated_alerts = []
            for alert in alerts:
                if current_time >= alert["next_run"]:
                    if alert["to_discord"]:
                        channel = bot.get_channel(int(MESHTASTIC_CHANNEL_ID))
                        if channel:
                            embed = discord.Embed(
                                title="Scheduled Alert",
                                description=alert["message"],
                                color=discord.Color.blue(),
                                timestamp=datetime.now(timezone.utc)
                            )
                            embed.set_footer(text="Alert via Meshtastic")
                            await channel.send(embed=embed)
                            logger.info(f"Sent Discord alert: {alert['message']}")
                    if alert["to_mesh"] and meshtastic_interface:
                        meshtastic_interface.sendText(text=alert["message"], channelIndex=0)
                        logger.info(f"Sent Meshtastic alert: {alert['message']}")
                    if alert["frequency"] != "once":
                        if alert["frequency"] == "hourly":
                            alert["next_run"] += 3600
                        elif alert["frequency"] == "daily":
                            alert["next_run"] += 86400
                        elif alert["frequency"] == "weekly":
                            alert["next_run"] += 604800
                        updated_alerts.append(alert)
                else:
                    updated_alerts.append(alert)
            save_alerts(updated_alerts)
        except Exception as e:
            logger.error(f"Error processing alerts: {e}")
        await asyncio.sleep(60)

# Meshtastic message handler
async def on_meshtastic_message_async(packet, interface):
    if meshtastic_interface is None:
        return
    if packet.get("decoded", {}).get("portnum") == "TEXT_MESSAGE_APP":
        try:
            sender_id = packet.get("fromId", "Unknown")
            message = packet.get("decoded", {}).get("text", "").strip()
            sender_name = data["nodes"].get(sender_id, "Unknown")
            for user_id, claim_data in list(pending_claims.items()):
                if message == claim_data["code"] and time.time() - claim_data["timestamp"] < 300:
                    owners[sender_id] = user_id
                    save_owners(owners)
                    user = await bot.fetch_user(int(user_id))
                    guild = bot.get_guild(int(GUILD_ID))
                    if guild:
                        member = guild.get_member(int(user_id))
                        if member:
                            role = guild.get_role(int(NODE_OWNER_ROLE_ID))
                            if role and role not in member.roles:
                                await member.add_roles(role)
                    await user.send(f"Success! You are now the owner of node {sender_name} ({sender_id}). You have been granted the Node Owner role.")
                    channel = bot.get_channel(int(MESHTASTIC_CHANNEL_ID))
                    if channel:
                        node_info = meshtastic_interface.nodes.get(sender_id, {})
                        user_data = node_info.get("user", {})
                        short_name = user_data.get("shortName", "N/A")
                        hardware = user_data.get("hwModel", "N/A")
                        role = user_data.get("role", "N/A")
                        battery = node_info.get("batteryLevel", "N/A")
                        if isinstance(battery, int):
                            battery = f"{battery}%"
                        snr = node_info.get("snr", "N/A")
                        embed = discord.Embed(
                            title=f"New Node Claimed by {user.name}",
                            description=f"Congratulations! {user.mention} has claimed a Meshtastic node.",
                            color=discord.Color.green(),
                            timestamp=datetime.now(timezone.utc)
                        )
                        embed.add_field(name="Node Name", value=sender_name, inline=True)
                        embed.add_field(name="Node ID", value=sender_id, inline=True)
                        embed.add_field(name="Short Name", value=short_name, inline=True)
                        embed.add_field(name="Hardware", value=hardware, inline=True)
                        embed.add_field(name="Role", value=role, inline=True)
                        embed.add_field(name="Battery", value=battery, inline=True)
                        embed.add_field(name="SNR", value=snr, inline=True)
                        embed.set_footer(text="Claimed via Meshtastic")
                        await channel.send(embed=embed)
                    del pending_claims[user_id]
                    if user_id in setup_sessions:
                        setup_sessions[user_id]["node_claimed"] = True
                        if setup_sessions[user_id]["step"] == 2.5:
                            await user.send("Node claimed successfully! Moving to next step...")
                            setup_sessions[user_id]["step"] = 3
                            setup_sessions[user_id]["timestamp"] = time.time()
                            await send_preferences_step(user, setup_sessions[user_id])
                    return
            messages.append({
                "node_id": sender_id,
                "timestamp": time.time(),
                "message": message
            })
            save_messages(messages)
            channel = bot.get_channel(int(MESHTASTIC_CHANNEL_ID))
            if not channel:
                logger.error(f"Error: Could not find channel {MESHTASTIC_CHANNEL_ID}")
                return
            snr = packet.get("rxSnr", "N/A")
            battery = packet.get("batteryLevel", "N/A")
            if isinstance(battery, int):
                battery = f"{battery}%"
            embed = discord.Embed(
                title="Meshtastic Message",
                description=message,
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Sender", value=f"{sender_name} ({sender_id})", inline=True)
            embed.add_field(name="Channel", value=channel.name, inline=True)
            embed.add_field(name="SNR", value=snr, inline=True)
            embed.add_field(name="Battery", value=battery, inline=True)
            embed.set_footer(text="Received via Meshtastic")
            await channel.send(embed=embed)
            for user_id, pref in preferences.items():
                if isinstance(pref, dict) and pref.get("dm_notifications", False) and user_id in [owner_id for node_id, owner_id in owners.items() if node_id == sender_id]:
                    try:
                        user = await bot.fetch_user(int(user_id))
                        await user.send(embed=embed)
                    except discord.Forbidden:
                        logger.warning(f"Could not send DM notification to user {user_id}")
        except Exception as e:
            logger.error(f"Error processing Meshtastic message: {e}")

# Meshtastic new node handler
async def on_node_updated_async(node_id):
    if meshtastic_interface is None:
        return
    try:
        node_info = meshtastic_interface.nodes.get(node_id)
        if not node_info:
            return
        long_name = node_info.get("user", {}).get("longName", "Unknown")
        data["nodes"][node_id] = long_name
        save_data(data)
        channel = bot.get_channel(int(MESHTASTIC_NODE_CHANNEL_ID))
        if not channel:
            logger.error(f"Error: Could not find node channel {MESHTASTIC_NODE_CHANNEL_ID}")
            return
        embed = discord.Embed(
            title="New Meshtastic Node Detected",
            description=f"A new node has joined the network.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Node ID", value=node_id, inline=True)
        embed.add_field(name="Name", value=long_name, inline=True)
        embed.add_field(name="Channel", value=channel.name, inline=True)
        embed.set_footer(text="Node joined via Meshtastic")
        await channel.send(embed=embed)
    except Exception as e:
        logger.error(f"Error processing new node: {e}")

# Synchronous wrappers
def on_meshtastic_message(packet, interface):
    asyncio.run_coroutine_threadsafe(
        on_meshtastic_message_async(packet, interface),
        bot.loop
    )

def on_node_updated(node_id):
    asyncio.run_coroutine_threadsafe(
        on_node_updated_async(node_id),
        bot.loop
    )

# Subscribe to Meshtastic events
if meshtastic_interface:
    pub.subscribe(on_meshtastic_message, "meshtastic.receive")
    pub.subscribe(on_node_updated, "meshtastic.node.updated")

# Setup wizard sessions
setup_sessions = {}  # {user_id: {"step": float, "message_id": int, "node_claimed": bool, "dm_notifications": bool, "timestamp": float}}

# Event: Bot is ready and connected
@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user.name}')
    bot.loop.create_task(discord_log_sender(bot, discord_log_handler.queue))
    bot.loop.create_task(check_node_status())
    bot.loop.create_task(check_alerts())
    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.add_command(meshtastic_status, guild=guild)
        bot.tree.add_command(claimnode, guild=guild)
        bot.tree.add_command(releasenode, guild=guild)
        bot.tree.add_command(ownednodes, guild=guild)
        bot.tree.add_command(nodeinfo, guild=guild)
        bot.tree.add_command(addnode, guild=guild)
        bot.tree.add_command(removenode, guild=guild)
        bot.tree.add_command(filtermessages, guild=guild)
        bot.tree.add_command(ack, guild=guild)
        bot.tree.add_command(broadcast, guild=guild)
        bot.tree.add_command(about, guild=guild)
        bot.tree.add_command(reboot, guild=guild)
        bot.tree.add_command(alert, guild=guild)
        bot.tree.add_command(listalerts, guild=guild)
        bot.tree.add_command(deletealert, guild=guild)
        bot.tree.add_command(clearalerts, guild=guild)
        bot.tree.add_command(setup, guild=guild)
        bot.tree.add_command(help, guild=guild)
        await bot.tree.sync(guild=guild)
        logger.info(f'Slash commands synced to guild {GUILD_ID}')
        embed = discord.Embed(
            title="Bot Online",
            description="Meshtastic bot has started.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Status via Meshtastic")
        channel = bot.get_channel(int(ADMIN_LOG_CHANNEL_ID)) if ADMIN_LOG_CHANNEL_ID else None
        if channel:
            await discord_log_handler.queue.put(embed)
    except Exception as e:
        logger.error(f'Error syncing commands: {e}')

# Setup wizard steps
async def send_welcome_step(user, session):
    try:
        embed = discord.Embed(
            title="Welcome to Meshtastic Bot Setup!",
            description="This wizard will guide you through setting up your Meshtastic node and preferences.\n\n"
                        "Use the reactions below to navigate:\n"
                        "➡️ Next | ❌ Cancel",
            color=discord.Color.from_rgb(114, 137, 218),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url="https://meshtastic.org/assets/images/meshtastic_logo.png")
        embed.set_footer(text="Step 1/4 | Meshtastic Setup")
        message = await user.send(embed=embed)
        session["message_id"] = message.id
        for emoji in ["➡️", "❌"]:
            await message.add_reaction(emoji)
        return message
    except discord.Forbidden:
        logger.warning(f"Cannot send welcome step DM to user {user.name}")
        return None

async def send_node_claim_step(user, session):
    try:
        user_id = str(user.id)
        owned_nodes = [node_id for node_id, owner_id in owners.items() if owner_id == user_id]
        description = "Let's claim your Meshtastic node. You'll receive a code to send via your device.\n\n"
        if owned_nodes:
            description += f"You already own {len(owned_nodes)} node(s). Want to claim another?\n\n"
        else:
            description += "You don't own any nodes yet. Let's claim one!\n\n"
        description += "➡️ Claim Node | ⬅️ Back | ❌ Cancel"
        if owned_nodes:
            description += " | ✅ Skip (I have enough nodes)"
        embed = discord.Embed(
            title="Step 2: Claim a Node",
            description=description,
            color=discord.Color.from_rgb(114, 137, 218),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Step 2/4 | Meshtastic Setup")
        message = await user.send(embed=embed)
        session["message_id"] = message.id
        emojis = ["➡️", "⬅️", "❌"]
        if owned_nodes:
            emojis.append("✅")
        for emoji in emojis:
            await message.add_reaction(emoji)
        return message
    except discord.Forbidden:
        logger.warning(f"Cannot send node claim step DM to user {user.name}")
        return None

async def send_preferences_step(user, session):
    try:
        embed = discord.Embed(
            title="Step 3: Set Preferences",
            description="Would you like to receive DM notifications for node events (e.g., new messages from your nodes)?\n\n"
                        "✅ Yes | ❌ No | ⬅️ Back",
            color=discord.Color.from_rgb(114, 137, 218),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Step 3/4 | Meshtastic Setup")
        message = await user.send(embed=embed)
        session["message_id"] = message.id
        for emoji in ["✅", "❌", "⬅️"]:
            await message.add_reaction(emoji)
        return message
    except discord.Forbidden:
        logger.warning(f"Cannot send preferences step DM to user {user.name}")
        return None

async def send_commands_step(user, session):
    try:
        embed = discord.Embed(
            title="Step 4: Learn Commands",
            description="You're all set! Here are some key commands to get started:\n"
                        "- `/meshtastic_status`: Check network status\n"
                        "- `/ownednodes`: View your nodes\n"
                        "- `/nodeinfo <node_id>`: Get node details\n"
                        "- `/help`: See all commands\n\n"
                        "Want to view the full command list now?\n\n"
                        "✅ Yes (run /help) | ❌ Finish | ⬅️ Back",
            color=discord.Color.from_rgb(114, 137, 218),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Step 4/4 | Meshtastic Setup")
        message = await user.send(embed=embed)
        session["message_id"] = message.id
        for emoji in ["✅", "❌", "⬅️"]:
            await message.add_reaction(emoji)
        return message
    except discord.Forbidden:
        logger.warning(f"Cannot send commands step DM to user {user.name}")
        return None

# Setup wizard reaction handler
async def handle_setup_reaction(reaction, user):
    user_id = str(user.id)
    if user_id not in setup_sessions or reaction.message.id != setup_sessions[user_id]["message_id"]:
        return
    session = setup_sessions[user_id]
    current_step = session["step"]
    emoji = str(reaction.emoji)

    # Check session timeout (30 minutes)
    if time.time() - session["timestamp"] > 1800:
        try:
            await user.send("Setup wizard session expired. Please run `/setup` again.")
        except discord.Forbidden:
            logger.warning(f"Cannot send session expired DM to user {user.name}")
        del setup_sessions[user_id]
        logger.info(f"User {user.name} setup session expired")
        return

    # Helper to update session and send new step
    async def update_step(new_step):
        session["step"] = new_step
        session["timestamp"] = time.time()
        if new_step == 1:
            message = await send_welcome_step(user, session)
        elif new_step == 2:
            message = await send_node_claim_step(user, session)
        elif new_step == 3:
            message = await send_preferences_step(user, session)
        elif new_step == 4:
            message = await send_commands_step(user, session)
        if message is None:
            del setup_sessions[user_id]
            logger.error(f"Failed to send step {new_step} to user {user.name} due to DM restrictions")

    try:
        logger.debug(f"Processing reaction {emoji} for user {user.name} on step {current_step}")
        if emoji == "❌":
            await user.send("Setup wizard cancelled.")
            del setup_sessions[user_id]
            logger.info(f"User {user.name} cancelled setup wizard")
            return
        if current_step == 1:
            if emoji == "➡️":
                await update_step(2)
        elif current_step == 2:
            if emoji == "⬅️":
                await update_step(1)
            elif emoji == "➡️":
                if meshtastic_interface is None:
                    await user.send("Error: Meshtastic device not connected. Please try again later.")
                    del setup_sessions[user_id]
                    logger.error(f"User {user.name} attempted node claim but Meshtastic is not connected")
                    return
                if user_id in pending_claims:
                    await user.send("You already have a pending claim. Check your previous DMs for the code.")
                    logger.warning(f"User {user.name} attempted node claim with existing pending claim")
                    return
                code = secrets.token_hex(4)
                pending_claims[user_id] = {"code": code, "timestamp": time.time()}
                await user.send(f"To claim your Meshtastic node, send this code via your device: **{code}**\nIt expires in 5 minutes.\n\n"
                                "Waiting for confirmation... (This message will update when claimed or after 5 minutes)")
                session["step"] = 2.5
                session["message_id"] = (await user.send("Waiting...")).id
                session["timestamp"] = time.time()
                await asyncio.sleep(300)
                if user_id in pending_claims:
                    del pending_claims[user_id]
                    if user_id in setup_sessions and session["step"] == 2.5:
                        await user.send("Claim code expired. Let's try again.")
                        await update_step(2)
            elif emoji == "✅":
                session["node_claimed"] = True
                await update_step(3)
        elif current_step == 2.5:
            # Waiting for claim; no reactions processed
            return
        elif current_step == 3:
            if emoji == "⬅️":
                await update_step(2)
            elif emoji == "✅":
                session["dm_notifications"] = True
                await update_step(4)
            elif emoji == "❌":
                session["dm_notifications"] = False
                await update_step(4)
        elif current_step == 4:
            if emoji == "⬅️":
                await update_step(3)
            elif emoji == "✅":
                preferences[user_id] = {"dm_notifications": session.get("dm_notifications", False)}
                save_preferences(preferences)
                logger.debug(f"Sending help embed to user {user.name} on step 4")
                embed = discord.Embed(
                    title="🔌 Meshtastic Bot Commands",
                    description="Welcome to the Meshtastic Discord bot! Use these commands to manage nodes, view network status, and stay updated with alerts. Type `/` in Discord to explore.",
                    color=discord.Color.from_rgb(114, 137, 218),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_thumbnail(url="https://meshtastic.org/assets/images/meshtastic_logo.png")
                embed.add_field(
                    name="📡 Network & Status",
                    value=(
                        "**/meshtastic_status**: Check node and network status\n"
                        "**/nodeinfo <node_id>**: View details of a specific node (e.g., `!abc123`)"
                    ),
                    inline=True
                )
                embed.add_field(
                    name="📟 Node Management",
                    value=(
                        "**/setup**: Start the interactive setup wizard\n"
                        "**/claimnode**: Claim a node with a code\n"
                        "**/releasenode**: Release your node ownership\n"
                        "**/ownednodes**: List your claimed nodes"
                    ),
                    inline=True
                )
                embed.add_field(
                    name="💬 Messaging",
                    value="**/filtermessages [node_id] [owner]**: Filter message logs by node or owner",
                    inline=True
                )
                embed.add_field(
                    name="🚨 Alerts",
                    value="**/listalerts**: View active scheduled alerts\n**/help**: Show this command list",
                    inline=True
                )
                embed.add_field(
                    name="🔧 Admin Commands (Requires Admin Role)",
                    value=(
                        "**/addnode <node_id> <user>**: Assign a node to a user\n"
                        "**/removenode <node_id>**: Remove a node’s ownership\n"
                        "**/ack <node_id> <message> [channel]**: Send a message to a node\n"
                        "**/broadcast <message> [channel]**: Broadcast to all nodes\n"
                        "**/reboot [seconds]**: Reboot the connected node\n"
                        "**/alert <message> <frequency> [to_discord] [to_mesh]**: Schedule an announcement\n"
                        "**/deletealert <index>**: Delete an alert by index\n"
                        "**/clearalerts**: Clear all alerts"
                    ),
                    inline=False
                )
                embed.set_footer(text="Checked via Meshtastic | Use / to explore commands")
                await user.send(embed=embed)
                del setup_sessions[user_id]
                logger.info(f"User {user.name} completed setup wizard with /help")
            elif emoji == "❌":
                preferences[user_id] = {"dm_notifications": session.get("dm_notifications", False)}
                save_preferences(preferences)
                await user.send("Setup complete! Use `/help` to explore commands.")
                del setup_sessions[user_id]
                logger.info(f"User {user.name} completed setup wizard")
    except Exception as e:
        logger.error(f"Error in setup wizard for user {user.name} on step {current_step} with emoji {emoji}: {e}")
        try:
            await user.send("An error occurred. Please try `/setup` again.")
        except discord.Forbidden:
            logger.warning(f"Cannot send error DM to user {user.name}")
        del setup_sessions[user_id]

# Event: Reaction added
@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return
    await handle_setup_reaction(reaction, user)

# Slash command: /setup
@app_commands.command(name="setup", description="Start an interactive setup wizard to configure your Meshtastic node")
async def setup(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id in setup_sessions:
        await interaction.response.send_message("You already have an active setup session. Check your DMs.", ephemeral=True)
        return
    try:
        await interaction.response.send_message("Setup wizard started! Check your DMs to continue.", ephemeral=True)
        setup_sessions[user_id] = {
            "step": 1,
            "message_id": None,
            "node_claimed": False,
            "dm_notifications": False,
            "timestamp": time.time()
        }
        await interaction.user.send("Starting the Meshtastic Bot Setup Wizard...")
        message = await send_welcome_step(interaction.user, setup_sessions[user_id])
        if message is None:
            await interaction.followup.send("Error: I can't send you a DM. Enable DMs from server members.", ephemeral=True)
            del setup_sessions[user_id]
            return
        logger.info(f"User {interaction.user.name} started setup wizard")
    except discord.Forbidden:
        logger.warning(f"Cannot send DM to user {interaction.user.name} for setup wizard")
        await interaction.followup.send("Error: I can't send you a DM. Enable DMs from server members.", ephemeral=True)
        if user_id in setup_sessions:
            del setup_sessions[user_id]
    except Exception as e:
        logger.error(f"Error starting setup wizard for {interaction.user.name}: {e}")
        await interaction.followup.send("Error starting setup wizard. Try again later.", ephemeral=True)
        if user_id in setup_sessions:
            del setup_sessions[user_id]

# Slash command: /help
@app_commands.command(name="help", description="Show available bot commands")
async def help(interaction: discord.Interaction):
    try:
        embed = discord.Embed(
            title="🔌 Meshtastic Bot Commands",
            description="Welcome to the Meshtastic Discord bot! Use these commands to manage nodes, view network status, and stay updated with alerts. Type `/` in Discord to explore.",
            color=discord.Color.from_rgb(114, 137, 218),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url="https://meshtastic.org/assets/images/meshtastic_logo.png")
        embed.add_field(
            name="📡 Network & Status",
            value=(
                "**/meshtastic_status**: Check node and network status\n"
                "**/nodeinfo <node_id>**: View details of a specific node (e.g., `!abc123`)"
            ),
            inline=True
        )
        embed.add_field(
            name="📟 Node Management",
            value=(
                "**/setup**: Start the interactive setup wizard\n"
                "**/claimnode**: Claim a node with a code\n"
                "**/releasenode**: Release your node ownership\n"
                "**/ownednodes**: List your claimed nodes"
            ),
            inline=True
        )
        embed.add_field(
            name="💬 Messaging",
            value="**/filtermessages [node_id] [owner]**: Filter message logs by node or owner",
            inline=True
        )
        embed.add_field(
            name="🚨 Alerts",
            value="**/listalerts**: View active scheduled alerts\n**/help**: Show this command list",
            inline=True
        )
        embed.add_field(
            name="🔧 Admin Commands (Requires Admin Role)",
            value=(
                "**/addnode <node_id> <user>**: Assign a node to a user\n"
                "**/removenode <node_id>**: Remove a node’s ownership\n"
                "**/ack <node_id> <message> [channel]**: Send a message to a node\n"
                "**/broadcast <message> [channel]**: Broadcast to all nodes\n"
                "**/reboot [seconds]**: Reboot the connected node\n"
                "**/alert <message> <frequency> [to_discord] [to_mesh]**: Schedule an announcement\n"
                "**/deletealert <index>**: Delete an alert by index\n"
                "**/clearalerts**: Clear all alerts"
            ),
            inline=False
        )
        embed.set_footer(text="Checked via Meshtastic | Use / to explore commands")
        await interaction.response.send_message(embed=embed)
        logger.info(f"User {interaction.user.name} used /help command")
    except Exception as e:
        logger.error(f"Error in /help command: {e}")
        embed = discord.Embed(
            title="Help Error",
            description=f"Failed to list commands: {e}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Checked via Meshtastic")
        await interaction.response.send_message(embed=embed)

# Slash command: /clearalerts
@app_commands.command(name="clearalerts", description="Admin: Clear all scheduled alerts")
async def clearalerts(interaction: discord.Interaction):
    if not any(role.id == int(ADMIN_ROLE_ID) for role in interaction.user.roles):
        await interaction.response.send_message("Error: You need the admin role to use this command.", ephemeral=True)
        return
    try:
        alerts = load_alerts()
        if not alerts:
            embed = discord.Embed(
                title="Clear Alerts Error",
                description="No alerts exist to clear.",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text="Command via Meshtastic")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.error(f"User {interaction.user.name} attempted to clear alerts but none exist")
            return
        save_alerts([])
        embed = discord.Embed(
            title="All Alerts Cleared",
            description="All scheduled alerts have been removed.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Command via Meshtastic")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"User {interaction.user.name} cleared all alerts")
    except Exception as e:
        logger.error(f"Error in /clearalerts command: {e}")
        embed = discord.Embed(
            title="Clear Alerts Error",
            description=f"Failed to clear alerts: {e}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Command via Meshtastic")
        await interaction.response.send_message(embed=embed, ephemeral=True)

# Slash command: /deletealert
@app_commands.command(name="deletealert", description="Admin: Delete a scheduled alert by index")
@app_commands.describe(index="The alert index from /listalerts")
async def deletealert(interaction: discord.Interaction, index: int):
    if not any(role.id == int(ADMIN_ROLE_ID) for role in interaction.user.roles):
        await interaction.response.send_message("Error: You need the admin role to use this command.", ephemeral=True)
        return
    try:
        alerts = load_alerts()
        if not alerts or index < 1 or index > len(alerts):
            embed = discord.Embed(
                title="Delete Alert Error",
                description="Invalid alert index or no alerts exist.",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text="Command via Meshtastic")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.error(f"User {interaction.user.name} attempted to delete invalid alert index {index}")
            return
        deleted_alert = alerts.pop(index - 1)
        save_alerts(alerts)
        embed = discord.Embed(
            title="Alert Deleted",
            description=f"Removed alert: {deleted_alert['message']}",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Command via Meshtastic")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"User {interaction.user.name} deleted alert: {deleted_alert['message']} (index {index})")
    except Exception as e:
        logger.error(f"Error in /deletealert command: {e}")
        embed = discord.Embed(
            title="Delete Alert Error",
            description=f"Failed to delete alert: {e}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Command via Meshtastic")
        await interaction.response.send_message(embed=embed, ephemeral=True)

# Slash command: /listalerts
@app_commands.command(name="listalerts", description="List all active scheduled alerts")
async def listalerts(interaction: discord.Interaction):
    try:
        alerts = load_alerts()
        current_time = time.time()
        active_alerts = [
            alert for alert in alerts
            if alert["frequency"] != "once" or alert["next_run"] > current_time
        ]
        embed = discord.Embed(
            title="Scheduled Alerts",
            description="List of active scheduled alerts." if active_alerts else "No active alerts scheduled.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        if active_alerts:
            alerts_text = "\n".join(
                f"{i+1}. {alert['message']} (Frequency: {alert['frequency'].capitalize()}, "
                f"Discord: {alert['to_discord']}, Mesh: {alert['to_mesh']}, "
                f"Next: {datetime.fromtimestamp(alert['next_run'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S')})"
                for i, alert in enumerate(active_alerts)
            )
            embed.add_field(name="Alerts", value=alerts_text, inline=False)
        embed.set_footer(text="Checked via Meshtastic")
        await interaction.response.send_message(embed=embed)
        logger.info(f"User {interaction.user.name} used /listalerts command")
    except Exception as e:
        logger.error(f"Error in /listalerts command: {e}")
        embed = discord.Embed(
            title="List Alerts Error",
            description=f"Failed to list alerts: {e}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Checked via Meshtastic")
        await interaction.response.send_message(embed=embed)

# Slash command: /alert
@app_commands.command(name="alert", description="Admin: Schedule a recurring or one-time announcement")
@app_commands.describe(
    message="The announcement message",
    frequency="How often to send (once, hourly, daily, weekly)",
    to_discord="Send to Discord channel (default: True)",
    to_mesh="Send to Meshtastic network (default: False)"
)
async def alert(interaction: discord.Interaction, message: str, frequency: str, to_discord: bool = True, to_mesh: bool = False):
    if not any(role.id == int(ADMIN_ROLE_ID) for role in interaction.user.roles):
        await interaction.response.send_message("Error: You need the admin role to use this command.", ephemeral=True)
        return
    valid_frequencies = ["once", "hourly", "daily", "weekly"]
    if frequency.lower() not in valid_frequencies:
        await interaction.response.send_message(f"Error: Frequency must be one of {', '.join(valid_frequencies)}.", ephemeral=True)
        return
    try:
        alerts = load_alerts()
        next_run = time.time()
        alerts.append({
            "message": message,
            "frequency": frequency.lower(),
            "to_discord": to_discord,
            "to_mesh": to_mesh,
            "next_run": next_run
        })
        save_alerts(alerts)
        embed = discord.Embed(
            title="Alert Scheduled",
            description=f"Message: {message}\nFrequency: {frequency}\nTo Discord: {to_discord}\nTo Mesh: {to_mesh}",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Command via Meshtastic")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"User {interaction.user.name} scheduled alert: {message} (frequency: {frequency})")
    except Exception as e:
        logger.error(f"Error in /alert command: {e}")
        embed = discord.Embed(
            title="Alert Error",
            description=f"Failed to schedule alert: {e}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Command via Meshtastic")
        await interaction.response.send_message(embed=embed, ephemeral=True)

# Slash command: /about
@app_commands.command(name="about", description="Show information about the Meshtastic bot and node")
async def about(interaction: discord.Interaction):
    try:
        about_data = load_about()
        embed = discord.Embed(
            title="Meshtastic Bot Info",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        if meshtastic_interface:
            node_info = meshtastic_interface.getMyNodeInfo() or {}
            user = node_info.get("user", {})
            node_id = node_info.get("id", "N/A")
            embed.add_field(name="Node ID", value=node_id, inline=True)
            embed.add_field(name="Node Name", value=user.get("longName", "N/A"), inline=True)
            embed.add_field(name="Short Name", value=user.get("shortName", "N/A"), inline=True)
            embed.add_field(name="Hardware", value=user.get("hwModel", "N/A"), inline=True)
            embed.add_field(name="Role", value=user.get("role", "N/A"), inline=True)
            embed.add_field(name="Battery", value=f"{node_info.get('batteryLevel', 'N/A')}%", inline=True)
            embed.add_field(name="SNR", value=node_info.get("snr", "N/A"), inline=True)
            position = node_info.get("position", {})
            embed.add_field(name="Latitude", value=position.get("latitude", "N/A"), inline=True)
            embed.add_field(name="Longitude", value=position.get("longitude", "N/A"), inline=True)
            embed.add_field(name="Altitude", value=position.get("altitude", "N/A"), inline=True)
            last_heard = node_info.get("lastHeard", 0)
            last_heard_str = datetime.fromtimestamp(last_heard, timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if last_heard else "N/A"
            embed.add_field(name="Last Heard", value=last_heard_str, inline=True)
            uptime = (time.time() - last_heard) / 3600 if last_heard else "N/A"
            uptime_str = f"{uptime:.2f} hours" if isinstance(uptime, float) else uptime
            embed.add_field(name="Uptime", value=uptime_str, inline=True)
        else:
            embed.add_field(name="Node Status", value="Meshtastic device not connected", inline=False)
        owner_name = "No Admin Found"
        guild = bot.get_guild(int(GUILD_ID))
        if guild and ADMIN_ROLE_ID:
            try:
                admin_role = guild.get_role(int(ADMIN_ROLE_ID))
                if admin_role:
                    for member in guild.members:
                        if admin_role in member.roles:
                            owner_name = member.name
                            break
                else:
                    logger.error(f"Admin role ID {ADMIN_ROLE_ID} not found in guild")
            except Exception as e:
                logger.error(f"Failed to fetch admin role or members: {e}")
                owner_name = "Error fetching admin"
        embed.add_field(name="Bot Owner", value=owner_name, inline=True)
        embed.add_field(name="Bot Version", value=about_data.get("bot_version", "N/A"), inline=True)
        embed.add_field(name="Network Size", value=str(about_data.get("network_size", 0)), inline=True)
        embed.add_field(name="Contact Info", value=about_data.get("contact_info", "N/A"), inline=True)
        embed.add_field(name="Last Maintenance", value=about_data.get("last_maintenance", "N/A"), inline=True)
        embed.add_field(name="Custom Message", value=about_data.get("custom_message", "N/A"), inline=False)
        embed.set_footer(text="Checked via Meshtastic")
        await interaction.response.send_message(embed=embed)
        logger.info(f"User {interaction.user.name} used /about command")
    except Exception as e:
        logger.error(f"Error in /about command: {e}")
        embed = discord.Embed(
            title="About",
            description=f"Error fetching bot info: {e}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Checked via Meshtastic")
        await interaction.response.send_message(embed=embed)

# Slash command: /reboot
@app_commands.command(name="reboot", description="Admin: Reboot the connected Meshtastic node")
@app_commands.describe(seconds="Delay before reboot (default 10 seconds)")
async def reboot(interaction: discord.Interaction, seconds: int = 10):
    global reboot_in_progress
    if not any(role.id == int(ADMIN_ROLE_ID) for role in interaction.user.roles):
        await interaction.response.send_message("Error: You need the admin role to use this command.", ephemeral=True)
        return
    if meshtastic_interface is None:
        await interaction.response.send_message("Error: Meshtastic device not connected.", ephemeral=True)
        return
    try:
        if seconds < 1:
            await interaction.response.send_message("Error: Reboot delay must be at least 1 second.", ephemeral=True)
            return
        meshtastic_interface.localNode.reboot(seconds)
        reboot_in_progress = True
        embed = discord.Embed(
            title="Node Reboot Initiated",
            description=f"Rebooting Meshtastic node in {seconds} seconds.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Command via Meshtastic")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"User {interaction.user.name} initiated node reboot with {seconds}-second delay")
    except Exception as e:
        logger.error(f"Error in /reboot command: {e}")
        embed = discord.Embed(
            title="Reboot Error",
            description=f"Failed to initiate reboot: {e}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Command via Meshtastic")
        await interaction.response.send_message(embed=embed, ephemeral=True)

# Slash command: /meshtastic_status
@app_commands.command(name="meshtastic_status", description="Show Meshtastic node and network status")
async def meshtastic_status(interaction: discord.Interaction):
    if meshtastic_interface is None:
        embed = discord.Embed(
            title="Meshtastic Status",
            description="Error: Meshtastic device not connected.",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Checked via Meshtastic")
        await interaction.response.send_message(embed=embed)
        return
    try:
        node_on = False
        local_node_info = None
        try:
            local_node_info = meshtastic_interface.getMyNodeInfo()
            node_on = bool(local_node_info)
        except Exception as e:
            logger.warning(f"Failed to get node info: {e}")
        nodes = meshtastic_interface.nodes
        network_connected = len(nodes) > 1
        data["nodes"] = {node_id: node.get("user", {}).get("longName", "Unknown") for node_id, node in nodes.items()}
        save_data(data)
        embed = discord.Embed(
            title="Meshtastic Status",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(
            name="Node Status",
            value="On" if node_on else "Off or inaccessible",
            inline=True
        )
        embed.add_field(
            name="Network Connection",
            value="Connected" if network_connected else "Not connected (no other nodes detected)",
            inline=True
        )
        embed.set_footer(text="Checked via Meshtastic")
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            title="Meshtastic Status",
            description=f"Error fetching status: {e}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Checked via Meshtastic")
        await interaction.response.send_message(embed=embed)

# Slash command: /claimnode
@app_commands.command(name="claimnode", description="Claim a Meshtastic node by receiving a code")
async def claimnode(interaction: discord.Interaction):
    if meshtastic_interface is None:
        await interaction.response.send_message("Error: Meshtastic device not connected.", ephemeral=True)
        return
    user_id = str(interaction.user.id)
    if user_id in pending_claims:
        await interaction.response.send_message("You already have a pending claim. Check your DMs for the code.", ephemeral=True)
        return
    try:
        code = secrets.token_hex(4)
        pending_claims[user_id] = {"code": code, "timestamp": time.time()}
        await interaction.user.send(f"To claim your Meshtastic node, send this code via your device: **{code}**\nIt expires in 5 minutes.")
        await interaction.response.send_message("Check your DMs for a code to send via your Meshtastic device.", ephemeral=True)
        logger.info(f"User {interaction.user.name} initiated node claim with code {code}")
    except discord.Forbidden:
        await interaction.response.send_message("Error: I can't send you a DM. Enable DMs from server members.", ephemeral=True)
        logger.warning(f"Cannot send claim code DM to user {interaction.user.name}")

# Slash command: /releasenode
@app_commands.command(name="releasenode", description="Release ownership of a Meshtastic node")
async def releasenode(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    owned_node = None
    for node_id, owner_id in list(owners.items()):
        if owner_id == user_id:
            owned_node = node_id
            break
    if not owned_node:
        await interaction.response.send_message("You don't own any nodes.", ephemeral=True)
        return
    try:
        node_name = data["nodes"].get(owned_node, "Unknown")
        del owners[owned_node]
        save_owners(owners)
        guild = bot.get_guild(int(GUILD_ID))
        if guild:
            member = guild.get_member(int(user_id))
            if member and not any(owner_id == user_id for owner_id in owners.values()):
                role = guild.get_role(int(NODE_OWNER_ROLE_ID))
                if role and role in member.roles:
                    await member.remove_roles(role)
        await interaction.response.send_message(f"You have released ownership of node {node_name} ({owned_node}).", ephemeral=True)
        logger.info(f"User {interaction.user.name} released node {node_name} ({owned_node})")
    except Exception as e:
        logger.error(f"Error in /releasenode command for user {interaction.user.name}: {e}")
        await interaction.response.send_message(f"Error releasing node: {e}", ephemeral=True)

# Slash command: /ownednodes
@app_commands.command(name="ownednodes", description="Show your claimed Meshtastic nodes")
async def ownednodes(interaction: discord.Interaction):
    try:
        user_id = str(interaction.user.id)
        owned_nodes = [
            (node_id, data["nodes"].get(node_id, "Unknown"))
            for node_id, owner_id in owners.items()
            if owner_id == user_id
        ]
        embed = discord.Embed(
            title=f"{interaction.user.name}'s Claimed Nodes",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        if not owned_nodes:
            embed.description = "You don't own any nodes. Use /claimnode to claim one."
        else:
            nodes_text = "\n".join(f"- {name} ({node_id})" for node_id, name in owned_nodes)
            embed.add_field(name="Nodes", value=nodes_text, inline=False)
        embed.set_footer(text="Checked via Meshtastic")
        await interaction.response.send_message(embed=embed)
        logger.info(f"User {interaction.user.name} used /ownednodes command")
    except Exception as e:
        logger.error(f"Error in /ownednodes command for user {interaction.user.name}: {e}")
        embed = discord.Embed(
            title="Owned Nodes Error",
            description=f"Error fetching owned nodes: {e}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Checked via Meshtastic")
        await interaction.response.send_message(embed=embed)

# Slash command: /nodeinfo
@app_commands.command(name="nodeinfo", description="Get detailed info about a specific Meshtastic node")
@app_commands.describe(node_id="The Node ID (e.g., !abc123)")
async def nodeinfo(interaction: discord.Interaction, node_id: str):
    if meshtastic_interface is None:
        embed = discord.Embed(
            title="Node Info",
            description="Error: Meshtastic device not connected.",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Checked via Meshtastic")
        await interaction.response.send_message(embed=embed)
        return
    try:
        node_id = node_id.strip()
        nodes = meshtastic_interface.nodes
        node_info = nodes.get(node_id)
        if not node_info:
            embed = discord.Embed(
                title="Node Info",
                description=f"Node {node_id} not found.",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text="Checked via Meshtastic")
            await interaction.response.send_message(embed=embed)
            return
        name = data["nodes"].get(node_id, "Unknown")
        user = node_info.get("user", {})
        short_name = user.get("shortName", "N/A")
        hardware = user.get("hwModel", "N/A")
        role = user.get("role", "N/A")
        battery = node_info.get("batteryLevel", "N/A")
        if isinstance(battery, int):
            battery = f"{battery}%"
        snr = node_info.get("snr", "N/A")
        last_heard = node_info.get("lastHeard", 0)
        last_heard_str = datetime.fromtimestamp(last_heard, timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if last_heard else "N/A"
        position = node_info.get("position", {})
        latitude = position.get("latitude", "N/A")
        longitude = position.get("longitude", "N/A")
        altitude = position.get("altitude", "N/A")
        owner_id = owners.get(node_id)
        owner = None
        owner_text = "None"
        if owner_id:
            try:
                owner = await bot.fetch_user(int(owner_id))
                owner_text = owner.name
            except:
                owner_text = f"ID: {owner_id}"
        embed = discord.Embed(
            title=f"Node Info: {name} ({node_id})",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Short Name", value=short_name, inline=True)
        embed.add_field(name="Hardware", value=hardware, inline=True)
        embed.add_field(name="Role", value=role, inline=True)
        embed.add_field(name="Battery", value=battery, inline=True)
        embed.add_field(name="SNR", value=snr, inline=True)
        embed.add_field(name="Last Heard", value=last_heard_str, inline=True)
        embed.add_field(name="Latitude", value=latitude, inline=True)
        embed.add_field(name="Longitude", value=longitude, inline=True)
        embed.add_field(name="Altitude", value=altitude, inline=True)
        embed.add_field(name="Owner", value=owner_text, inline=True)
        embed.set_footer(text="Checked via Meshtastic")
        await interaction.response.send_message(embed=embed)
        logger.info(f"User {interaction.user.name} used /nodeinfo for node {node_id}")
    except Exception as e:
        logger.error(f"Error in /nodeinfo command for user {interaction.user.name}: {e}")
        embed = discord.Embed(
            title="Node Info",
            description=f"Error fetching node info: {e}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Checked via Meshtastic")
        await interaction.response.send_message(embed=embed)

# Slash command: /addnode
@app_commands.command(name="addnode", description="Admin: Assign a node to a user")
@app_commands.describe(node_id="The Node ID (e.g., !abc123)", user="The user to assign the node to")
async def addnode(interaction: discord.Interaction, node_id: str, user: discord.Member):
    if not any(role.id == int(ADMIN_ROLE_ID) for role in interaction.user.roles):
        await interaction.response.send_message("Error: You need the admin role to use this command.", ephemeral=True)
        return
    try:
        node_id = node_id.strip()
        nodes = meshtastic_interface.nodes if meshtastic_interface else {}
        if node_id not in nodes:
            await interaction.response.send_message(f"Error: Node {node_id} not found.", ephemeral=True)
            return
        user_id = str(user.id)
        owners[node_id] = user_id
        save_owners(owners)
        guild = bot.get_guild(int(GUILD_ID))
        if guild:
            role = guild.get_role(int(NODE_OWNER_ROLE_ID))
            if role and role not in user.roles:
                await user.add_roles(role)
        node_name = data["nodes"].get(node_id, "Unknown")
        await interaction.response.send_message(f"Node {node_name} ({node_id}) assigned to {user.name}.", ephemeral=True)
        logger.info(f"User {interaction.user.name} assigned node {node_name} ({node_id}) to {user.name}")
    except Exception as e:
        logger.error(f"Error in /addnode command for user {interaction.user.name}: {e}")
        await interaction.response.send_message(f"Error assigning node: {e}", ephemeral=True)

# Slash command: /removenode
@app_commands.command(name="removenode", description="Admin: Remove a node's ownership")
@app_commands.describe(node_id="The Node ID (e.g., !abc123)")
async def removenode(interaction: discord.Interaction, node_id: str):
    if not any(role.id == int(ADMIN_ROLE_ID) for role in interaction.user.roles):
        await interaction.response.send_message("Error: You need the admin role to use this command.", ephemeral=True)
        return
    try:
        node_id = node_id.strip()
        if node_id not in owners:
            await interaction.response.send_message(f"Error: Node {node_id} has no owner.", ephemeral=True)
            return
        user_id = owners[node_id]
        node_name = data["nodes"].get(node_id, "Unknown")
        del owners[node_id]
        save_owners(owners)
        guild = bot.get_guild(int(GUILD_ID))
        if guild:
            member = guild.get_member(int(user_id))
            if member and not any(owner_id == user_id for owner_id in owners.values()):
                role = guild.get_role(int(NODE_OWNER_ROLE_ID))
                if role and role in member.roles:
                    await member.remove_roles(role)
        await interaction.response.send_message(f"Ownership of node {node_name} ({node_id}) removed.", ephemeral=True)
        logger.info(f"User {interaction.user.name} removed ownership of node {node_name} ({node_id})")
    except Exception as e:
        logger.error(f"Error in /removenode command for user {interaction.user.name}: {e}")
        await interaction.response.send_message(f"Error removing node ownership: {e}", ephemeral=True)

# Slash command: /filtermessages
@app_commands.command(name="filtermessages", description="Filter Meshtastic messages by node, user, or owner")
@app_commands.describe(
    node_id="Filter by Node ID (e.g., !abc123), optional",
    owner="Filter by node owner (Discord user), optional"
)
async def filtermessages(interaction: discord.Interaction, node_id: str = None, owner: discord.Member = None):
    if not messages:
        embed = discord.Embed(
            title="Filtered Messages",
            description="No messages found in the log.",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Checked via Meshtastic")
        await interaction.response.send_message(embed=embed)
        return
    try:
        filtered_messages = messages
        filter_description = []
        if node_id:
            node_id = node_id.strip()
            if node_id not in meshtastic_interface.nodes:
                embed = discord.Embed(
                    title="Filtered Messages",
                    description=f"Node {node_id} not found.",
                    color=discord.Color.red(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_footer(text="Checked via Meshtastic")
                await interaction.response.send_message(embed=embed)
                return
            filtered_messages = [msg for msg in filtered_messages if msg["node_id"] == node_id]
            filter_description.append(f"Node ID: {node_id}")
        elif not owner:
            user_id = str(interaction.user.id)
            owned_nodes = [node_id for node_id, owner_id in owners.items() if owner_id == user_id]
            if not owned_nodes:
                embed = discord.Embed(
                    title="Filtered Messages",
                    description="You don't own any nodes.",
                    color=discord.Color.red(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_footer(text="Checked via Meshtastic")
                await interaction.response.send_message(embed=embed)
                return
            filtered_messages = [msg for msg in filtered_messages if msg["node_id"] in owned_nodes]
            filter_description.append(f"User: {interaction.user.name}")
        else:
            owner_id = str(owner.id)
            owned_nodes = [node_id for node_id, owner_id in owners.items() if owner_id == owner_id]
            if not owned_nodes:
                embed = discord.Embed(
                    title="Filtered Messages",
                    description=f"{owner.name} doesn't own any nodes.",
                    color=discord.Color.red(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_footer(text="Checked via Meshtastic")
                await interaction.response.send_message(embed=embed)
                return
            filtered_messages = [msg for msg in filtered_messages if msg["node_id"] in owned_nodes]
            filter_description.append(f"Owner: {owner.name}")
        embed = discord.Embed(
            title="Filtered Messages",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Filter", value=", ".join(filter_description) or "None", inline=False)
        if not filtered_messages:
            embed.description = "No messages match the filter."
        else:
            messages_text = "\n".join(
                f"**{data['nodes'].get(msg['node_id'], 'Unknown')} ({msg['node_id']})** at {datetime.fromtimestamp(msg['timestamp'], timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}: {msg['message']}"
                for msg in filtered_messages[-5:]
            )
            embed.add_field(name="Messages", value=messages_text, inline=False)
        embed.set_footer(text="Checked via Meshtastic")
        await interaction.response.send_message(embed=embed)
        logger.info(f"User {interaction.user.name} used /filtermessages command")
    except Exception as e:
        logger.error(f"Error in /filtermessages command for user {interaction.user.name}: {e}")
        embed = discord.Embed(
            title="Filtered Messages",
            description=f"Error filtering messages: {e}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Checked via Meshtastic")
        await interaction.response.send_message(embed=embed)

# Slash command: /ack
@app_commands.command(name="ack", description="Admin: Send a message to a specific Meshtastic node")
@app_commands.describe(
    node_id="The Node ID (e.g., !abc123)",
    message="The message to send",
    channel="The Meshtastic channel index (0-7, default 0)"
)
async def ack(interaction: discord.Interaction, node_id: str, message: str, channel: int = 0):
    if not any(role.id == int(ADMIN_ROLE_ID) for role in interaction.user.roles):
        await interaction.response.send_message("Error: You need the admin role to use this command.", ephemeral=True)
        return
    if meshtastic_interface is None:
        await interaction.response.send_message("Error: Meshtastic device not connected.", ephemeral=True)
        return
    try:
        node_id = node_id.strip()
        nodes = meshtastic_interface.nodes
        if node_id not in nodes:
            await interaction.response.send_message(f"Error: Node {node_id} not found.", ephemeral=True)
            return
        if not (0 <= channel <= 7):
            await interaction.response.send_message("Error: Channel index must be between 0 and 7.", ephemeral=True)
            return
        meshtastic_interface.sendText(
            text=message,
            destinationId=node_id,
            channelIndex=channel
        )
        node_name = data["nodes"].get(node_id, "Unknown")
        await interaction.response.send_message(f"Message sent to {node_name} ({node_id}) on channel {channel}: {message}", ephemeral=True)
        logger.info(f"User {interaction.user.name} sent message to node {node_name} ({node_id})")
    except Exception as e:
        logger.error(f"Error in /ack command for user {interaction.user.name}: {e}")
        await interaction.response.send_message(f"Error sending message: {e}", ephemeral=True)

# Slash command: /broadcast
@app_commands.command(name="broadcast", description="Admin: Broadcast a message to all Meshtastic nodes")
@app_commands.describe(
    message="The message to broadcast",
    channel="The Meshtastic channel index (0-7, default 0)"
)
async def broadcast(interaction: discord.Interaction, message: str, channel: int = 0):
    if not any(role.id == int(ADMIN_ROLE_ID) for role in interaction.user.roles):
        await interaction.response.send_message("Error: You need the admin role to use this command.", ephemeral=True)
        return
    if meshtastic_interface is None:
        await interaction.response.send_message("Error: Meshtastic device not connected.", ephemeral=True)
        return
    try:
        if not (0 <= channel <= 7):
            await interaction.response.send_message("Error: Channel index must be between 0 and 7.", ephemeral=True)
            return
        meshtastic_interface.sendText(
            text=message,
            destinationId="^all",
            channelIndex=channel
        )
        await interaction.response.send_message(f"Broadcast message sent on channel {channel}: {message}", ephemeral=True)
        logger.info(f"User {interaction.user.name} broadcasted message on channel {channel}")
    except Exception as e:
        logger.error(f"Error in /broadcast command for user {interaction.user.name}: {e}")
        await interaction.response.send_message(f"Error broadcasting message: {e}", ephemeral=True)

# Run the bot
bot.run(BOT_TOKEN)