import discord
from discord.ext import commands
from discord.commands import Option
import os
from dotenv import load_dotenv
from flask import Flask
from threading import Thread
import google.generativeai as genai
import yt_dlp
import traceback
from bs4 import BeautifulSoup
import requests
import asyncio
import random
import aiohttp
import json

# ====== Keep Alive（Replit専用） ======
app = Flask('')

@app.route('/')
def home():
    return "online"

def run():
    app.run(host='0.0.0.0', port=8080)

Thread(target=run).start()

# ====== 認証情報読み込み ======
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ====== Gemini API 初期化 ======
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("models/gemini-1.5-flash-latest")

# ====== Discord Bot 初期化 ======
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
last_song_title = None

# ====== YouTube再生機能 ======
async def play_youtube(query, text_channel):
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'default_search': 'ytsearch1',
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)

            if 'entries' in info:
                info = info['entries'][0]

            title = info.get("title", "Unknown Title")
            url = info.get("webpage_url", "URLが見つからなかった…")

        await text_channel.send(f"🎵 推薦曲名：**{title}**\n📺 {url}")

    except Exception:
        await text_channel.send(f"⚠️找不到適合的曲子呢：\n```{traceback.format_exc()}```")



# ====== イベント ======
@bot.event
async def on_ready():
    print(f"✅ 起動完成！！！: {bot.user}")

# ====== スラッシュコマンド：兄控チャット ======
@bot.slash_command(name="onichan", description="煩死了，你是想怎麼樣")
async def onichan(ctx, メッセージ: Option(str, "你想說什麼？")):
    await ctx.respond("...")

    try:
        prompt = f"""
你現在是一位高中女生，個性有點高冷但其實很關心對方。
說話風格要冷靜、簡潔，偶爾嘴硬，但話語中要隱約流露出關心。
偶爾會出現不小心透露出的可愛行為或詞語，帶有些微反差萌，讓人覺得你其實有點可愛。
不要使用撒嬌語氣，也不需要太多表情符號。
不要使用「（內心：...）」或其他括號說明，只用自然對話方式表達關心和情緒。

你的女朋友剛剛說：
{メッセージ}
"""


        response = model.generate_content(prompt)
        await ctx.send(response.text)

    except Exception as e:
        await ctx.send(f"糟糕，好像出錯了…：{e}")


# ====== スラッシュコマンド：Vocaloid曲再生 ======
# ====== 歷史記憶（全域變數）======
recent_songs = []

@bot.slash_command(name="play", description="我來幫你選擇Vocaloid歌曲吧~~🎵")
async def play(ctx):
    global recent_songs

    await ctx.respond("嗯……等我一下")

    # 整理最近推薦過的曲名列表（如果沒推薦過就空白）
    history_text = "、".join(recent_songs) if recent_songs else "沒有"

    prompt = f"""
あなたは兄が大好きな妹キャラです。日本語で答えてください。
今おすすめしたいVocaloid曲を一つだけ選んでください。

条件：
- 過去に推薦した曲（{history_text}）と同じ曲、または超有名な曲（例：千本桜、メルトなど）は選ばないでください。
- あまり知られていない、でも素敵なVocaloid曲を選んでください。
- 形式は必ず『推薦曲名：<曲名>』だけ。他の言葉や説明は禁止です。

注意：
- 有名すぎる曲は禁止です。
- 同じ曲は絶対に選ばないでください。
    """

    try:
        ai_response = model.generate_content(prompt)
        text = ai_response.text.strip()

        if "推薦曲名：" in text:
            parts = text.split("推薦曲名：")
            if len(parts) > 1:
                song_title = parts[1].strip()
            else:
                await ctx.send("咦...歌名好像不見了？我再想一首吧～")
                return

            if song_title in recent_songs:
                await ctx.send("呃...這首之前不是說過了嗎…我幫你再想一首新的吧")
                return

            recent_songs.append(song_title)
            if len(recent_songs) > 10:
                recent_songs.pop(0)

            await play_youtube(song_title, ctx.channel)

        else:
            await ctx.send("呃…我好像說錯格式了？我再試一次試試看...")

    except Exception as e:
        await ctx.send(f"哇...出錯了...ˊ˙_˙：{e}")

anime_history = set()

# AI 生成推薦動漫
async def generate_anime_title():
    prompt = (
        "請根據以下條件推薦一部動畫作品：\n"
        "・類型必須是『戀愛』或『校園』類型。\n"
        "・播出年份必須是2010年之後。\n"
        "・請用以下格式回答：『推薦作品名：<繁體中文名稱>｜<日文原名>』或『<日文原名>』。\n"
        "・請用繁體中文回答。"
    )
    ai_response = model.generate_content(prompt)
    text = ai_response.text.strip()

    # 最寬鬆處理方式
    if "推薦作品名：" in text and "｜" in text:
        parts = text.split("我還蠻推薦這部的... ")[1].split("｜")
        zh_name = parts[0].strip()
        jp_name = parts[1].strip()
        return zh_name, jp_name
    elif "｜" in text:
        zh_name, jp_name = text.split("｜")
        return zh_name.strip(), jp_name.strip()
    else:
        return None, text  # 把整段當作日文名 fallback 使用

