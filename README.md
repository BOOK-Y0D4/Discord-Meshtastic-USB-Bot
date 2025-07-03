# Meshtastic Discord Bot

A Discord bot for managing a Meshtastic mesh network, allowing users to claim nodes, send messages, and schedule alerts.

## Setup
- Install dependencies: `pip install discord.py python-dotenv meshtastic`
- Configure `.env` with required variables (see `.env.example`).
- Run: `python bot.py`

## Features
- Interactive setup wizard (`/setup`)
- Node management (`/claimnode`, `/releasenode`, `/nodeinfo`)
- Messaging and alerts (`/ack`, `/broadcast`, `/alert`)

## License
MIT License