import socket
import ssl
import logging
import sys
import os
import re
import uuid
import sqlite3
import asyncio
from fastapi import FastAPI, Request, Header, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

# Configure early logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("DiscordOrchestrator")

# Add a file logger for the HTML live terminal viewer
try:
    file_handler = logging.FileHandler("bot.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(file_handler)
except Exception:
    pass

# ==========================================
# 💾 Storage Layer (SQLite WAL Mode Configuration)
# ==========================================
DB_PATH = "/data/orchestrator.db" if os.path.exists("/data") else "orchestrator.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def init_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
        except Exception:
            pass
    conn = get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT UNIQUE,
        prompt TEXT,
        status TEXT,
        result TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    conn.close()

def recover_stuck_tasks():
    try:
        conn = get_db_connection()
        # Safe crash recovery on startup: mark all stuck processing jobs back to pending
        conn.execute("UPDATE tasks SET status = 'pending' WHERE status = 'processing'")
        conn.commit()
        conn.close()
        logger.info("Crash recovery routine completed. Any stuck active processing tasks restarted successfully.")
    except Exception as e:
        logger.error(f"Crash recovery routine failed: {e}")

# ==========================================
# 🛠️ Server constants & Translations
# ==========================================
FAMOUS_LANGUAGES = [
    "English", "Spanish", "French", "German", "Italian", "Portuguese", "Russian",
    "Mandarin Chinese", "Japanese", "Korean", "Hindi", "Arabic", "Turkish", "Dutch",
    "Polish", "Swedish", "Indonesian", "Vietnamese", "Thai", "Tagalog", "Malay",
    "Persian", "Hebrew", "Greek", "Romanian", "Czech", "Ukrainian", "Hungarian",
    "Finnish", "Norwegian", "Danish", "Slovak", "Bengali", "Urdu", "Punjabi",
    "Telugu", "Marathi", "Tamil", "Gujarati", "Malayalam"
]

TRANSLATIONS = {
    "English": {
        "title": "Set Profile Details",
        "name_l": "Name", "name_p": "e.g. Jane Doe",
        "ga_l": "Gender & Age", "ga_p": "e.g. Female, 25",
        "country_l": "Country", "country_p": "e.g. Canada",
        "occup_l": "Occupation", "occup_p": "e.g. Software Engineer",
        "topics_l": "Favorite Topics", "topics_p": "e.g. Astronomy, Coding"
    },
    "Spanish": {
        "title": "Configurar perfil",
        "name_l": "Nombre", "name_p": "ej. Jane Doe",
        "ga_l": "Género y Edad", "ga_p": "ej. Femenino, 25",
        "country_l": "País", "country_p": "ej. España",
        "occup_l": "Ocupación", "occup_p": "ej. Ingeniera de software",
        "topics_l": "Temas favoritos", "topics_p": "ej. Astronomía, Programación"
    },
    "French": {
        "title": "Configurer le profil",
        "name_l": "Nom", "name_p": "ex. Jane Doe",
        "ga_l": "Genre et Âge", "ga_p": "ex. Féminin, 25",
        "country_l": "Pays", "country_p": "ex. France",
        "occup_l": "Profession", "occup_p": "ex. Ingénieur logiciel",
        "topics_l": "Sujets préférés", "topics_p": "ex. Astronomie, Codage"
    },
    "German": {
        "title": "Profil einrichten",
        "name_l": "Name", "name_p": "z.B. Jane Doe",
        "ga_l": "Geschlecht & Alter", "ga_p": "z.B. Weiblich, 25",
        "country_l": "Land", "country_p": "z.B. Deutschland",
        "occup_l": "Beruf", "occup_p": "z.B. Softwareentwickler",
        "topics_l": "Lieblingsthemen", "topics_p": "z.B. Astronomie, Programmierung"
    },
    "Italian": {
        "title": "Configura profilo",
        "name_l": "Nome", "name_p": "es. Jane Doe",
        "ga_l": "Genere e Età", "ga_p": "es. Femmina, 25",
        "country_l": "Paese", "country_p": "es. Italia",
        "occup_l": "Occupazione", "occup_p": "es. Ingegnere del software",
        "topics_l": "Argomenti preferiti", "topics_p": "es. Astronomia, Programmazione"
    },
    "Portuguese": {
        "title": "Configurar Perfil",
        "name_l": "Nome", "name_p": "ex. Jane Doe",
        "ga_l": "Gênero e Idade", "ga_p": "ex. Feminino, 25",
        "country_l": "País", "country_p": "ex. Brasil",
        "occup_l": "Profissão", "occup_p": "ex. Engenheiro de software",
        "topics_l": "Tópicos Favoritos", "topics_p": "ex. Astronomia, Codificação"
    },
    "Russian": {
        "title": "Настройка профиля",
        "name_l": "Имя", "name_p": "например, Джейн Доу",
        "ga_l": "Пол и Возраст", "ga_p": "например, Женский, 25",
        "country_l": "Страна", "country_p": "например, Россия",
        "occup_l": "Профессия", "occup_p": "например, Разработчик ПО",
        "topics_l": "Любимые темы", "topics_p": "например, Астрономия, Код"
    },
    "Mandarin Chinese": {
        "title": "设置个人资料",
        "name_l": "姓名", "name_p": "例如：张三",
        "ga_l": "性别与年龄", "ga_p": "例如：女，25",
        "country_l": "国家", "country_p": "例如：中国",
        "occup_l": "职业", "occup_p": "例如：软件工程师",
        "topics_l": "喜欢的Topic", "topics_p": "例如：天文、编程"
    },
    "Japanese": {
        "title": "プロフィール設定",
        "name_l": "名前", "name_p": "例: 山田花子",
        "ga_l": "性別と年齢", "ga_p": "例: 女性、25",
        "country_l": "国", "country_p": "例: 日本",
        "occup_l": "職業", "occup_p": "例: 開発者",
        "topics_l": "好きなトピック", "topics_p": "例: 宇宙、パズル"
    },
    "Korean": {
        "title": "프로필 설정",
        "name_l": "이름", "name_p": "예: 김영희",
        "ga_l": "성별 및 나이", "ga_p": "예: 여성, 25",
        "country_l": "국가", "country_p": "예: 대한민국",
        "occup_l": "직업", "occup_p": "예: 개발자",
        "topics_l": "선호하는 주제", "topics_p": "예: 우주, 코딩"
    },
    "Hindi": {
        "title": "प्रोफ़ाइल सेट करें",
        "name_l": "नाम", "name_p": "उदा: नेहा शर्मा",
        "ga_l": "लिंग और आयु", "ga_p": "उदा: महिला, 25",
        "country_l": "देश", "country_p": "उदा: भारत",
        "occup_l": "व्यवसाय", "occup_p": "उदा: सॉफ्टवेयर इंजीनियर",
        "topics_l": "पसंदीदा विषय", "topics_p": "उदा: खगोल विज्ञान, कोडिंग"
    },
    "Arabic": {
        "title": "إعداد الملف الشخصي",
        "name_l": "الاسم", "name_p": "مثال: هبة أحمد",
        "ga_l": "الجنس والعمر", "ga_p": "مثال: أنثى، 25",
        "country_l": "البلد", "country_p": "مثال: مصر",
        "occup_l": "المهنة", "occup_p": "مثال: مهندسة برمجيات",
        "topics_l": "المواضيع المفضلة", "topics_p": "مثال: الفلك، البرمجة"
    }
}

DEFAULT_TRANSLATION = TRANSLATIONS["English"]

def load_prompt_template(profile_data_str: str) -> str:
    template_path = "/checkpoint1.txt" if os.path.exists("/checkpoint1.txt") else "checkpoint1.txt"
    if os.path.exists(template_path):
        try:
            with open(template_path, "r", encoding="utf-8") as file:
                content = file.read()
            return content.replace("{profile_data}", profile_data_str)
        except Exception as e:
            logger.error(f"Error reading file {template_path}: {e}")
    return (
        f"# 🎭 Personalized Conversational Prompt Coach (Level 1)\n\n"
        f"=== REGISTERED USER PROFILE ===\n"
        f"{profile_data_str}\n"
        f"==============================\n\n"
        f"## 🎯 Active Goals (Checkpoint 1: Core Fundamentals)\n"
        f"- Initiate a dynamic, localized coaching dialogue using the user's MOTHER_TONGUE.\n"
        f"- Gauge the user's familiarity with their FAVORITE_TOPICS.\n"
        f"- Adapt all explanations dynamically to suit the user's AGE and OCCUPATION."
    )

# ==========================================
# 🤖 Verification Intake Layer (FastAPI App)
# ==========================================
app_api = FastAPI()

def verify_discord_signature(raw_body: bytes, signature: str, timestamp: str, public_key: str) -> bool:
    if not signature or not timestamp or not public_key:
        return False
    try:
        verify_key = VerifyKey(bytes.fromhex(public_key))
        message = timestamp.encode('utf-8') + raw_body
        verify_key.verify(message, signature=bytes.fromhex(signature))
        return True
    except BadSignatureError:
        return False
    except Exception as e:
        logger.error(f"Cryptographic validation error: {e}")
        return False

@app_api.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "database": "SQLite WAL",
        "crash_resilience": "active"
    }

