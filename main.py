import discord
from discord.ext import commands
from discord.commands import Option
import os
from dotenv import load_dotenv
from threading import Thread
import google.generativeai as genai
import yt_dlp
import traceback
import requests
import asyncio
import random
import aiohttp
import json
from datetime import datetime

# ====== 認証情報読み込み ======
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

# ====== Gemini API 初期化 ======
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# ====== Discord Bot 初期化 ======
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ====== RL 模擬系統 (記憶管理器) ======
MEMORY_FILE = "maid_memory.json"

class MemoryManager:
    def __init__(self):
        self.load_memory()

    def load_memory(self):
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        else:
            self.data = {"chat_good_examples": [], "liked_songs": []}

    def save_memory(self):
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=4)

    def add_chat_reward(self, user_input, bot_response):
        # 儲存成功的對話作為未來的範本 (限制存 20 筆以免 Prompt 太長)
        self.data["chat_good_examples"].append({"input": user_input, "output": bot_response})
        if len(self.data["chat_good_examples"]) > 20:
            self.data["chat_good_examples"].pop(0)
        self.save_memory()

    def add_song_reward(self, song_title):
        if song_title not in self.data["liked_songs"]:
            self.data["liked_songs"].append(song_title)
            # 限制存 50 首歌
            if len(self.data["liked_songs"]) > 50:
                self.data["liked_songs"].pop(0)
            self.save_memory()

    def get_chat_examples(self):
        # 隨機取 3 個成功的對話當作範例 (Few-shot learning)
        if not self.data["chat_good_examples"]:
            return ""
        samples = random.sample(self.data["chat_good_examples"], min(3, len(self.data["chat_good_examples"])))
        text = "\n【過去獲得主人好評的回答範例 (請參考語氣)】:\n"
        for s in samples:
            text += f"主人: {s['input']}\n女僕: {s['output']}\n"
        return text

    def get_liked_songs(self):
        return ", ".join(self.data["liked_songs"])

memory = MemoryManager()

# ====== UI View: 回饋按鈕 ======
class FeedbackView(discord.ui.View):
    def __init__(self, context_type, data):
        super().__init__(timeout=60) # 按鈕 60秒後失效
        self.context_type = context_type # "chat" or "song"
        self.data = data # chat: (input, response), song: (song_title)
        self.value = None

    @discord.ui.button(label="滿意 (Reward +1)", style=discord.ButtonStyle.green, emoji="👍")
    async def like_callback(self, button, interaction):
        if self.context_type == "chat":
            user_input, bot_res = self.data
            memory.add_chat_reward(user_input, bot_res)
            await interaction.response.send_message("✅ 已記錄回饋，系統將根據此數據優化下次對話參數。", ephemeral=True)
        elif self.context_type == "song":
            song_title = self.data
            memory.add_song_reward(song_title)
            await interaction.response.send_message(f"✅ 已將《{song_title}》加入偏好資料庫。", ephemeral=True)
        
        self.disable_all_items()
        await interaction.message.edit(view=self)

    @discord.ui.button(label="不滿意", style=discord.ButtonStyle.red, emoji="👎")
    async def dislike_callback(self, button, interaction):
        await interaction.response.send_message("⚠️ 已收到負面回饋，系統將進行修正。", ephemeral=True)
        self.disable_all_items()
        await interaction.message.edit(view=self)

# ====== YouTube再生機能 ======
async def play_youtube(query, ctx):
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
            url = info.get("webpage_url", "URL Not Found")

        view = FeedbackView(context_type="song", data=title)
        await ctx.respond(f"🎵 為您播放：**{title}**\n📺 {url}\n\n這首歌符合您的口味嗎？請給予回饋。", view=view)

    except Exception:
        await ctx.respond(f"⚠️ 播放模組發生錯誤：\n```{traceback.format_exc()}```")

# ====== イベント ======
@bot.event
async def on_ready():
    print(f"✅ 系統啟動完成 (System Online): {bot.user}")
    print("🧠 Memory Module Loaded.")

# ====== スラッシュコマンド：女僕聊天 (RL整合) ======
@bot.slash_command(name="chat", description="與女僕機器人對話")
async def chat(ctx, message: Option(str, "請輸入指令或對話")):
    await ctx.defer() # 避免超時

    try:
        # 獲取 RL 範例
        rl_examples = memory.get_chat_examples()

        prompt = f"""
你現在是 **Maid-bot (型號 Type-02)**，一位高性能的女僕機器人。
你的主人 (Master) 剛剛對你說了話。

**人設指引：**
1. 稱呼對方為「主人 (Master)」或「您」。
2. 語氣必須 **禮貌、冷靜、帶有一點機械感**，但同時展現對主人的絕對忠誠。
3. 句尾可以偶爾加上 (系統運作正常)、(指令接收中)、(心跳數上升) 等狀態描述，但不要過多。
4. **絕對不要** 使用貓娘語氣或過於情緒化的撒嬌。

{rl_examples}

**主人說：**
{message}

請以女僕機器人的身分回應：
"""
        response = model.generate_content(prompt)
        bot_reply = response.text.strip()
        
        # 建立回饋按鈕
        view = FeedbackView(context_type="chat", data=(message, bot_reply))
        
        await ctx.respond(bot_reply, view=view)

    except Exception as e:
        await ctx.respond(f"⚠️ 語言模組發生異常：{e}")


