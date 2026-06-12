import socket
import ssl
import logging

# Configure basic logging early so we can log monkeypatch registration
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Force IPv4 DNS resolution to prevent ConnectionResetError / failure Routing IPv6 on Hugging Face Spaces
orig_getaddrinfo = socket.getaddrinfo
def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = getaddrinfo_ipv4

# Monkeypatch aiohttp to enforce IPv4, disable keep-alive (force_close) to prevent ConnectionResetError
# due to Cloudflare connection dropping / idle socket reuse issues on Hugging Face Spaces / Python 3.13.
try:
    import aiohttp
    orig_connector_init = aiohttp.TCPConnector.__init__
    def custom_connector_init(self, *args, **kwargs):
        kwargs['family'] = socket.AF_INET
        kwargs['force_close'] = True
        kwargs.pop('keepalive_timeout', None)
        kwargs['enable_cleanup_closed'] = True
        orig_connector_init(self, *args, **kwargs)
    aiohttp.TCPConnector.__init__ = custom_connector_init
    logging.info("Successfully registered custom aiohttp.TCPConnector monkeypatch in app.py.")
except Exception as e:
    logging.error(f"Failed to register custom aiohttp.TCPConnector monkeypatch: {e}")

import sys
import huggingface_hub

# HfFolder has been deprecated/removed in recent huggingface_hub versions.
# Under older versions of gradio it tries to import it; let's mock it if it's missing.
if not hasattr(huggingface_hub, "HfFolder"):
    class DummyHfFolder:
        @classmethod
        def get_token(cls):
            return None
        @classmethod
        def save_token(cls, token):
            pass
        @classmethod
        def delete_token(cls):
            pass
    huggingface_hub.HfFolder = DummyHfFolder

import os
import threading
import asyncio
import logging
import gradio as gr
from bot import bot, logger, TRANSLATIONS, FAMOUS_LANGUAGES, TIER_SYSTEM

# Define high-fidelity Gradio Theme and Stylesheet
CUSTOM_CSS = """
body, .gradio-container {
    background-color: #f1f5f9 !important;
}
.header-card {
    background: linear-gradient(135deg, #1e293b, #0f172a);
    color: white;
    padding: 2.5rem;
    border-radius: 1rem;
    box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
    margin-bottom: 2rem;
}
.header-card h1 {
    color: #38bdf8 !important;
    font-size: 2.25rem !important;
    font-weight: 800 !important;
    margin-bottom: 0.5rem !important;
}
.header-card p {
    color: #94a3b8 !important;
    font-size: 1.1rem !important;
}
.status-card {
    background: white;
    border: 1px solid #e2e8f0;
    box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1);
    padding: 1.5rem;
    border-radius: 0.75rem;
}
.action-btn {
    background-color: #0284c7 !important;
    color: white !important;
    border-radius: 0.5rem !important;
    font-weight: 600 !important;
    transition: all 0.2s;
}
.action-btn:hover {
    background-color: #0369a1 !important;
    transform: translateY(-1px);
}
.danger-btn {
    background-color: #ef4444 !important;
    color: white !important;
    border-radius: 0.5rem !important;
}
.log-terminal {
    background-color: #0f172a !important;
    color: #f1f5f9 !important;
    font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
    padding: 1.5rem !important;
    border-radius: 0.5rem !important;
    border: 1px solid #334155 !important;
}
.info-card {
    background-color: #f8fafc;
    border-left: 4px solid #0284c7;
    padding: 1rem;
    border-radius: 0 0.5rem 0.5rem 0;
}
"""

def get_bot_diagnostic_info():
    """
    Returns full diagnostic breakdown from live thread details.
    """
    token = os.getenv("DISCORD_TOKEN")
    status_markdown = ""
    
    if bot.is_ready():
        status_markdown += "### 🟢 System Status: **CONNECTED & ACTIVE**\n"
        status_markdown += f"- **Bot User Identity:** `{bot.user.name}#{bot.user.discriminator or '0000'}` (ID: `{bot.user.id}`)\n"
        status_markdown += f"- **API Latency Connection:** `{round(bot.latency * 1000, 2)} ms`\n"
        status_markdown += f"- **Joined Service Servers (Guilds):** `{len(bot.guilds)}` servers\n"
        
        guilds_list = []
        for g in bot.guilds:
            guilds_list.append(f"  - **{g.name}** (ID: `{g.id}` | Members: `{g.member_count}`)")
        if guilds_list:
            status_markdown += "\n**Active Server Registry:**\n" + "\n".join(guilds_list)
    else:
        status_markdown += "### 🟡 System Status: **AWAITING TOKEN / CONNECTING**\n"
        if not token:
            status_markdown += "⚠️ **Alert Details:** Private variable `DISCORD_TOKEN` is blank or undefined in your configuration environment! Set it to authorize connecting to Discord servers.\n"
        else:
            status_markdown += "- **Token Authorization:** Configured securely. Background connection loop has been scheduled and is actively negotiating socket handshakes!\n"
        status_markdown += "- **Active Connections Status:** Offline (No bot object active or logged in)."
        
    return status_markdown