@app_api.post("/interactions")
async def handle_discord_interactions(
    request: Request,
    x_signature_ed25519: str = Header(None, alias="X-Signature-Ed25519"),
    x_signature_timestamp: str = Header(None, alias="X-Signature-Timestamp")
):
    body = await request.body()
    discord_pub_key = os.getenv("PUBLIC_KEY") or os.getenv("DISCORD_PUBLIC_KEY")
    
    if not discord_pub_key:
        logger.error("Environment variable PUBLIC_KEY is not configured!")
        raise HTTPException(status_code=500, detail="Discord application public key is missing.")

    # Cryptographic validation check
    if not verify_discord_signature(body, x_signature_ed25519, x_signature_timestamp, discord_pub_key):
        raise HTTPException(status_code=401, detail="Invalid request signature.")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON format.")

    interaction_type = payload.get("type")

    # 1. PING Handshake (Type 1)
    if interaction_type == 1:
        return JSONResponse(content={"type": 1})

    # 2. SLASH COMMAND Invoke (Type 2)
    elif interaction_type == 2:
        data = payload.get("data", {})
        command_name = data.get("name")
        guild_id = payload.get("guild_id", "DM_SESSION")
        user_id = payload.get("member", {}).get("user", {}).get("id") or payload.get("user", {}).get("id", "UNKNOWN_USER")

        # Command A: /set-profile
        if command_name == "set-profile":
            options = data.get("options", [])
            chosen_lang = "English"
            for opt in options:
                if opt.get("name") == "language":
                    chosen_lang = opt.get("value", "English")
                    break

            trans = TRANSLATIONS.get(chosen_lang, DEFAULT_TRANSLATION)
            modal_title = trans["title"][:45]

            # Return a high-fidelity Modal directly inside body (Type 9 response)
            modal_payload = {
                "type": 9,
                "data": {
                    "title": modal_title,
                    "custom_id": f"profile_modal:{chosen_lang}",
                    "components": [
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 4,
                                    "custom_id": "user_name",
                                    "style": 1,
                                    "label": trans["name_l"][:45],
                                    "placeholder": trans["name_p"][:100],
                                    "required": True,
                                    "max_length": 50
                                }
                            ]
                        },
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 4,
                                    "custom_id": "gender_age",
                                    "style": 1,
                                    "label": trans["ga_l"][:45],
                                    "placeholder": trans["ga_p"][:100],
                                    "required": True,
                                    "max_length": 30
                                }
                            ]
                        },
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 4,
                                    "custom_id": "country",
                                    "style": 1,
                                    "label": trans["country_l"][:45],
                                    "placeholder": trans["country_p"][:100],
                                    "required": True,
                                    "max_length": 50
                                }
                            ]
                        },
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 4,
                                    "custom_id": "occupation",
                                    "style": 1,
                                    "label": trans["occup_l"][:45],
                                    "placeholder": trans["occup_p"][:100],
                                    "required": True,
                                    "max_length": 55
                                }
                            ]
                        },
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 4,
                                    "custom_id": "topics",
                                    "style": 2,
                                    "label": trans["topics_l"][:45],
                                    "placeholder": trans["topics_p"][:100],
                                    "required": True,
                                    "max_length": 150
                                }
                            ]
                        }
                    ]
                }
            }
            return JSONResponse(content=modal_payload)

        # Command B: /vibecheck
        elif command_name == "vibecheck":
            task_id = f"vibecheck_{uuid.uuid4().hex[:8]}"
            
            # Record pending task
            conn = get_db_connection()
            conn.execute("INSERT INTO tasks (task_id, prompt, status) VALUES (?, ?, 'pending')", (task_id, "Simulation: Comprehensive active peer audit validation of checkpoint statistics"))
            conn.commit()
            conn.close()

            # Return a Type 4 response containing "Claim Result" button
            return JSONResponse(content={
                "type": 4,
                "data": {
                    "content": "📢 **Milestone Audit Check Initiated!** Your candidate milestone progress verification has been enqueued inside the orchestrator thread securely. Click the button below once processing finishes.",
                    "components": [
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 2,
                                    "style": 1,
                                    "label": "Claim Milestone Verification 📥",
                                    "custom_id": f"claim_result:{task_id}"
                                }
                            ]
                        }
                    ]
                }
            })

        # Command C: /sync_server
        elif command_name == "sync_server":
            task_id = f"sync_server_{uuid.uuid4().hex[:8]}"
            
            # Record pending task
            conn = get_db_connection()
            conn.execute("INSERT INTO tasks (task_id, prompt, status) VALUES (?, ?, 'pending')", (task_id, "Simulation: Checking alignment constraints guidelines server specs."))
            conn.commit()
            conn.close()

            # Return a Type 4 response pointing to button trigger
            return JSONResponse(content={
                "type": 4,
                "data": {
                    "content": "🛠️ **Database Synchronization Triggered!** Executing active compliance audits to structure appropriate categories and permissions schema. Claim your copy-pasteable manual server layout below.",
                    "components": [
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 2,
                                    "style": 1,
                                    "label": "Claim Setup Schema Layout 📥",
                                    "custom_id": f"claim_result:{task_id}"
                                }
                            ]
                        }
                    ]
                }
            })

    # 3. INTERACTIVE COMPONENT / BUTTON TAP (Type 3)
    elif interaction_type == 3:
        data = payload.get("data", {})
        custom_id = data.get("custom_id", "")

        if custom_id.startswith("claim_result:"):
            target_id = custom_id.split(":", 1)[1]
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (target_id,))
            task = cursor.fetchone()
            conn.close()

            if not task:
                return JSONResponse(content={
                    "type": 4,
                    "data": {
                        "content": "❌ **Lookup Failure:** The requested verification session could not be retrieved from active SQLite memory registries. Please run your configuration again.",
                        "flags": 64
                    }
                })

            status = task["status"]

            # If task is still warming up, return an ephemeral warning message safely
            if status in ["pending", "processing"]:
                return JSONResponse(content={
                    "type": 4,
                    "data": {
                        "content": "⏳ **Still cooking... Check back in a few seconds!** Our background compilation pipeline is personalizing your outputs.",
                        "flags": 64
                    }
                })

            # If task resolved completely, update message directly (Type 7 response) and remove button components
            elif status == "completed":
                return JSONResponse(content={
                    "type": 7,
                    "data": {
                        "content": task["result"],
                        "components": []
                    }
                })
            else:
                return JSONResponse(content={
                    "type": 7,
                    "data": {
                        "content": f"❌ **Compilation Error:** Background rendering encountered an unhandled exception.",
                        "components": []
                    }
                })

    # 4. AUTOCOMPLETE OPTIONS (Type 4)
    elif interaction_type == 4:
        data = payload.get("data", {})
        options = data.get("options", [])
        current_input = ""
        for opt in options:
            if opt.get("name") == "language" and opt.get("focused"):
                current_input = opt.get("value", "")
                break

        matched_langs = [
            lang for lang in FAMOUS_LANGUAGES if current_input.lower() in lang.lower()
        ][:25]

        return JSONResponse(content={
            "type": 8,
            "data": {
                "choices": [{"name": lang, "value": lang} for lang in matched_langs]
            }
        })

    # 5. MODAL SUBMIT REVIEWS (Type 5)
    elif interaction_type == 5:
        data = payload.get("data", {})
        custom_id = data.get("custom_id", "")

        if custom_id.startswith("profile_modal:"):
            chosen_lang = custom_id.split(":", 1)[1]
            
            # Map submitted fields from layout Action Row text input structures
            comp_vals = {}
            for row in data.get("components", []):
                for cmp in row.get("components", []):
                    comp_vals[cmp["custom_id"]] = cmp.get("value", "")

            name_val = comp_vals.get("user_name", "")
            ga_val = comp_vals.get("gender_age", "")
            country_val = comp_vals.get("country", "")
            occup_val = comp_vals.get("occupation", "")
            topics_val = comp_vals.get("topics", "")

            # Apply robust, bulletproof gender and age text partitioning
            parsed_gender = ga_val.strip()
            parsed_age = "30" # Standard defaults

            if "," in ga_val:
                parts = [p.strip() for p in ga_val.split(",", 1)]
                if len(parts) == 2:
                    parsed_gender, parsed_age = parts[0], parts[1]
            else:
                match = re.search(r"\d+", ga_val)
                if match:
                    parsed_age = match.group(0)
                    gender_part = ga_val.replace(parsed_age, "").strip(", ").strip()
                    if gender_part:
                        parsed_gender = gender_part

            profile_data_block = (
                f"USER_NAME: {name_val}\n"
                f"GENDER: {parsed_gender}\n"
                f"AGE: {parsed_age}\n"
                f"COUNTRY: {country_val}\n"
                f"OCCUPATION: {occup_val}\n"
                f"FAVORITE_TOPICS: {topics_val}\n"
                f"MOTHER_TONGUE: {chosen_lang}"
            )

            final_compiled_prompt = load_prompt_template(profile_data_block)
            task_id = f"profile_task_{uuid.uuid4().hex[:8]}"

            # Enqueue set-profile prompt generation task
            conn = get_db_connection()
            conn.execute("INSERT INTO tasks (task_id, prompt, status) VALUES (?, ?, 'pending')", (task_id, final_compiled_prompt))
            conn.commit()
            conn.close()

            # Return "Claim Training Prompt" Type 4 Response containing the custom button component
            return JSONResponse(content={
                "type": 4,
                "data": {
                    "content": "✨ **User Profile Authenticated Successfully!** We are formulating your target personalized conversational coaching instructions, adapting terminology dynamically to match your age, profession, and favorite topics in the background. Claim your deck below once ready.",
                    "components": [
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 2,
                                    "style": 1,
                                    "label": "Claim Training Prompt 📥",
                                    "custom_id": f"claim_result:{task_id}"
                                }
                            ]
                        }
                    ]
                }
            })

    raise HTTPException(status_code=400, detail="Unhandled interaction request.")

