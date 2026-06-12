import os
import threading
import gradio as gr
from bot import bot, logger

# Set up clean professional Gradio Control Panel
with gr.Blocks(title="Discord Arabic Bot Control Panel") as demo:
    gr.Markdown("# 🤖 Discord Arabic Bot Control Panel")
    gr.Markdown("This Hugging Face Space runs your Discord Arabic learning bot in the background.")
    
    with gr.Group():
        gr.Markdown("## 🟢 System Status")
        status_box = gr.Markdown("### **Status:** Bot initialized, web health checks passing.")
    
    gr.Markdown("""
    ### 🛡️ Active Slash Commands:
    - `/sync_server` (Admin Only): Recreates and repairs category/channel structures and sets strict level permission overrides.
    - `/set-profile`: User profile setup workflow supporting 40 selectable languages with dynamic translated modals.
    - `/vibecheck`: Sends a private checkoff ping to teachers/mentors for level graduations.
    """)

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
    
    # Launch Gradio server on port 7860 to natively pass Hugging Face health probes
    demo.launch(server_name="0.0.0.0", server_port=7860)
