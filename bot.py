import os
import asyncio
import logging
import discord
from discord.ext import commands
from discord import app_commands
import uvicorn
from fastapi import FastAPI

# Setup structured logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DiscordDevOps")

# ==========================================
# 🌐 FastAPI Health Check Service
# ==========================================
app = FastAPI()

@app.get("/")
async def health_check():
    """
    Hugging Face Spaces health check endpoint.
    Must listen on port 7860 to pass the container deployment health probe.
    """
    return {
        "status": "healthy",
        "bot": "running"
    }

# ==========================================
# 🛠️ Discord Tier Structure Configuration
# ==========================================
TIER_SYSTEM = [
    {
        "category": "@checkpoint1",
        "role": "Checkpoint 1 Passed",
        "text_channels": ["أكتب"],
        "voice_channels": ["تحدث1", "تحدث2", "تحدث3"]
    },
    {
        "category": "@checkpoint2",
        "role": "Checkpoint 2 Passed",
        "text_channels": ["أكتب"],
        "voice_channels": ["تحدث1", "تحدث2", "تحدث3"]
    },
    {
        "category": "@checkpoint3",
        "role": "Checkpoint 3 Passed",
        "text_channels": ["أكتب"],
        "voice_channels": ["تحدث1", "تحدث2", "تحدث3"]
    },
    {
        "category": "@checkpoint4",
        "role": "Alumni",
        "text_channels": ["أكتب"],
        "voice_channels": ["تحدث1", "تحدث2", "تحدث3"]
    }
]

class ManagedTierBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.guild_messages = True
        intents.members = True   # Useful for managing roles
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        logger.info("Registering application commands...")
        await self.tree.sync()
        logger.info("Synced Slash Command tree globally.")

bot = ManagedTierBot()

async def sync_guild_layout(guild: discord.Guild):
    """
    Ensures categories, text/voice channels, roles and permission overwrites
    are created exactly down to the character matching to prevent duplicates
    and enforce security.
    """
    logger.info(f"Syncing architecture for Guild: {guild.name} (ID: {guild.id})")
    
    for tier in TIER_SYSTEM:
        category_name = tier["category"]
        role_name = tier["role"]
        
        # 1. Ensure associated role exists
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            try:
                role = await guild.create_role(
                    name=role_name,
                    reason="Automatically created by Tier sync engine"
                )
                logger.info(f"Created missing role: '{role_name}'")
            except Exception as e:
                logger.error(f"Failed to create role '{role_name}': {e}")
                continue
        else:
            logger.info(f"Role '{role_name}' already exists.")

        # 2. Structure exact Privacy Overwrites on the Category Level
        # - @everyone: No view permissions (view_channel=False)
        # - Associated Role: Can View, write messages & connect (view_channel=True, send_messages=True, connect=True)
        # - Bot (guild.me): Needs to retain view and management rights
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                connect=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                manage_channels=True,
                manage_roles=True,
                send_messages=True,
                connect=True
            )
        }

        # 3. Ensure Category exists
        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            try:
                category = await guild.create_category(
                    name=category_name,
                    overwrites=overwrites,
                    reason="Created missing Tier category with secure permissions"
                )
                logger.info(f"Created category: '{category_name}' with strict permission overwrites.")
            except Exception as e:
                logger.error(f"Failed to create category '{category_name}': {e}")
                continue
        else:
            # Sync / enforce overwrites on existing category to avoid drift
            try:
                await category.edit(overwrites=overwrites)
                logger.info(f"Verified category '{category_name}' and updated overwrites.")
            except Exception as e:
                logger.error(f"Failed to update overwrites on '{category_name}': {e}")

        # 4. Sync Text Channels (أكتب)
        for text_chan_name in tier["text_channels"]:
            text_chan = discord.utils.get(category.text_channels, name=text_chan_name)
            if not text_chan:
                try:
                    await category.create_text_channel(
                        name=text_chan_name,
                        reason="Created missing Tier text channel"
                    )
                    logger.info(f"  Created text channel: '#{text_chan_name}' under '{category_name}'")
                except Exception as e:
                    logger.error(f"  Failed to create text channel '{text_chan_name}': {e}")
            else:
                # Force synchronization of permissions with category inheritance
                try:
                    await text_chan.edit(sync_permissions=True)
                    logger.info(f"  Synced text channel: '#{text_chan_name}' permissions.")
                except Exception as e:
                    logger.error(f"  Failed to sync permissions for '{text_chan_name}': {e}")

        # 5. Sync Voice Channels (تحدث1, تحدث2, تحدث3)
        for voice_chan_name in tier["voice_channels"]:
            voice_chan = discord.utils.get(category.voice_channels, name=voice_chan_name)
            if not voice_chan:
                try:
                    await category.create_voice_channel(
                        name=voice_chan_name,
                        reason="Created missing Tier voice channel"
                    )
                    logger.info(f"  Created voice channel: '🔊 {voice_chan_name}' under '{category_name}'")
                except Exception as e:
                    logger.error(f"  Failed to create voice channel '{voice_chan_name}': {e}")
            else:
                # Force synchronization of permissions with category inheritance
                try:
                    await voice_chan.edit(sync_permissions=True)
                    logger.info(f"  Synced voice channel: '{voice_chan_name}' permissions.")
                except Exception as e:
                    logger.error(f"  Failed to sync permissions for '{voice_chan_name}': {e}")