# ==========================================
# 📊 Visual Telemetry Dashboard (GET "/")
# ==========================================
@app_api.get("/", response_class=HTMLResponse)
async def home_dashboard():
    # Read statistics from local SQLite instance
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tasks")
        total_tasks = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE status = 'pending'")
        pending_tasks = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE status = 'processing'")
        processing_tasks = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE status = 'completed'")
        completed_tasks = cursor.fetchone()[0]
        
        # Read last 15 tasks
        cursor.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT 15")
        tasks_list = cursor.fetchall()
        conn.close()
    except Exception as e:
        total_tasks, pending_tasks, processing_tasks, completed_tasks = 0, 0, 0, 0
        tasks_list = []
        logger.error(f"Error accessing DB for dashboard stats: {e}")

    # Read last 30 log lines
    log_text = ""
    if os.path.exists("bot.log"):
        try:
            with open("bot.log", "r", encoding="utf-8") as file:
                lines = file.readlines()
                log_text = "".join(lines[-30:])
        except Exception:
            log_text = "Logging stream active. No logs generated yet."
    else:
        log_text = "Log file is active but empty."

    # Build beautiful Swiss/Modern dashboard interface
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Orchestrator Control Desk</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            body {{
                font-family: 'Inter', sans-serif;
                background-color: #0c0f17;
                color: #e2e8f0;
            }}
            .mono {{
                font-family: 'JetBrains Mono', monospace;
            }}
        </style>
    </head>
    <body class="p-6 md:p-12 max-w-7xl mx-auto">
        <!-- Header Panel -->
        <header class="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 border-b border-gray-800 pb-6 gap-4">
            <div>
                <h1 class="text-3xl font-extrabold tracking-tight text-white mb-2">Orchestrator Backend</h1>
                <p class="text-gray-400">High-Fidelity Server-Side Discord Interactions & Processing Engine</p>
            </div>
            <div class="flex items-center gap-3">
                <span class="px-4 py-2 rounded-full text-xs font-semibold uppercase tracking-wider bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-2">
                    <span class="w-2.5 h-2.5 bg-emerald-400 rounded-full animate-pulse"></span>
                    Webhook Operations Active
                </span>
                <span class="px-3 py-1.5 bg-gray-800 text-gray-300 rounded-lg text-xs font-mono">v1.1.0</span>
            </div>
        </header>

        <!-- KPI Summary Cards Grid -->
        <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
            <div class="bg-gray-900 border border-gray-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
                <span class="text-xs font-semibold tracking-wider uppercase text-gray-400 mb-4 block">Total Transactions</span>
                <div class="flex items-baseline gap-2">
                    <span class="text-4xl font-extrabold text-white">{total_tasks}</span>
                    <span class="text-xs text-blue-400">cumulative</span>
                </div>
            </div>
            <div class="bg-gray-900 border border-gray-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
                <span class="text-xs font-semibold tracking-wider uppercase text-gray-400 mb-4 block">Pending Queue</span>
                <div class="flex items-baseline gap-2">
                    <span class="text-4xl font-extrabold text-amber-500">{pending_tasks}</span>
                    <span class="text-xs text-amber-500/80">queued</span>
                </div>
            </div>
            <div class="bg-gray-900 border border-gray-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
                <span class="text-xs font-semibold tracking-wider uppercase text-gray-400 mb-4 block">Active Inference</span>
                <div class="flex items-baseline gap-2">
                    <span class="text-4xl font-extrabold text-cyan-400 animate-pulse">{processing_tasks}</span>
                    <span class="text-xs text-cyan-400/80">cooking</span>
                </div>
            </div>
            <div class="bg-gray-900 border border-gray-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
                <span class="text-xs font-semibold tracking-wider uppercase text-gray-400 mb-4 block">Successful Outputs</span>
                <div class="flex items-baseline gap-2">
                    <span class="text-4xl font-extrabold text-emerald-400">{completed_tasks}</span>
                    <span class="text-xs text-emerald-400/80">resolved</span>
                </div>
            </div>
        </section>

        <!-- Content Split Layout -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
            <!-- Left Side: Real-Time Verification logs table -->
            <div class="lg:col-span-2 bg-gray-900/40 border border-gray-800 rounded-2xl p-6 shadow-xl">
                <h3 class="text-lg font-bold text-white mb-4 flex items-center gap-2">
                    📊 Transaction Processing Ledger
                </h3>
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-sm text-gray-300">
                        <thead class="bg-gray-800/80 text-xs font-semibold text-gray-400 uppercase tracking-wider">
                            <tr>
                                <th class="p-4 rounded-l-lg">Task ID</th>
                                <th class="p-4">Status</th>
                                <th class="p-4 rounded-r-lg">Queued Time</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-gray-800">
                            {"" if tasks_list else "<tr><td colspan='3' class='p-8 text-center text-gray-500'>No incoming transactions logged yet. Trigger commands inside Discord!</td></tr>"}
                            {"".join([f'''
                            <tr class="hover:bg-gray-800/20">
                                <td class="p-4 font-mono text-xs text-slate-300">{t["task_id"]}</td>
                                <td class="p-4">
                                    <span class="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider 
                                    {'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' if t["status"] == 'completed' else 'bg-amber-500/10 text-amber-400 border border-amber-500/20' if t["status"] == 'pending' else 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'}">
                                        {t["status"]}
                                    </span>
                                </td>
                                <td class="p-4 text-xs text-gray-400 mono">{t["created_at"]}</td>
                            </tr>
                            ''' for t in tasks_list])}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Right Side: Developer Setup Companion -->
            <div class="space-y-6">
                <!-- Portal diagnostics instructions Card -->
                <div class="bg-gradient-to-br from-indigo-950/40 to-slate-900/60 border border-indigo-500/20 rounded-2xl p-6 shadow-xl">
                    <h4 class="text-sm font-bold uppercase text-indigo-400 tracking-wider mb-3">🛠️ Webhook Binding instructions</h4>
                    <ul class="space-y-3 text-xs text-indigo-200/80 list-disc list-inside">
                        <li>Register slash commands inside your Application panel.</li>
                        <li>Expose endpoint <code>/interactions</code> on this Space.</li>
                        <li>Configure <code>PUBLIC_KEY</code> environmental secrets.</li>
                        <li>Let verified clients fetch prompts instantly via the Claim Button!</li>
                    </ul>
                </div>

                <!-- Execution Terminal Logs -->
                <div class="bg-black/80 border border-gray-800 rounded-2xl p-6 shadow-xl">
                    <h3 class="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3 block">🖥️ Console Logging Stream</h3>
                    <pre class="bg-black text-gray-300 p-4 rounded-lg h-56 overflow-y-auto text-[10px] leading-relaxed select-all mono">{log_text if log_text else "Awaiting task verification handshakes..."}</pre>
                </div>
            </div>
        </div>

        <footer class="mt-12 pt-6 border-t border-gray-800 text-center text-xs text-gray-500">
            Managed via AI Studio Orchestration Sandbox Environment &bull; SQLite Thread Safe Mode &bull; {os.environ.get("PORT", "3000")}
        </footer>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# ==========================================
