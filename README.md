📡 Discord-Meshtastic-USB-Bot
Welcome to the Discord-Meshtastic-USB-Bot, a powerful Discord bot that seamlessly integrates with a Meshtastic mesh network connected via USB. This bot allows users to manage nodes, send messages, schedule alerts, and monitor network status, all from within Discord. With an intuitive setup wizard and robust command set, it’s perfect for hobbyists and communities using Meshtastic for off-grid communication.

🚀 Features

Interactive Setup Wizard (/setup): Guides new users through claiming a Meshtastic node and setting preferences via DMs with reaction-based navigation.
Node Management:
Claim Nodes (/claimnode): Users can claim ownership of a Meshtastic node by sending a unique code via their device.
Release Nodes (/releasenode): Release ownership of a claimed node.
View Owned Nodes (/ownednodes): List all nodes owned by a user.
Node Info (/nodeinfo <node_id>): Display detailed information (name, hardware, battery, SNR, location) for a specific node.


Messaging:
Filter Messages (/filtermessages): View message logs filtered by node ID or owner.
Send Messages (/ack <node_id> <message>): Admins can send messages to specific nodes.
Broadcast Messages (/broadcast <message>): Admins can broadcast messages to all nodes.


Network Monitoring:
Status Check (/meshtastic_status): Show the status of the connected Meshtastic node and network.
Node Detection: Automatically notifies a Discord channel when new nodes join the network.


Alerts:
Schedule Alerts (/alert <message> <frequency>): Admins can schedule recurring or one-time announcements to Discord or Meshtastic.
Manage Alerts (/listalerts, /deletealert, /clearalerts): View, delete, or clear scheduled alerts.


User-Friendly Help (/help): Displays a categorized list of commands in a sleek Discord embed.
Secure and Robust:
Stores data in JSON files (data.json, owners.json, etc.) for persistence.
Logs all actions and errors to bot.log and an admin Discord channel for transparency.
Excludes sensitive data (e.g., .env) via .gitignore.



🛠️ Setup
Prerequisites

Python 3.8+
Meshtastic Device: Connected via USB (e.g., COM3 on Windows).
Discord Bot Token: Create a bot on the Discord Developer Portal with message_content, members, and reactions intents enabled.
Git: Installed for cloning the repository.
Dependencies: discord.py, python-dotenv, meshtastic (installed via pip).

Installation

Clone the Repository:
git clone https://github.com/BOOK-Y0D4/Discord-Meshtastic-USB-Bot.git
cd Discord-Meshtastic-USB-Bot


Install Dependencies:
pip install discord.py python-dotenv meshtastic


Configure Environment Variables:

Copy .env.example to .env:copy .env.example .env


Edit .env with your settings (e.g., Discord token, Meshtastic port, channel/role IDs):BOT_TOKEN=your_discord_bot_token
GUILD_ID=your_discord_server_id
MESHTASTIC_CHANNEL_ID=channel_id_for_messages
MESHTASTIC_NODE_CHANNEL_ID=channel_id_for_node_events
ADMIN_ROLE_ID=admin_role_id
NODE_OWNER_ROLE_ID=node_owner_role_id
MESHTASTIC_PORT=COM3
ADMIN_LOG_CHANNEL_ID=channel_id_for_logs




Run the Bot:
python bot.py


The bot will connect to Discord and the Meshtastic device, logging events to bot.log and the admin channel.



📚 Usage

Invite the Bot:

Add the bot to your Discord server using an invite link from the Discord Developer Portal.
Ensure it has permissions to send messages, embeds, reactions, and manage roles.


Run Commands:

Use /setup to start the interactive wizard for new users.
Try /help to see all available commands in a formatted embed.
Example: /nodeinfo !abc123 to view details of a node with ID !abc123.


Interact with Meshtastic:

Send messages via your Meshtastic device to see them appear in the configured Discord channel.
Claim nodes with /claimnode and follow the DM instructions to send a code via Meshtastic.



🔧 Commands



Command
Description
Admin Only



/setup
Start the interactive setup wizard
No


/help
Show all available commands
No


/meshtastic_status
Show node and network status
No


/claimnode
Claim a Meshtastic node with a code
No


/releasenode
Release ownership of a node
No


/ownednodes
List your claimed nodes
No


/nodeinfo <node_id>
Get details of a specific node
No


/filtermessages [node_id] [owner]
Filter message logs
No


/addnode <node_id> <user>
Assign a node to a user
Yes


/removenode <node_id>
Remove a node’s ownership
Yes


/ack <node_id> <message> [channel]
Send a message to a node
Yes


/broadcast <message> [channel]
Broadcast to all nodes
Yes


/about
Show bot and node information
No


/reboot [seconds]
Reboot the connected node
Yes


/alert <message> <frequency> [to_discord] [to_mesh]
Schedule an announcement
Yes


/listalerts
List active alerts
No


/deletealert <index>
Delete an alert by index
Yes


/clearalerts
Clear all alerts
Yes


🐛 Troubleshooting

Bot not responding: Check bot.log and the admin channel for errors. Ensure .env variables are correct and the Meshtastic device is connected.
DM issues: Enable “Allow direct messages from server members” in Discord settings.
Meshtastic errors: Verify the serial port (e.g., COM3) and test with the Meshtastic CLI.
File permissions: Ensure JSON files (data.json, etc.) are writable.

📜 License
This project is licensed under the MIT License.
🙌 Contributing
Contributions are welcome! Feel free to open issues or submit pull requests on GitHub.

Built with 💻 by BOOK-Y0D4