# ==========================================
# 🤖 Discord Event Handlers
# ==========================================
@bot.event
async def on_ready():
    logger.info(f"🤖 Bot client connected to Gateway. Interfacing as Account: {bot.user.name} (ID: {bot.user.id})")
    for guild in bot.guilds:
        try:
            await sync_guild_layout(guild)
        except Exception as e:
            logger.error(f"Error during automatic boot synchronizer for Guild {guild.name}: {e}")

# ==========================================
# 🛠️ Admins Slash Commands
# ==========================================
@bot.tree.command(name="sync_server", description="Synchronizes and repairs the tier category structure and locks permissions.")
@app_commands.default_permissions(administrator=True)
async def sync_server_command(interaction: discord.Interaction):
    """
    Force verification/synchronization on demand.
    Requires server 'Administrator' permission privileges.
    """
    await interaction.response.defer(ephemeral=True)
    try:
        await sync_guild_layout(interaction.guild)
        await interaction.followup.send(
            "🏆 **Server Synchronized Successfully!** Verified and managed checkpoint roles, categories, and channels.",
            ephemeral=True
        )
    except Exception as e:
        logger.error(f"Manual sync requested by user failed: {e}")
        await interaction.followup.send(
            f"❌ **Synchronization encountered fatal error:** `{e}`",
            ephemeral=True
        )

# ==========================================
# 🚀 Multithreaded Async Process Execution
# ==========================================
async def main():
    discord_token = os.getenv("DISCORD_TOKEN")
    
    if not discord_token:
        logger.critical("🚨 DISCORD_TOKEN is not defined in environments variables!")
        logger.warning("The bot will remain inactive, but FastAPI will boot to maintain Hugging Face Space health check validity.")

    # Concurrently launch FastAPI using uvicorn on Host 0.0.0.0 and Port 7860
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=7860,
        log_level="info",
        use_colors=True
    )
    server = uvicorn.Server(config)
    
    # Run both the web service and the discord library bot client in parallel inside ASGI loop
    if discord_token:
        # discord.py library has a .start() method which acts as an async coroutine
        # we gather both tasks so they run concurrently on python event loop
        await asyncio.gather(
            server.serve(),
            bot.start(discord_token)
        )
    else:
        # Keep FastAPI alive alone to prevent Container crash loop in web dashboard
        await server.serve()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("DevOps Suite shutdown gracefully.")