def trigger_admin_reconstruct_sync():
    """
    Initiates server synchronization by safely submitting the request to background thread's loop.
    """
    if not bot.is_ready():
        return "❌ Sync Aborted: Bot is offline. Please resolve DISCORD_TOKEN configuration and try again."
        
    async def task():
        from bot import execute_server_sync
        guilds_synced = []
        for guild in bot.guilds:
            await execute_server_sync(guild)
            guilds_synced.append(guild.name)
        if guilds_synced:
            return f"✅ Reconstructed categories, synced permissions, and repaired missing subchannels on servers: {', '.join(guilds_synced)}"
        return "ℹ️ Synchronization triggered, but the bot hasn't joined any guilds yet to execute actions on."
        
    try:
        future = asyncio.run_coroutine_threadsafe(task(), bot.loop)
        return future.result(timeout=45)
    except Exception as e:
        logger.error(f"Gradio control manual sync exception: {e}", exc_info=True)
        return f"❌ Sync Failure: {str(e)}"

def read_prompt_template(filepath):
    if not os.path.exists(filepath):
        return f"Error: '{filepath}' could not be located in this project container."
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

def write_prompt_template_changes(filepath, new_content):
    if not os.path.exists(filepath):
        return f"❌ Target template file '{filepath}' is missing."
    if not new_content or not new_content.strip():
        return "❌ Operation blocked: Cannot overwrite with empty prompt instructions template."
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        return "✅ Success: Prompts instruction deck has been updated and compiled inside the server filesystem!"
    except Exception as e:
        return f"❌ File system save failed: {str(e)}"

def get_live_logging_stream():
    """
    Reads recent execution event cycles from bot.log
    """
    if not os.path.exists("bot.log"):
        return "Starting log engine... If you recently booted the bot, trigger a page reload or perform actions to spawn logs."
    try:
        with open("bot.log", "r", encoding="utf-8") as f:
            log_lines = f.readlines()
            return "".join(log_lines[-75:]) # Last 75 telemetry lines
    except Exception as e:
        return f"Failed fetching diagnostic terminal stream log: {e}"

def preview_localizations(language):
    """
    Extracts dynamic translation blocks for /set-profile UI components
    """
    from bot import TRANSLATIONS
    data = TRANSLATIONS.get(language, TRANSLATIONS["English"])
    
    preview_md = f"""### 🌐 Selected Language: **{language}**
This is how user form text labels, input descriptions, and instructions are rendered dynamically inside the native Discord screen:

- **Modal Dialog Title:** `{data['title']}`
- **Name Field Label:** `{data['name_l']}` *(Placeholder/Ex: `{data['name_p']}`)*
- **Gender & Age Label:** `{data['ga_l']}` *(Placeholder/Ex: `{data['ga_p']}`)*
- **Country Region Label:** `{data['country_l']}` *(Placeholder/Ex: `{data['country_p']}`)*
- **Occupation Profession Label:** `{data['occup_l']}` *(Placeholder/Ex: `{data['occup_p']}`)*
- **Favorite Learning Themes:** `{data['topics_l']}` *(Placeholder/Ex: `{data['topics_p']}`)*
"""
    return preview_md

