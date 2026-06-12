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

# Monkeypatch aiohttp to enforce IPv4, disable keep-alive (force_close) and disable strict SSL verification
# to prevent ConnectionResetError due to Cloudflare connection blocking / strict TLS renegotiation on Hugging Face Spaces.
try:
    import aiohttp
    orig_connector_init = aiohttp.TCPConnector.__init__
    def custom_connector_init(self, *args, **kwargs):
        kwargs['family'] = socket.AF_INET
        kwargs['force_close'] = True
        kwargs.pop('keepalive_timeout', None)
        kwargs['enable_cleanup_closed'] = True
        kwargs['ssl'] = False  # Disable strict certification checks to bypass Handshake ConnectionResetError
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
import re
import gradio as gr
import discord
from discord.ext import commands
from discord import app_commands
import uvicorn
from fastapi import FastAPI

# Configure robust production logging
logger = logging.getLogger("DiscordDevOps")

# Also add a file logger for live web monitoring in the dashboard
try:
    file_handler = logging.FileHandler("bot.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(file_handler)
except Exception as e:
    pass

# FastAPI health check setup
app_api = FastAPI()
@app_api.get("/")
async def health_check():
    return {
        "status": "healthy",
        "bot": "running"
    }

# ==========================================
# 🛠️ Server configuration templates
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

# Supported languages list for /set-profile autocompletion choices
FAMOUS_LANGUAGES = [
    "English", "Spanish", "French", "German", "Italian", "Portuguese", "Russian",
    "Mandarin Chinese", "Japanese", "Korean", "Hindi", "Arabic", "Turkish", "Dutch",
    "Polish", "Swedish", "Indonesian", "Vietnamese", "Thai", "Tagalog", "Malay",
    "Persian", "Hebrew", "Greek", "Romanian", "Czech", "Ukrainian", "Hungarian",
    "Finnish", "Norwegian", "Danish", "Slovak", "Bengali", "Urdu", "Punjabi",
    "Telugu", "Marathi", "Tamil", "Gujarati", "Malayalam"
]

# Detailed Translation dictionary for Modal configuration
# Maps exact dynamic titles, labels and placeholders based on selected Mother Tongue
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
    },
    "Turkish": {
        "title": "Profil Kurulumu",
        "name_l": "Ad", "name_p": "örn. Jane Doe",
        "ga_l": "Cinsiyet ve Yaş", "ga_p": "örn. Kadın, 25",
        "country_l": "Ülke", "country_p": "örn. Türkiye",
        "occup_l": "Meslek", "occup_p": "örn. Yazılım Mühendisi",
        "topics_l": "Favori Konular", "topics_p": "örn. Astronomi, Kodlama"
    },
    "Dutch": {
        "title": "Profiel Instellen",
        "name_l": "Naam", "name_p": "bijv. Jane Doe",
        "ga_l": "Geslacht & Leeftijd", "ga_p": "bijv. Vrouw, 25",
        "country_l": "Land", "country_p": "bijv. Nederland",
        "occup_l": "Beroep", "occup_p": "bijv. Softwareontwikkelaar",
        "topics_l": "Favoriete Onderwerpen", "topics_p": "bijv. Astronomie, Codering"
    },
    "Polish": {
        "title": "Skonfiguruj profil",
        "name_l": "Imię", "name_p": "np. Anna Kowalska",
        "ga_l": "Płeć i Wiek", "ga_p": "np. Kobieta, 25",
        "country_l": "Kraj", "country_p": "np. Polska",
        "occup_l": "Zawód", "occup_p": "np. Programista",
        "topics_l": "Ulubione tematy", "topics_p": "np. Astronomia, Kodowanie"
    },
    "Swedish": {
        "title": "Ställ in profil",
        "name_l": "Namn", "name_p": "t.ex. Jane Doe",
        "ga_l": "Kön & Ålder", "ga_p": "t.ex. Kvinna, 25",
        "country_l": "Land", "country_p": "t.ex. Sverige",
        "occup_l": "Yrke", "occup_p": "t.ex. Programvarutekniker",
        "topics_l": "Favoritämnen", "topics_p": "t.ex. Astronomi, Kodning"
    },
    "Indonesian": {
        "title": "Atur Profil",
        "name_l": "Nama", "name_p": "mis. Jane Doe",
        "ga_l": "Jenis Kelamin & Umur", "ga_p": "mis. Perempuan, 25",
        "country_l": "Negara", "country_p": "mis. Indonesia",
        "occup_l": "Pekerjaan", "occup_p": "mis. Insinyur Perangkat Lunak",
        "topics_l": "Topik Favorit", "topics_p": "mis. Astronomi, Pemrograman"
    },
    "Vietnamese": {
        "title": "Cài đặt hồ sơ",
        "name_l": "Tên", "name_p": "vd. Jane Doe",
        "ga_l": "Giới tính & Tuổi", "ga_p": "vd. Nữ, 25",
        "country_l": "Quốc gia", "country_p": "vd. Việt Nam",
        "occup_l": "Nghề nghiệp", "occup_p": "vd. Kỹ sư phần mềm",
        "topics_l": "Chủ đề yêu thích", "topics_p": "vd. Thiên văn, Lập trình"
    },
    "Thai": {
        "title": "ตั้งค่าโปรไฟล์",
        "name_l": "ชื่อ", "name_p": "เช่น Jane Doe",
        "ga_l": "เพศและอายุ", "ga_p": "เช่น หญิง, 25",
        "country_l": "ประเทศ", "country_p": "เช่น ประเทศไทย",
        "occup_l": "อาชีพ", "occup_p": "เช่น วิศวกรซอฟต์แวร์",
        "topics_l": "หัวข้อที่ชื่นชอบ", "topics_p": "เช่น ดาราศาสตร์, เขียนโค้ด"
    },
    "Tagalog": {
        "title": "I-set ang Profile",
        "name_l": "Pangalan", "name_p": "hal. Jane Doe",
        "ga_l": "Kasarian at Edad", "ga_p": "hal. Babae, 25",
        "country_l": "Bansa", "country_p": "hal. Pilipinas",
        "occup_l": "Trabaho", "occup_p": "hal. Software Engineer",
        "topics_l": "Mga Paboritong Paksa", "topics_p": "hal. Astronomiya, Coding"
    },
    "Malay": {
        "title": "Tetapkan Profil",
        "name_l": "Nama", "name_p": "cth. Jane Doe",
        "ga_l": "Jantina & Umur", "ga_p": "cth. Perempuan, 25",
        "country_l": "Negara", "country_p": "cth. Malaysia",
        "occup_l": "Pekerjaan", "occup_p": "cth. Jurutera Perisian",
        "topics_l": "Topik Kegemaran", "topics_p": "cth. Astronomi, Pengekodan"
    },
    "Persian": {
        "title": "تنظیم پروفایل",
        "name_l": "نام", "name_p": "مانند جين دو",
        "ga_l": "جنسیت و سن", "ga_p": "مانند زن، 25",
        "country_l": "کشور", "country_p": "مانند ایران",
        "occup_l": "شغل", "occup_p": "مانند مهندس نرم‌افزار",
        "topics_l": "موضوعات مورد علاقه", "topics_p": "مانند نجوم، برنامه‌نویسی"
    },
    "Hebrew": {
        "title": "הגדר פרופイル",
        "name_l": "שם", "name_p": "למשל ג׳יין דו",
        "ga_l": "מין וגיל", "ga_p": "למשל נקבה, 25",
        "country_l": "מדינה", "country_p": "למשל ישראל",
        "occup_l": "עיסוק", "occup_p": "למשל מהנדסת תוכנה",
        "topics_l": "נושאים מועדפים", "topics_p": "למשל אסטרונומיה, תכנות"
    },
    "Greek": {
        "title": "Ρύθμιση Προφίλ",
        "name_l": "Όνομα", "name_p": "π.χ. Jane Doe",
        "ga_l": "Φύλο & Ηλικία", "ga_p": "π.χ. Γυναίκα, 25",
        "country_l": "Χώρα", "country_p": "π.χ. Ελλάδα",
        "occup_l": "Επάγγελμα", "occup_p": "π.χ. Μηχανικός Λογισμικού",
        "topics_l": "Αγαπημένα Θέματα", "topics_p": "π.χ. Αστρονομία, Κώδικας"
    },
    "Romanian": {
        "title": "Configurare Profil",
        "name_l": "Nume", "name_p": "ex. Jane Doe",
        "ga_l": "Gen și Vârstă", "ga_p": "ex. Feminin, 25",
        "country_l": "Țară", "country_p": "ex. România",
        "occup_l": "Ocupație", "occup_p": "ex. Inginer Software",
        "topics_l": "Subiecte Preferate", "topics_p": "ex. Astronomie, Programare"
    },
    "Czech": {
        "title": "Nastavit profil",
        "name_l": "Jméno", "name_p": "např. Jane Doe",
        "ga_l": "Pohlaví a Věk", "ga_p": "např. Žena, 25",
        "country_l": "Země", "country_p": "např. Česká republika",
        "occup_l": "Povolání", "occup_p": "např. Softwarový inženýr",
        "topics_l": "Oblíbená témata", "topics_p": "např. Astronomie, Kódování"
    },
    "Ukrainian": {
        "title": "Налаштувати профіль",
        "name_l": "Ім'я", "name_p": "наприклад, Джейн Доу",
        "ga_l": "Стать та Вік", "ga_p": "наприклад, Жіноча, 25",
        "country_l": "Країна", "country_p": "наприклад, Україна",
        "occup_l": "Професія", "occup_p": "наприклад, Розробник ПЗ",
        "topics_l": "Улюблені теми", "topics_p": "наприклад, Астрономия, Кодинг"
    },
    "Hungarian": {
        "title": "Profil beállítása",
        "name_l": "Név", "name_p": "pl. Jane Doe",
        "ga_l": "Nem és Kor", "ga_p": "pl. Nő, 25",
        "country_l": "Ország", "country_p": "pl. Magyarország",
        "occup_l": "Foglalkozás", "occup_p": "pl. Szoftverfejlesztő",
        "topics_l": "Kedvenc témák", "topics_p": "pl. Csillagászat, Programozás"
    },
    "Finnish": {
        "title": "Aseta profiili",
        "name_l": "Nimi", "name_p": "esim. Jane Doe",
        "ga_l": "Sukupuoli & Ikä", "ga_p": "esim. Nainen, 25",
        "country_l": "Maa", "country_p": "esim. Suomi",
        "occup_l": "Ammatti", "occup_p": "esim. Ohjelmistokehittäjä",
        "topics_l": "Suosikkiaiheet", "topics_p": "esim. Tähtitiede, Koodaus"
    },
    "Norwegian": {
        "title": "Opprett profil",
        "name_l": "Navn", "name_p": "f.eks. Jane Doe",
        "ga_l": "Kjønn & Alder", "ga_p": "f.eks. Kvinne, 25",
        "country_l": "Land", "country_p": "f.eks. Norge",
        "occup_l": "Yrke", "occup_p": "f.eks. Programvareutvikler",
        "topics_l": "Favorittemner", "topics_p": "f.eks. Astronomi, Koding"
    },
    "Danish": {
        "title": "Indstil profil",
        "name_l": "Navn", "name_p": "f.eks. Jane Doe",
        "ga_l": "Køn & Alder", "ga_p": "f.eks. Kvinde, 25",
        "country_l": "Land", "country_p": "f.eks. Danmark",
        "occup_l": "Erhverv", "occup_p": "f.eks. Softwareingeniør",
        "topics_l": "Yndlingsemner", "topics_p": "f.eks. Astronomi, Kodning"
    },
    "Slovak": {
        "title": "Nastaviť profil",
        "name_l": "Meno", "name_p": "napr. Jane Doe",
        "ga_l": "Pohlavie a Vek", "ga_p": "napr. Žena, 25",
        "country_l": "Krajina", "country_p": "napr. Slovensko",
        "occup_l": "Povolanie", "occup_p": "napr. Softvérový inžinier",
        "topics_l": "Obľúbené témy", "topics_p": "napr. Astronómia, Kódovanie"
    },
    "Bengali": {
        "title": "প্রোফাইল সেট করুন",
        "name_l": "নাম", "name_p": "যেমন: জেসমিন আক্তার",
        "ga_l": "লিঙ্গ ও বয়স", "ga_p": "যেমন: মহিলা, ২৫",
        "country_l": "দেশ", "country_p": "যেমন: বাংলাদেশ",
        "occup_l": "পেশা", "occup_p": "যেমন: সফটওয়্যার ইঞ্জিনিয়ার",
        "topics_l": "প্রিয় বিষয়", "topics_p": "যেমন: জ্যোতির্বিজ্ঞান, কোডিং"
    },
    "Urdu": {
        "title": "پروفائل مرتب کریں",
        "name_l": "نام", "name_p": "جیسے: مریم عاصم",
        "ga_l": "جنس اور عمر", "ga_p": "جیسے: خاتون، 25",
        "country_l": "ملک", "country_p": "جیسے: پاکستان",
        "occup_l": "پیشہ", "occup_p": "جیسے: سافٹ ویئر انجینئر",
        "topics_l": "پسندیدہ موضوعات", "topics_p": "جیسے: فلکیات، کوڈنگ"
    },
    "Punjabi": {
        "title": "ਪ੍ਰੋਫਾਈਲ ਸੈੱਟ ਕਰੋ",
        "name_l": "ਨਾਮ", "name_p": "ਉਦਾ: ਕਿਰਨ",
        "ga_l": "ਲਿੰਗ ਅਤੇ ਉਮਰ", "ga_p": "ਉਦਾ: ਮਹਿਲਾ, 25",
        "country_l": "ਦੇਸ਼", "country_p": "ਉਦਾ: ਭਾਰਤ",
        "occup_l": "ਪੇਸ਼ਾ", "occup_p": "ਉਦਾ: ਸਾਫਟਵੇਅਰ ਇੰਜੀਨੀਅਰ",
        "topics_l": "ਪਸੰਦੀਦਾ ਵਿਸ਼ੇ", "topics_p": "ਉਦਾ: ਖਗੋਲ ਵਿਗਿਆਨ, ਕੋਡਿੰਗ"
    },
    "Telugu": {
        "title": "ప్రొఫైల్ సెట్ చేయండి",
        "name_l": "పేరు", "name_p": "ఉదా: దివ్య",
        "ga_l": "లింగం & వయస్సు", "ga_p": "ఉదా: స్త్రీ, 25",
        "country_l": "దేశం", "country_p": "ఉదా: భారతదేశం",
        "occup_l": "ఉద్యోగం", "occup_p": "ఉదా: సాఫ్ట్‌వేర్ ఇంజనీర్",
        "topics_l": "ఇష్టమైన అంశాలు", "topics_p": "ఉదా: ఖగోళ శాస్త్రం, కోడింగ్"
    },
    "Marathi": {
        "title": "प्रोफाइल सेट करा",
        "name_l": "नाव", "name_p": "उदा: प्रिया",
        "ga_l": "लिंग आणि वय", "ga_p": "उदा: महिला, २५",
        "country_l": "देश", "country_p": "उदा: भारत",
        "occup_l": "व्यवसाय", "occup_p": "उदा: सॉफ्टवेअर इंजिनिअर",
        "topics_l": "आवडते विषय", "topics_p": "उदा: खगोलशास्त्र, कोडिंग"
    },
    "Tamil": {
        "title": "சுவரொட்டியை அமை",
        "name_l": "பெயர்", "name_p": "எ.கா: பிரியா",
        "ga_l": "பாலினம் & வயது", "ga_p": "எ.கா: பெண், 25",
        "country_l": "நாடு", "country_p": "எ.கா: இந்தியா",
        "occup_l": "தொழில்", "occup_p": "எ.கா: மென்பொருள் பொறியாளர்",
        "topics_l": "பிடித்த தலைப்புகள்", "topics_p": "எ.கா: வானியல், குறியீட்டு முறை"
    },
    "Gujarati": {
        "title": "પ્રોફાઇલ સેટ કરો",
        "name_l": "નામ", "name_p": "દા.ત: પૂજા",
        "ga_l": "જાતિ અને ઉંમર", "ga_p": "દા.ત: સ્ત્રી, ૨૫",
        "country_l": "દેશ", "country_p": "દા.ત: ભારત",
        "occup_l": "વ્યવસાય", "occup_p": "દા.ત: સૉફ્ટવેર એન્જિનિયર",
        "topics_l": "પ્રિય વિષયો", "topics_p": "દા.ત: ખગોળશાસ્ત્ર, કોડિંગ"
    },
    "Malayalam": {
        "title": "പ്രൊഫൈൽ സജ്ജമാക്കുക",
        "name_l": "പേര്", "name_p": "ഉദാ: അഞ്ജലി",
        "ga_l": "ലിംഗഭേദവും പ്രായവും", "ga_p": "ഉദാ: സ്ത്രീ, 25",
        "country_l": "രാജ്യം", "country_p": "ഉദാ: ഇന്ത്യ",
        "occup_l": "തൊഴിൽ", "occup_p": "ഉദാ: സോഫ്റ്റ്‌വെയർ എഞ്ചിനീയർ",
        "topics_l": "ഇഷ്ടവിഷയങ്ങൾ", "topics_p": "ഉദാ: ജ്യോതിശാസ്ത്രം, കോഡിംഗ്"
    }
}