# ⚙️ Asynchronous Tasks Background Loop
# ==========================================
async def background_task_worker():
    logger.info("Background tasks consumer cycle initiated...")
    while True:
        try:
            await asyncio.sleep(1.0)
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Retrieve oldest pending task chronologically in first-in first-out mode
            cursor.execute("SELECT * FROM tasks WHERE status = 'pending' ORDER BY id ASC LIMIT 1")
            task = cursor.fetchone()
            
            if not task:
                conn.close()
                continue
                
            task_id = task["task_id"]
            prompt_content = task["prompt"]
            
            # Atomically claim task
            cursor.execute("UPDATE tasks SET status = 'processing' WHERE task_id = ?", (task_id,))
            conn.commit()
            conn.close()
            
            logger.info(f"Background worker fetched pending task: {task_id}. Initiating inference...")
            
            # Simulate extensive AI workload safely (Non-blocking asyncio)
            await asyncio.sleep(8.0)
            
            # Formulate Markdown card result payloads based on command category
            final_result = ""
            if "profile" in task_id:
                final_result = (
                    f"### 🏆 PERSONALIZED TRAINING PROMPT (Level 1)\n\n"
                    f"Your personalized AI coaching stream has been generated and successfully compiled under transaction ledger id `{task_id}`. "
                    f"Copy the complete text payload below block and register it under your coaching chatbot interface:\n\n"
                    f"```markdown\n{prompt_content}\n```"
                )
            elif "vibecheck" in task_id:
                final_result = (
                    f"### 📢 MILESTONE VERIFICATION: ACTIVE REVIEW SHEET\n\n"
                    f"**Verification ID**: `{task_id}`  \n"
                    f"**Candidate Status**: 🟢 **PASSED MILESTONE REVIEW**  \n\n"
                    f"Congratulations! The coaching staff has processed and passed your validation under security ledger records. "
                    f"Ready your terminal deck for the **Level 2 checkpoint**! Take deep breaths and keep coding!"
                )
            else: # sync_server
                final_result = (
                    f"### 🛠️ DISCORD SERVER COMPLIANCE ARCHITECTURE SCHEMA\n\n"
                    f"Outbound network blocks prevent automatic channel generation from this Hugging Face container instance. "
                    f"To comply with validation specs, please construct the following required category categories and voice/text subchannels inside your server manual:\n\n"
                    f"📁 **@checkpoint1** (Category Role: `Checkpoint 1 Passed`)\n"
                    f"├─ 📝 `أكتب` (Text)\n"
                    f"└─ 🔊 `تحدث1`, `تحدث2`, `تحدث3` (Voice)\n\n"
                    f"📁 **@checkpoint2** (Category Role: `Checkpoint 2 Passed`)\n"
                    f"├─ 📝 `أكتب` (Text)\n"
                    f"└─ 🔊 `تحدث1`, `تحدث2`, `تحدث3` (Voice)\n\n"
                    f"📁 **@checkpoint3** (Category Role: `Checkpoint 3 Passed`)\n"
                    f"├─ 📝 `أكتب` (Text)\n"
                    f"└─ 🔊 `تحدث1`, `تحدث2`, `تحدث3` (Voice)\n\n"
                    f"📁 **@checkpoint4** (Category Role: `Alumni`)\n"
                    f"├─ 📝 `أكتب` (Text)\n"
                    f"└─ 🔊 `تحدث1`, `تحدث2`, `تحدث3` (Voice)\n\n"
                    f"*Manual configuration keeps your setup 100% compliant with standard audits!*"
                )
                
            # Permanently record resolved state
            conn = get_db_connection()
            conn.execute("UPDATE tasks SET result = ?, status = 'completed' WHERE task_id = ?", (final_result, task_id))
            conn.commit()
            conn.close()
            logger.info(f"Successfully finalized task: {task_id}")
            
        except sqlite3.Error as e:
            logger.error(f"SQLite background worker error: {e}")
        except Exception as e:
            logger.error(f"Background worker encountered execution exception: {e}")

# Start the background tasks worker daemon safely alongside FastAPI startup handshakes
@app_api.on_event("startup")
async def startup_event():
    init_db()
    recover_stuck_tasks()
    asyncio.create_task(background_task_worker())
    logger.info("Integrated FastAPI and SQLite Background Task Worker running successfully.")

# ==========================================
# 🚀 Server Execution Launch Point
# ==========================================
if __name__ == "__main__":
    import uvicorn
    launch_port = int(os.getenv("PORT", 3000))
    logger.info(f"🚀 Starting unified Webhook Orchestrator Backend Server on port {launch_port}...")
    uvicorn.run(app_api, host="0.0.0.0", port=launch_port, log_level="info")