# Build highly polished, responsive block layout interface
with gr.Blocks(title="Discord Arabic Bot Control Panel", css=CUSTOM_CSS, theme=gr.themes.Soft()) as demo:
    
    # 🌟 Elegant Top Header Card Block
    with gr.Column(elem_classes=["header-card"]):
        gr.Markdown("# 🤖 Discord Arabic Learning Bot Control Center")
        gr.Markdown("A unified high-fidelity diagnostics and developer operational cockpit to audit active bot thread instances, customize learning prompt blueprints, configure translation sets, and trace execution events.")
        
    with gr.Tabs():
        
        # TAB 1: Main Diagnostics Dashboard
        with gr.TabItem("📊 Bot Diagnostics"):
            gr.Markdown("### 📡 Live Engine Registry & Network Stats")
            with gr.Row():
                with gr.Column(scale=3):
                    diagnostics_viewer = gr.Markdown(value="Fetching real-time variables...")
                    refresh_stats_btn = gr.Button("🔄 Refresh Status Metrics", elem_classes=["action-btn"])
                with gr.Column(scale=2, elem_classes=["status-card"]):
                    gr.Markdown("### 🛠️ Server Architecture Enforcement")
                    gr.Markdown("Instantly verify and structural sync entire Discord guild layout patterns. This automatically scans categories, ensures correct permissions security protocols, and boots active text/voice systems.")
                    sync_trigger_btn = gr.Button("⚡ Trigger Server Reconstruction Sync", elem_classes=["action-btn"])
                    sync_status_logs = gr.Textbox(label="Sync Output Message Log", interactive=False, lines=3, placeholder="Awaiting trigger sync protocol execution...")
                    
            gr.Markdown("---")
            gr.Markdown("### 🗂️ Managed Channels & Tier Hierarchies")
            gr.Markdown("Below is the architecture roadmap built automatically per connected guild server:")
            
            with gr.Row():
                for tier in TIER_SYSTEM:
                    with gr.Column(min_width=240, elem_classes=["status-card"]):
                        gr.Markdown(f"### **{tier['category']}**")
                        gr.Markdown(f"🏆 *Unlock Role:* `{tier['role']}`")
                        gr.Markdown("**📝 Text channels:**")
                        for ch in tier['text_channels']:
                            gr.Markdown(f"  - `# {ch}`")
                        gr.Markdown("**🔊 Voice channels:**")
                        for ch in tier['voice_channels']:
                            gr.Markdown(f"  - `🔊 {ch}`")

        # TAB 2: Dynamic Modal Registration Localization Audit Tool
        with gr.TabItem("🌐 Localization & Translation Audit"):
            gr.Markdown("### 🧪 Discord Model Content Localizer Auditor")
            gr.Markdown("Our discord.py autogreeter includes language tracking for 40 different mother tongues. Use this module to dynamically view the parameters mapped to Discord Modal Fields as users run the `/set-profile` command.")
            
            with gr.Row():
                with gr.Column(scale=1):
                    lang_selectors = gr.Dropdown(choices=FAMOUS_LANGUAGES, value="English", label="Choose Language To Test Layouts")
                with gr.Column(scale=2):
                    translation_preview_card = gr.Markdown(value="Select language from left to query maps...")
                    
            lang_selectors.change(fn=preview_localizations, inputs=[lang_selectors], outputs=[translation_preview_card])

        # TAB 3: Advanced Prompt Content Manager (CMS)
        with gr.TabItem("📝 Prompt BLUEPRINT CMS"):
            gr.Markdown("### 📂 Learning Deck Prompt Blueprints Manager")
            gr.Markdown("Modify the instruction sets fed directly to the underlying Gemini conversational context whenever a user triggers Profile completion parameters.")
            
            with gr.Row():
                with gr.Column(scale=1):
                    file_selector = gr.Dropdown(
                        choices=["checkpoint1.txt", "checkpoint2.txt", "checkpoint3.txt", "checkpoint4.txt"],
                        value="checkpoint1.txt",
                        label="Select Blueprint File to Audit/Modify"
                    )
                    load_file_trigger_btn = gr.Button("🔍 Load Selected Blueprint")
                    save_file_trigger_btn = gr.Button("💾 Save Changes to Server File", elem_classes=["danger-btn"])
                    io_save_result_log = gr.Markdown(value="*Open a file to make edits...*")
                with gr.Column(scale=3):
                    blueprint_text_editor = gr.Textbox(
                        label="Blueprint Instruction Payload Editor", 
                        lines=18, 
                        max_lines=35,
                        interactive=True,
                        show_copy_button=True,
                        placeholder="Loading configuration bytes, please wait..."
                    )
                    
            # Interactivity Actions
            load_file_trigger_btn.click(fn=read_prompt_template, inputs=[file_selector], outputs=[blueprint_text_editor])
            save_file_trigger_btn.click(
                fn=write_prompt_template_changes, 
                inputs=[file_selector, blueprint_text_editor], 
                outputs=[io_save_result_log]
            )

        # TAB 4: Production Diagnostics Logs CLI
        with gr.TabItem("📋 Real-Time Server Console"):
            gr.Markdown("### 📟 Shell Event Telemetry Logs Monitor")
            gr.Markdown("Audit native runtime exceptions, socket loops connection handshakes, discord.py webhooks, and sync cycles below as they commit.")
            
            with gr.Row():
                with gr.Column(scale=4):
                    log_terminal_output = gr.Code(
                        value="Starting stream reader...", 
                        language="python", 
                        elem_classes=["log-terminal"], 
                        lines=15
                    )
                with gr.Column(scale=1):
                    manual_refresh_logs_btn = gr.Button("🔄 Refresh Stream Logs", elem_classes=["action-btn"])
                    
            manual_refresh_logs_btn.click(fn=get_live_logging_stream, outputs=[log_terminal_output])

        # TAB 5: DevOps Commands Instructions Reference
        with gr.TabItem("ℹ️ Slash Commands Reference Guide"):
            gr.Markdown("### 📚 Quick Configuration and Orchestration Guide")
            gr.Markdown("""
            Welcome to the operational manual for the **Discord Arabic Learning Server Auto-governance bot**. Below is an overview of the platform configuration layout.
            
            ### 🛡️ Active Discord Slash Commands Setup
            
            1. **`/sync_server` (Admin Only):**
               - **Purpose:** Restores categories, voice, and text layouts. Correctly enforces locked viewing policies on a server.
               - **Design Logic:** Scans the active guild for the specific category indices (`@checkpoint1`, `@checkpoint2`, etc.). If missing, it creates them. If present, it reviews and restores permission overwrites.
            
            2. **`/set-profile [language]`:**
               - **Purpose:** Initiates the customized training sequence using the user's Mother Tongue.
               - **Process Flow:** Automatically brings up an interactive localized Modal Form with translation matches across **40 global environments**.
               - **Outcome:** The database writes out profiles as customized standardized instruction cards, grants the associated `Checkpoint Passed` role, and DMs the corresponding prompting manuals directly to the user safely.
            
            3. **`/vibecheck`:**
               - **Purpose:** Dispatches checkpoint verification review alert signals to administrators.
               - **Benefit:** Notifies moderators that a user is fully prepared for their review instantly, streamlining server advancement workflows.
            
            ### ⚙️ Quick Troubleshooting Reference
            - **Permission Error exception:** If the bot fails to assign any roles or create channels, verify its role ranking order in Discord Settings. It **must** locate above target roles it is intended to assign or administer!
            - **Missing Direct Message Delivery:** Users must have 'Allow Direct Messages from Server Members' toggled ON inside their user privacy profiles for the bot to dispatch Prompt Template decks safely.
            """)
            
    # Page-load behaviors
    demo.load(fn=get_bot_diagnostic_info, outputs=[diagnostics_viewer])
    demo.load(fn=read_prompt_template, inputs=[file_selector], outputs=[blueprint_text_editor])
    demo.load(fn=get_live_logging_stream, outputs=[log_terminal_output])
    demo.load(fn=preview_localizations, inputs=[lang_selectors], outputs=[translation_preview_card])
    
    # Live Refresh bindings
    refresh_stats_btn.click(fn=get_bot_diagnostic_info, outputs=[diagnostics_viewer])
    sync_trigger_btn.click(fn=trigger_admin_reconstruct_sync, outputs=[sync_status_logs])

def run_discord_bot():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("🚨 DISCORD_TOKEN is missing from your Hugging Face Space secrets!")
        return
    
    logger.info("👾 Starting background Discord Bot client loop...")
    bot.run(token)

if __name__ == "__main__":
    # Launch Discord bot natively in its own background thread to prevent blocking
    bot_thread = threading.Thread(target=run_discord_bot, daemon=True)
    bot_thread.start()
    
    # Launch Gradio server on standard port, reading environmental overrides smoothly
    launch_port = int(os.getenv("PORT", 3000))
    logger.info(f"🚀 Starting Gradio web server on port {launch_port}...")
    demo.launch(server_name="0.0.0.0", server_port=launch_port)