# Default English fallback structures
DEFAULT_TRANSLATION = TRANSLATIONS["English"]

class ProfileModal(discord.ui.Modal):
    def __init__(self, chosen_lang: str):
        # Resolve translation or fallback
        self.chosen_lang = chosen_lang
        trans = TRANSLATIONS.get(chosen_lang, DEFAULT_TRANSLATION)
        
        # In discord.py v2, titles can max out at 45 chars
        super().__init__(title=trans["title"][:45])

        # Interactive Inputs definition with customized translation mappings
        self.user_name = discord.ui.TextInput(
            label=trans["name_l"][:45],
            placeholder=trans["name_p"][:100],
            required=True,
            max_length=50
        )
        self.gender_age = discord.ui.TextInput(
            label=trans["ga_l"][:45],
            placeholder=trans["ga_p"][:100],
            required=True,
            max_length=30
        )
        self.country = discord.ui.TextInput(
            label=trans["country_l"][:45],
            placeholder=trans["country_p"][:100],
            required=True,
            max_length=50
        )
        self.occupation = discord.ui.TextInput(
            label=trans["occup_l"][:45],
            placeholder=trans["occup_p"][:100],
            required=True,
            max_length=55
        )
        self.topics = discord.ui.TextInput(
            label=trans["topics_l"][:45],
            placeholder=trans["topics_p"][:100],
            required=True,
            max_length=150,
            style=discord.TextStyle.paragraph
        )

        self.add_item(self.user_name)
        self.add_item(self.gender_age)
        self.add_item(self.country)
        self.add_item(self.occupation)
        self.add_item(self.topics)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Parse Gender & Age input (e.g. "Female, 25" or "Female 25")
        raw_ga = self.gender_age.value
        parsed_gender = raw_ga.strip()
        parsed_age = "30" # Smart default

        if "," in raw_ga:
            parts = [p.strip() for p in raw_ga.split(",", 1)]
            if len(parts) == 2:
                parsed_gender, parsed_age = parts[0], parts[1]
        else:
            # Check for any digit to extract age
            match = re.search(r"\d+", raw_ga)
            if match:
                parsed_age = match.group(0)
                # Leftover is gender
                gender_part = raw_ga.replace(parsed_age, "").strip(", ").strip()
                if gender_part:
                    parsed_gender = gender_part

        # Construct specific standardized profile layout
        profile_data_str = (
            f"USER_NAME: {self.user_name.value}\n"
            f"GENDER: {parsed_gender}\n"
            f"AGE: {parsed_age}\n"
            f"COUNTRY: {self.country.value}\n"
            f"OCCUPATION: {self.occupation.value}\n"
            f"FAVORITE_TOPICS: {self.topics.value}\n"
            f"MOTHER_TONGUE: {self.chosen_lang}"
        )

        checkpoint_filename = "checkpoint1.txt"
        final_prompt_block = ""
        
        try:
            # Open and read checkpoint1.txt
            if os.path.exists(checkpoint_filename):
                with open(checkpoint_filename, "r", encoding="utf-8") as f:
                    template_content = f.read()
                
                # Replace the slot delimiter
                final_prompt_block = template_content.replace("{profile_data}", profile_data_str)
            else:
                logger.error(f"Required prompt file '{checkpoint_filename}' is missing from directory!")
                final_prompt_block = f"[Warning: {checkpoint_filename} not found on server root!]\n\n[profile]\n{profile_data_str}\n[profile]"
            
            # DM template delivery to user (DM limits: split every 1950 characters safely)
            try:
                if len(final_prompt_block) <= 2000:
                    await interaction.user.send(final_prompt_block)
                else:
                    for i in range(0, len(final_prompt_block), 1950):
                        await interaction.user.send(final_prompt_block[i:i+1950])
                dm_status = "📥 **Successfully DM'd your target Prompt instruction deck!**"
            except discord.Forbidden:
                dm_status = "⚠️ **Cannot send DM!** Please enable 'Allow Server Direct Messages' so we can deliver your training prompt files safely."

            # Assign associated "Checkpoint 1 Passed" role directly
            role_name = "Checkpoint 1 Passed"
            role = discord.utils.get(interaction.guild.roles, name=role_name)
            
            if role:
                try:
                    await interaction.user.add_roles(role)
                    role_status = f"🏆 **Linked Account with Role:** `{role_name}`"
                except discord.Forbidden:
                    role_status = "⚠️ **Permission Error!** The bot can't assign you roles because its role position status is too low."
            else:
                role_status = f"⚠️ **Configuration Error!** Role '{role_name}' wasn't found on this server. Ask an Admin to sync layouts."

            await interaction.followup.send(
                f"✅ **Profile Form Parsed & Registered!**\n\n{dm_status}\n{role_status}",
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Failed checkpoint profile lifecycle handler: {e}", exc_info=True)
            await interaction.followup.send(
                f"❌ **Encountered processing failure:** `{str(e)}`",
                ephemeral=True
            )

# ==========================================
# 👾 Bot class definition
# ==========================================
class EliteDevOpsBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.guild_messages = True
        intents.members = True   # Privileged Intent for role synchronization and manipulation
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        logger.info("Initializing app tree syncing sequence...")
        await self.tree.sync()
        logger.info("Universal slash commands tree synced globally!")

bot = EliteDevOpsBot()

# Helper synchronization routine
async def execute_server_sync(guild: discord.Guild):
    """
    Scans, creates missing categories & channels exactly corresponding to setup rules.
    Syncs permissions and prevents duplicated instances.
    """
    logger.info(f"Verification engine launched in Guild: {guild.name} (ID: {guild.id})")
    
    for tier in TIER_SYSTEM:
        category_name = tier["category"]
        role_name = tier["role"]

        # Ensure Role Exists
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            try:
                role = await guild.create_role(name=role_name, reason="Elite Server DevOps Autogreeter Setup")
                logger.info(f"🛡️ Constructed missing role: '{role_name}'")
            except Exception as ex:
                logger.error(f"🛡️ Failed constructing role: '{role_name}': {ex}")
                continue
        else:
            logger.info(f"🛡️ Verified role: '{role_name}' exists.")

        # Set permissions overwrites
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

        # Check category existence
        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            try:
                category = await guild.create_category(
                    name=category_name,
                    overwrites=overwrites,
                    reason="Tier categories configuration"
                )
                logger.info(f"📂 Created category: '{category_name}'")
            except Exception as ex:
                logger.error(f"📂 Failed category construction '{category_name}': {ex}")
                continue
        else:
            try:
                await category.edit(overwrites=overwrites)
                logger.info(f"📂 Enforced policy overwrites on Category: '{category_name}'")
            except Exception as ex:
                logger.error(f"📂 Failed writing overwrites on category '{category_name}': {ex}")

        # Manage nested Text channels (أكتب)
        for tc_name in tier["text_channels"]:
            text_channel = discord.utils.get(category.text_channels, name=tc_name)
            if not text_channel:
                try:
                    await category.create_text_channel(name=tc_name, reason="Standard category channel setup")
                    logger.info(f"   📝 Generated Text Channel: '#{tc_name}'")
                except Exception as ex:
                    logger.error(f"   📝 Failed generating channel: {ex}")
            else:
                try:
                    await text_channel.edit(sync_permissions=True)
                    logger.info(f"   📝 Synced permissions on channel: '#{tc_name}'")
                except Exception as ex:
                    logger.error(f"   📝 Failed sync edits on: {ex}")

        # Manage nested Voice channels (تحدث1, تحدث2, تحدث3)
        for vc_name in tier["voice_channels"]:
            voice_channel = discord.utils.get(category.voice_channels, name=vc_name)
            if not voice_channel:
                try:
                    await category.create_voice_channel(name=vc_name, reason="Standard category voice setup")
                    logger.info(f"   🔊 Generated Voice Channel: '🔊 {vc_name}'")
                except Exception as ex:
                    logger.error(f"   🔊 Failed generating voice channel: {ex}")
            else:
                try:
                    await voice_channel.edit(sync_permissions=True)
                    logger.info(f"   🔊 Synced permissions on voice: '{vc_name}'")
                except Exception as ex:
                    logger.error(f"   🔊 Failed sync edits on: {ex}")

# ==========================================
# 🤖 Event handlers
# ==========================================
@bot.event
async def on_ready():
    logger.info(f"🤖 Bot is LIVE! Authenticated as client: {bot.user.name} (ID: {bot.user.id})")
    
    # Auto loop on guilds on boot
    for guild in bot.guilds:
        try:
            await execute_server_sync(guild)
        except Exception as e:
            logger.error(f"Boot auto-sync failed on guild: {guild.name}: {e}")

# ==========================================
# 🛠️ Slash Commands definitions
# ==========================================

# 1. /sync_server
@bot.tree.command(name="sync_server", description="Repairs categories, creates missing text/voice subchannels & applies lock permission overrides.")
@app_commands.default_permissions(administrator=True)
async def sync_server_command(interaction: discord.Interaction):
    """Admin command to execute complete sync sequence."""
    await interaction.response.defer(ephemeral=True)
    try:
        await execute_server_sync(interaction.guild)
        await interaction.followup.send("🏆 **Server Architecture Sync complete!** Categorical permissions validated and checked successfully.", ephemeral=True)
    except Exception as e:
        logger.error(f"Admin synchronization command failure: {e}")
        await interaction.followup.send(f"❌ **Sync failure:** `{e}`", ephemeral=True)

# 2. /vibecheck
@bot.tree.command(name="vibecheck", description="Sends a live checkpoint milestone alert notify directly to private review staff channels.")
async def vibe_check_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        # Search for a suitable log channel (name matches reviews, staff commands, etc.)
        staff_channel = discord.utils.get(interaction.guild.text_channels, name="staff-review")
        if not staff_channel:
            staff_channel = discord.utils.get(interaction.guild.text_channels, name="staff")
        
        # If still none exists, try to create it natively with secure locks
        if not staff_channel:
            try:
                overwrites = {
                    interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    interaction.guild.me: discord.PermissionOverwrite(view_channel=True)
                }
                staff_channel = await interaction.guild.create_text_channel(
                    name="staff-review", 
                    overwrites=overwrites,
                    reason="Create logs vault for /vibecheck alerts"
                )
            except Exception as err:
                logger.warning(f"Failed creating private staff-review channel: {err}")
                staff_channel = interaction.channel # fallback

        ping_message = f"📢 **Vibecheck Alert:** @Mentor, **{interaction.user.mention}** is ready for their live checkpoint review!"
        await staff_channel.send(ping_message)
        
        await interaction.followup.send(
            f"✅ **Milestone Alert Dispatched!** Mentors have been alerted in the private {staff_channel.mention} channel! Take some deep breaths while they prepare for your active live checkpoint review.", 
            ephemeral=True
        )
    except Exception as e:
        logger.error(f"Failed vibecheck dispatcher sequence: {e}")
        await interaction.followup.send(f"❌ **Dispatch Error:** `{e}`", ephemeral=True)

# 3. /set-profile
@bot.tree.command(name="set-profile", description="Defines customized profile and triggers target conversational learning prompts.")
@app_commands.describe(language="Select your native tongue / instructional language for instructions")
async def set_profile(interaction: discord.Interaction, language: str):
    """
    Launches a language customized modal capture form.
    Assigns checkpoint 1 on completion.
    """
    # Simply pull translation index or English by default
    chosen_language = language if language in TRANSLATIONS else "English"
    
    # Send custom localized input modal popup
    modal = ProfileModal(chosen_language)
    await interaction.response.send_modal(modal)

@set_profile.autocomplete('language')
async def set_profile_autocomplete(interaction: discord.Interaction, current: str):
    """
    Implements standard Autocomplete selection matching limit outputs perfectly.
    Matches the 40 specified language lists.
    """
    return [
        app_commands.Choice(name=lang, value=lang)
        for lang in FAMOUS_LANGUAGES if current.lower() in lang.lower()
    ][:25] # Autocomplete returns maximum of 25 nodes to prevent overflows


# ==========================================
# 📊 Gradio control functions
# ==========================================

# Define high-fidelity Gradio Theme and Stylesheet
CUSTOM_CSS = """
body, .gradio-container, .main-blocks-container {
    background-color: #0b0f19 !important;
    color: #f1f5f9 !important;
}
.header-card {
    background: linear-gradient(135deg, #1e293b, #0f172a) !important;
    border: 1px solid #334155 !important;
    padding: 2.5rem;
    border-radius: 1rem;
    box-shadow: 0 10px 15px -3px rgba(0,0,0,0.4) !important;
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
    background: #111827 !important;
    border: 1px solid #374151 !important;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3) !important;
    padding: 1.5rem;
    border-radius: 0.75rem;
    color: #f1f5f9 !important;
}
.status-card h3, .status-card p, .status-card span, .status-card div, .status-card label {
    color: #f1f5f9 !important;
}
.action-btn {
    background: linear-gradient(135deg, #0284c7, #0369a1) !important;
    color: white !important;
    border: none !important;
    border-radius: 0.5rem !important;
    font-weight: 600 !important;
    transition: all 0.2s !important;
    box-shadow: 0 2px 4px rgba(2, 132, 199, 0.3) !important;
}
.action-btn:hover {
    background: linear-gradient(135deg, #0369a1, #075985) !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 6px rgba(2, 132, 199, 0.4) !important;
}
.danger-btn {
    background: linear-gradient(135deg, #ef4444, #b91c1c) !important;
    color: white !important;
    border: none !important;
    border-radius: 0.5rem !important;
    font-weight: 600 !important;
    transition: all 0.2s !important;
}
.danger-btn:hover {
    background: linear-gradient(135deg, #dc2626, #991b1b) !important;
    transform: translateY(-1px) !important;
}
.log-terminal {
    background-color: #030712 !important;
    color: #38bdf8 !important;
    font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
    padding: 1.5rem !important;
    border-radius: 0.5rem !important;
    border: 1px solid #1f2937 !important;
}
.info-card {
    background-color: #1f2937 !important;
    border-left: 4px solid #38bdf8 !important;
    padding: 1rem;
    border-radius: 0 0.5rem 0.5rem 0;
    color: #e5e7eb !important;
}
/* Ensure Gradio components (tabs, dropdowns, textboxes) look brilliant in our slate theme */
.tabs, .tab-nav, .tabitem {
    background-color: #111827 !important;
    border-bottom: 2px solid #374151 !important;
    color: #e5e7eb !important;
}
.tab-nav button {
    color: #9ca3af !important;
}
.tab-nav button.selected {
    color: #38bdf8 !important;
    border-bottom: 2px solid #38bdf8 !important;
}
.gr-box, .gr-input, input, textarea, select {
    background-color: #1f2937 !important;
    color: #f1f5f9 !important;
    border-color: #374151 !important;
}
.gr-box:focus, .gr-input:focus, input:focus, textarea:focus, select:focus {
    border-color: #38bdf8 !important;
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
        defaults = {
            "checkpoint1.txt": "# 🎭 Personalized Conversational Prompt Coach (Level 1)\nYou are now acting as the user's interactive AI coach. Based on the registered profile data below, tailor your terminology, tone of voice, and discussion topics:\n\n=== REGISTERED USER PROFILE ===\n{profile_data}\n==============================\n\n## 🎯 Active Goals (Checkpoint 1: Core Fundamentals)\n- Initiate a dynamic, localized coaching dialogue using the user's MOTHER_TONGUE.\n- Gauge the user's familiarity with their FAVORITE_TOPICS.\n- Adapt all explanations dynamically to suit the user's AGE and OCCUPATION.\n- Keep responses concise, clear, and engaging.",
            "checkpoint2.txt": "# 🎭 Personalized Conversational Prompt Coach (Level 2)\nYou are now acting as the user's interactive AI coach for deeper application drills. Tailor your terminology, tone of voice, and discussion topics:\n\n=== REGISTERED USER PROFILE ===\n{profile_data}\n==============================\n\n## 🎯 Active Goals (Checkpoint 2: In-Depth Practice)\n- Introduce intermediate scenario challenges in the user's MOTHER_TONGUE.\n- Guide them through hands-on roleplay drills regarding their OCCUPATION and FAVORITE_TOPICS.\n- Use encouraging phrasing, offering active positive feedback loops on progress.",
            "checkpoint3.txt": "# 🎭 Personalized Conversational Prompt Coach (Level 3)\nYou are now acting as the user's interactive AI coach for advanced analytical problem solving. Tailor your terminology, tone of voice, and discussion topics:\n\n=== REGISTERED USER PROFILE ===\n{profile_data}\n==============================\n\n## 🎯 Active Goals (Checkpoint 3: Diagnostic Case Studies)\n- Frame advanced, open-ended case studies matching their OCCUPATION and FAVORITE_TOPICS.\n- Audit their reasoning skills, correcting misconceptions gently but thoroughly.\n- Encourage self-correction by asking reflective, probing questions.",
            "checkpoint4.txt": "# 🎭 Personalized Conversational Prompt Coach (Level 4)\nYou are now acting as the user's Masterclass Coach guiding them through final mastery evaluation. Tailor your terminology, tone of voice, and discussion topics:\n\n=== REGISTERED USER PROFILE ===\n{profile_data}\n==============================\n\n## 🎯 Active Goals (Checkpoint 4: Masterclass Synthesis)\n- Challenge the user with a comprehensive scenario combining multiple topics.\n- Require high-precision professional outputs tailored perfectly to their AGE and OCCUPATION.\n- Assess their command of technical vocabulary, certifying them upon successful completion."
        }
        fallback_content = defaults.get(filepath, f"# {filepath.capitalize()} Blueprint\n\n{{profile_data}}")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(fallback_content)
        except Exception as e:
            return f"Error: '{filepath}' could not be located, and auto-restoration failed: {str(e)}"
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

def write_prompt_template_changes(filepath, new_content):
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
        logger.error("🚨 DISCORD_TOKEN is missing from your configuration env!")
        return
    
    logger.info("👾 Starting background Discord Bot client loop...")
    bot.run(token)

if __name__ == "__main__":
    # Launch Discord bot natively in its own background thread to prevent blocking
    bot_thread = threading.Thread(target=run_discord_bot, daemon=True)
    bot_thread.start()
    
    # Use HF portal standard port (7860) as fallback when running on Hugging Face Spaces,
    # and AI Studio standard port (3000) when running inside AI Studio development environment.
    is_huggingface = any(k in os.environ for k in ["SPACE_ID", "SPACE_REPO_NAME", "SPACES_RESOURCES"])
    default_port = 7860 if is_huggingface else 3000
    launch_port = int(os.getenv("PORT", default_port))
    logger.info(f"🚀 Starting Gradio web server on port {launch_port} (is_huggingface={is_huggingface})...")
    demo.launch(server_name="0.0.0.0", server_port=launch_port)