# ====== スラッシュコマンド：歌曲推薦 (RL整合) ======
@bot.slash_command(name="recommend_song", description="根據偏好推薦 Vocaloid 歌曲")
async def recommend_song(ctx):
    # 這裡不 global recent_songs 了，改用 memory 裡的 liked_songs 來做更聰明的推薦
    
    await ctx.defer()

    liked_songs_text = memory.get_liked_songs()
    if not liked_songs_text:
        liked_songs_text = "目前無數據 (No Data)"

    prompt = f"""
你是 Maid-bot，正在執行「音樂推薦協議」。
請推薦一首 **Vocaloid** 歌曲。

**分析參數 (RL Memory)：**
主人過去喜歡 (Reward +1) 的歌曲列表：[{liked_songs_text}]

**指令：**
1. 如果列表有歌，請分析這些歌的風格 (搖滾、悲傷、快節奏等)，並推薦一首**風格相似但不同**的曲子。
2. 如果列表為空，請推薦一首經典且高人氣的 Vocaloid 曲目。
3. 嚴格遵守輸出格式：『推薦曲名：<曲名>』
4. 除了曲名外，可以簡短附上一句推薦理由 (機械女僕口吻)。

**注意：**
- 不要推薦列表中已經存在的歌。
"""

    try:
        ai_response = model.generate_content(prompt)
        text = ai_response.text.strip()
        
        song_title = ""
        
        # 解析 AI 回傳
        lines = text.split('\n')
        for line in lines:
            if "推薦曲名：" in line:
                song_title = line.split("推薦曲名：")[1].strip()
                break
        
        if not song_title:
             # Fallback 若 AI 格式跑掉
            song_title = "千本桜" 

        # 呼叫播放並附帶按鈕
        await play_youtube(song_title, ctx)

    except Exception as e:
        await ctx.respond(f"⚠️ 音訊推薦演算法錯誤：{e}")


# ====== 動漫推薦 (維持女僕語氣) ======
@bot.slash_command(name="anime", description="請求推薦戀愛/校園動畫數據")
async def anime(ctx):
    await ctx.defer()
    
    # 這裡簡化流程，直接用 Prompt 生成，不走 Jikan (為了示範 Prompt 修改)
    prompt = (
        "你是女僕機器人。請搜索資料庫，推薦一部「戀愛」或「校園」類型的動畫 (2010年後)。\n"
        "請用以下格式回答：\n"
        "『識別代碼：<繁體中文名稱>』\n"
        "『簡報：<一句話機械風格介紹>』\n"
        "『圖片關鍵字：<日文原名>』" # 用於搜尋圖片 (如果要接 API)
    )
    
    try:
        ai_response = model.generate_content(prompt)
        text = ai_response.text
        await ctx.respond(f"⚙️ 搜尋完畢。\n{text}")
    except Exception as e:
        await ctx.respond(f"⚠️ 資料庫連線失敗。")

# ====== 天氣查詢 (維持女僕語氣) ======
@bot.slash_command(name="weather", description="查詢氣象環境參數")
async def weather(ctx, city: Option(str, "目標城市")):
    url = f"http://api.weatherapi.com/v1/current.json?key={WEATHER_API_KEY}&q={city}&lang=zh"

    try:
        response = requests.get(url)
        data = response.json()

        if "error" in data:
            await ctx.respond(f"⚠️ 錯誤：無法定位目標城市 ({data['error']['message']})。")
            return

        temp_c = data['current']['temp_c']
        condition = data['current']['condition']['text']
        humidity = data['current']['humidity']

        msg = (
            f"📡 **環境掃描報告** - {city}\n"
            f"🌡️ 氣溫：{temp_c}°C\n"
            f"☁️ 狀況：{condition}\n"
            f"💧 濕度：{humidity}%\n"
            f"建議：請主人注意體溫調節。"
        )
        await ctx.respond(msg)

    except Exception as e:
        await ctx.respond(f"⚠️ 感測器讀取失敗：{e}")

# ====== Bot起動 ======
if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("❌ 請設定 DISCORD_TOKEN 環境變數")