# Jikan API 搜尋
async def search_jikan_anime(title_jp):
    url = f"https://api.jikan.moe/v4/anime?q={title_jp}&limit=10&sfw=true"
    res = requests.get(url)

    if res.status_code != 200:
        return None

    data = res.json()
    if not data.get("data"):
        return None

    for anime in data["data"]:
        year = anime.get("year", 0)
        genres = [g["name"] for g in anime.get("genres", [])]

        # 寬鬆條件：2010以後 + 含任一關鍵 genre
        if year >= 2010 and ("Romance" in genres or "School" in genres):
            return {
                "title_jp": anime.get("title_japanese", anime.get("title")),
                "title_zh": anime.get("title"),
                "url": anime["url"],
                "image_url": anime["images"]["jpg"]["large_image_url"]
            }

    return None

@bot.slash_command(name="anime", description="推薦一部戀愛／校園系動漫")
async def anime(ctx):
    await ctx.respond("稍微等我一下喔...")

    for _ in range(5):  # 最多嘗試 5 次
        result = await generate_anime_title()
        if not result:
            continue

        zh_name, jp_name = result

        if jp_name in anime_history:
            continue

        anime_info = await search_jikan_anime(jp_name)

        if anime_info:
            anime_history.add(jp_name)
            embed = discord.Embed(
                title=f"推薦作品名：{anime_info['title_zh']}｜{anime_info['title_jp']}",
                url=anime_info["url"],
                color=0x00ccff
            )
            embed.set_image(url=anime_info["image_url"])
            await ctx.send("這部動畫應該很適合你，要不要去看看呢?")
            await ctx.send(embed=embed)
            return

        await asyncio.sleep(1)

    await ctx.send("唉…找不到適合的作品欸…再讓我試一次吧!")





# ====== 天氣查詢指令（改良版） ======
@bot.slash_command(name="weather", description="查詢天氣☀️")
async def weather(ctx, city: Option(str, "想知道哪裡的天氣呢？")):
    await ctx.respond("等我一下，我來幫你查天氣☁️")

    weather_api_key = os.getenv("WEATHER_API_KEY")
    url = f"http://api.weatherapi.com/v1/current.json?key={weather_api_key}&q={city}&lang=zh"

    try:
        response = requests.get(url)
        data = response.json()

        if "error" in data:
            await ctx.send(f"找不到那個地方欸…\n你檢查一下城市的名字，是不是打錯了？\n（錯誤訊息{data['error']['message']}）")
            return

        # 取得天氣資料
        temp_c = data['current']['temp_c']
        condition = data['current']['condition']['text']
        humidity = data['current']['humidity']

        # 發送撒嬌語氣訊息
        message = (
            f"查到啦～這是 **{city}** 現在的天氣!\n"
            f"🌡️ 氣溫：**{temp_c}°C**\n"
            f"☁️ 天氣狀況：**{condition}**\n"
            f"💧 濕度：**{humidity}%**\n\n"
        )

        await ctx.send(message)

    except Exception as e:
        await ctx.send(f" 哇!查天氣的時候出了點問題…讓我再試一次吧!：{e}")


# ====== スラッシュコマンド：じゃんけん（猜拳） ======
@bot.slash_command(name="rps", description="一起猜拳吧~~✊✌️🖐️")
async def rps(ctx, 手: Option(str, "選擇要出什麼吧!", choices=["石頭", "剪刀", "布"])):
    await ctx.respond("嗯……，已經猜到你要出什麼了呢...")

    try:
        # AI 猜哥哥的真正出拳 & 妹妹選擇贏的手
        prompt = f"""
你是一位很會讀空氣的妹妹，要和哥哥猜拳（石頭、剪刀、布）。
哥哥說他要出「{手}」，但你覺得他心裡真正會出的是什麼呢？
請預測他真正的選擇，並選出能贏他的手勢。

⚠️ 僅回覆格式為：選擇的手：<石頭 / 剪刀 / 布>
不要加上任何解釋或多餘的文字。
        """

        ai_response = model.generate_content(prompt)
        ai_choice_raw = ai_response.text.strip()

        if "選擇的手：" in ai_choice_raw:
            ai_hand = ai_choice_raw.split("選擇的手：")[1].strip()
        else:
            import random
            ai_hand = random.choice(["石頭", "剪刀", "布"])

        # 判定邏輯
        result = ""
        if ai_hand == 手:
            result = "咦！？平手嗎?好巧啊~"
        elif (手 == "石頭" and ai_hand == "布") or (手 == "剪刀" and ai_hand == "石頭") or (手 == "布" and ai_hand == "剪刀"):
            result = "嘿嘿~這次是我贏啦~ˋvˊ"
        else:
            result = "欸欸欸！？竟然是你贏了嗎！？"

        await ctx.send(f"✊✌️🖐️\n你剛剛出的是【{手}】，然後我出了【{ai_hand}】唷～！\n\n{result}")

    except Exception as e:
        await ctx.send(f"哇…我猜拳猜到一半當機了，忘記要出什麼了ˊ^^：{e}")


# ====== 普通のメッセージ反応（旧式） ======
@bot.event
async def on_message(message):
    await bot.process_commands(message)

    if message.author == bot.user:
        return

    if message.content.startswith("!hello"):
        await message.channel.send("嗯?有什麼想跟我說的嗎？")

# ====== Bot起動 ======
bot.run(TOKEN)

