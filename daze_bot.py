"""
DAZE Clan — Discord Bot
========================
ดึงข้อมูลจาก Google Sheet แบบ real-time
Commands: !clan  !stat  !rank  !กิจ  !alert  !help
"""

import discord
from discord.ext import commands
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
import os
import time
import json
import tempfile
from datetime import datetime

# ─────────────────────────────────────────
#  Config
# ─────────────────────────────────────────
load_dotenv()

# รองรับ Railway: ถ้าไม่มีไฟล์ credentials.json ให้อ่านจาก env var แทน
_creds_env = os.getenv("GOOGLE_CREDENTIALS_JSON")
if _creds_env and not os.path.exists(os.getenv("CREDS_FILE", "credentials.json")):
    _tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    _tmp.write(_creds_env)
    _tmp.close()
    os.environ["CREDS_FILE"] = _tmp.name

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SHEET_ID      = os.getenv("SHEET_ID", "1btKWQ4K4gPO6IegDmoDYI9TlGdBNj5spvsBq2dOZqF0")
LEADER_ROLE   = os.getenv("LEADER_ROLE", "Leader")   # ชื่อ Role ใน Discord ที่ใช้คำสั่ง !alert
CREDS_FILE    = os.getenv("CREDS_FILE", "credentials.json")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# ─────────────────────────────────────────
#  Google Sheets — Cache 3 นาที
# ─────────────────────────────────────────
_cache = {"members": None, "activity": None, "ts": 0}
CACHE_TTL = 180  # seconds


def _refresh_cache():
    global _cache
    if time.time() - _cache["ts"] < CACHE_TTL:
        return

    creds  = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
    gc     = gspread.authorize(creds)
    sheet  = gc.open_by_key(SHEET_ID)

    # ── รายชื่อ sheet : col B (2) = รหัส, col C (3) = ชื่อในเกม, col H (8) = รวม ──
    ws_list = sheet.worksheet("รายชื่อ")
    codes_m  = ws_list.col_values(2)[4:]   # รหัส เช่น dz001
    names_m  = ws_list.col_values(3)[4:]   # ชื่อในเกม
    scores   = ws_list.col_values(8)[4:]

    members = []
    for i, name in enumerate(names_m):
        if name.strip():
            score = 0.0
            if i < len(scores):
                try:
                    score = float(str(scores[i]).replace(",", ""))
                except ValueError:
                    score = 0.0
            code = codes_m[i].strip() if i < len(codes_m) else ""
            members.append({"name": name.strip(), "code": code, "score": score})

    # ── คะแนนกิจ sheet : col B (2) = ชื่อในเกม, col AO (41) = สรุป ──
    ws_act  = sheet.worksheet("คะแนนกิจ")
    names_a = ws_act.col_values(2)[5:]     # skip 5 header rows, data starts row 6
    att_raw = ws_act.col_values(41)[5:]    # AO = column 41

    activity = []
    for i, name in enumerate(names_a):
        if name.strip():
            att = 0
            if i < len(att_raw):
                try:
                    att = int(str(att_raw[i]).replace(",", ""))
                except ValueError:
                    att = 0
            activity.append({"name": name.strip(), "attendance": att})

    _cache["members"]  = members
    _cache["activity"] = activity
    _cache["ts"]       = time.time()


def get_members():
    _refresh_cache()
    return _cache["members"]


def get_activity():
    _refresh_cache()
    return _cache["activity"]


def find_member(name: str):
    """ค้นหาจากรหัส (dz001) หรือชื่อในเกม แบบ case-insensitive + partial match"""
    n = name.strip().lower()
    m = next((x for x in get_members()
              if n == x["code"].lower() or n in x["name"].lower()), None)
    # ค้นหา activity ด้วยชื่อของ member ที่เจอ (ถ้าเจอ) หรือ query ตรงๆ
    search_name = m["name"].lower() if m else n
    a = next((x for x in get_activity() if search_name in x["name"].lower()), None)
    return m, a


# ─────────────────────────────────────────
#  Bot setup
# ─────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


def has_leader_role():
    """Permission check — ต้องมี Role ชื่อตาม LEADER_ROLE"""
    async def predicate(ctx):
        return any(r.name == LEADER_ROLE for r in ctx.author.roles)
    return commands.check(predicate)


def att_emoji(att):
    if att >= 25: return "✅"
    if att >= 20: return "⚠️"
    return "🔴"


def att_label(att):
    if att >= 25: return "Active"
    if att >= 20: return "ปานกลาง"
    return "น้อย"


def updated_footer():
    return f"อัปเดต {datetime.now().strftime('%d/%m/%Y %H:%M')}  •  DAZE Bot"


# ─────────────────────────────────────────
#  Events
# ─────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ DAZE Bot online — {bot.user}  (prefix: !)")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("🔒 คำสั่งนี้ใช้ได้เฉพาะ Leader เท่านั้น")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ ใส่ argument ไม่ครบ — พิมพ์ `!help` ดูวิธีใช้")
    else:
        await ctx.send(f"❌ เกิดข้อผิดพลาด: `{error}`")


# ─────────────────────────────────────────
#  !help
# ─────────────────────────────────────────
@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(
        title="🤖 DAZE Bot — คำสั่งทั้งหมด",
        color=0x5865F2
    )
    embed.add_field(
        name="`!clan`",
        value="สรุปภาพรวม Clan (จำนวนสมาชิก, Avg Score, Active, กิจน้อย)",
        inline=False
    )
    embed.add_field(
        name="`!stat <ชื่อ>`",
        value="ดู stat + กิจกรรมรายคน\nใช้รหัสหรือชื่อก็ได้ เช่น: `!stat dz001` หรือ `!stat SirT`",
        inline=False
    )
    embed.add_field(
        name="`!rank [N]`",
        value="Top N ranking ตามคะแนนรวม (default 10, max 20)\nตัวอย่าง: `!rank 15`",
        inline=False
    )
    embed.add_field(
        name="`!กิจ [ชื่อ]`",
        value="Top 10 กิจกรรม หรือดูรายคน\nตัวอย่าง: `!กิจ` หรือ `!กิจ MaxApply`",
        inline=False
    )
    embed.add_field(
        name="`!alert` 🔒",
        value="รายชื่อสมาชิกที่มีกิจ < 20 ครั้ง (เฉพาะ Leader)",
        inline=False
    )
    embed.set_footer(text=updated_footer())
    await ctx.send(embed=embed)


# ─────────────────────────────────────────
#  !clan — ภาพรวม
# ─────────────────────────────────────────
@bot.command(name="clan")
async def clan_cmd(ctx):
    members  = get_members()
    activity = get_activity()

    total     = len(members)
    avg_score = round(sum(m["score"] for m in members) / total) if total else 0
    top_score = max(m["score"] for m in members) if members else 0
    active_25 = sum(1 for a in activity if a["attendance"] >= 25)
    active_20 = sum(1 for a in activity if a["attendance"] >= 20)
    low_att   = sum(1 for a in activity if a["attendance"] < 20)
    top_member = max(members, key=lambda x: x["score"]) if members else None

    embed = discord.Embed(title="🏰 DAZE Clan — ภาพรวม", color=0x5865F2)
    embed.add_field(name="👥 สมาชิกทั้งหมด", value=f"**{total}** คน",              inline=True)
    embed.add_field(name="⭐ Avg Score",       value=f"**{avg_score:.1f}**",         inline=True)
    embed.add_field(name="🏆 Top Score",        value=f"**{top_score:.1f}**",        inline=True)
    embed.add_field(name="✅ Active (≥25 ครั้ง)", value=f"**{active_25}** คน",      inline=True)
    embed.add_field(name="⚠️ ปานกลาง (20-24)",   value=f"**{active_20 - active_25}** คน", inline=True)
    embed.add_field(name="🔴 กิจน้อย (<20)",      value=f"**{low_att}** คน",        inline=True)
    if top_member:
        embed.add_field(name="👑 อันดับ 1", value=f"**{top_member['name']}** ({top_member['score']:.1f})", inline=False)
    embed.set_footer(text=updated_footer())
    await ctx.send(embed=embed)


# ─────────────────────────────────────────
#  !stat <ชื่อ>
# ─────────────────────────────────────────
@bot.command(name="stat")
async def stat_cmd(ctx, *, name: str = None):
    if not name:
        await ctx.send("❌ ระบุชื่อด้วยนะครับ เช่น `!stat MaxApply`")
        return

    member, act = find_member(name)

    if not member:
        await ctx.send(f"❌ ไม่พบสมาชิกชื่อ **{name}** — ลองพิมพ์ชื่อในเกมให้ตรงนะครับ")
        return

    # คำนวณ rank
    sorted_m = sorted(get_members(), key=lambda x: x["score"], reverse=True)
    rank = next((i + 1 for i, m in enumerate(sorted_m) if m["name"] == member["name"]), "?")

    att = act["attendance"] if act else 0

    code_str = f" `{member['code']}`" if member.get("code") else ""
    embed = discord.Embed(
        title=f"👤 {member['name']}{code_str}",
        color=0x57F287 if att >= 25 else (0xFEE75C if att >= 20 else 0xED4245)
    )
    embed.add_field(name="🏆 คะแนนรวม",   value=f"**{member['score']:.1f}**",     inline=True)
    embed.add_field(name="📊 Rank",        value=f"**#{rank}** / {len(sorted_m)}", inline=True)
    embed.add_field(name=f"{att_emoji(att)} กิจกรรม",
                    value=f"**{att}/36** ครั้ง — {att_label(att)}",               inline=True)
    embed.set_footer(text=updated_footer())
    await ctx.send(embed=embed)


# ─────────────────────────────────────────
#  !rank [N]
# ─────────────────────────────────────────
@bot.command(name="rank")
async def rank_cmd(ctx, top: int = 10):
    top = min(max(top, 1), 20)   # clamp 1–20
    members = get_members()
    sorted_m = sorted(members, key=lambda x: x["score"], reverse=True)[:top]

    medals = ["🥇", "🥈", "🥉"]
    lines  = []
    for i, m in enumerate(sorted_m):
        prefix = medals[i] if i < 3 else f"`{i+1:>2}.`"
        lines.append(f"{prefix} **{m['name']}** — {m['score']:.1f}")

    embed = discord.Embed(
        title=f"🏆 Top {len(sorted_m)} Ranking — DAZE",
        description="\n".join(lines),
        color=0xFEE75C
    )
    embed.set_footer(text=updated_footer())
    await ctx.send(embed=embed)


# ─────────────────────────────────────────
#  !กิจ [ชื่อ]
# ─────────────────────────────────────────
@bot.command(name="กิจ")
async def activity_cmd(ctx, *, name: str = None):
    if name:
        _, act = find_member(name)
        if not act:
            await ctx.send(f"❌ ไม่พบ **{name}**")
            return
        att = act["attendance"]
        embed = discord.Embed(
            title=f"📅 กิจกรรม — {act['name']}",
            color=0x57F287 if att >= 25 else (0xFEE75C if att >= 20 else 0xED4245)
        )
        embed.add_field(name="เข้าร่วม",  value=f"**{att}/36** ครั้ง", inline=True)
        embed.add_field(name="สถานะ",     value=f"{att_emoji(att)} {att_label(att)}", inline=True)

        # Progress bar (10 blocks)
        filled = round(att / 38 * 10)
        bar    = "█" * filled + "░" * (10 - filled)
        embed.add_field(name="Progress", value=f"`{bar}` {round(att/36*100)}%", inline=False)
        embed.set_footer(text=updated_footer())
        await ctx.send(embed=embed)

    else:
        activity = sorted(get_activity(), key=lambda x: x["attendance"], reverse=True)[:10]
        lines = [
            f"`{i+1:>2}.` {att_emoji(a['attendance'])} **{a['name']}** — {a['attendance']}/36"
            for i, a in enumerate(activity)
        ]
        embed = discord.Embed(
            title="📅 Top 10 กิจกรรม — DAZE",
            description="\n".join(lines),
            color=0x57F287
        )
        embed.set_footer(text=updated_footer())
        await ctx.send(embed=embed)


# ─────────────────────────────────────────
#  !alert  [Leader only]
# ─────────────────────────────────────────
@bot.command(name="alert")
@has_leader_role()
async def alert_cmd(ctx):
    activity = get_activity()
    low = sorted(
        [a for a in activity if a["attendance"] < 20],
        key=lambda x: x["attendance"]
    )

    if not low:
        embed = discord.Embed(
            title="✅ ไม่มีสมาชิกที่กิจน้อยกว่า 20 ครั้ง!",
            color=0x57F287
        )
        await ctx.send(embed=embed)
        return

    lines = [f"🔴 **{a['name']}** — {a['attendance']}/36 ครั้ง" for a in low]
    embed = discord.Embed(
        title=f"⚠️ Alert — {len(low)} คน มีกิจน้อยกว่า 20 ครั้ง",
        description="\n".join(lines),
        color=0xED4245
    )
    embed.set_footer(text=updated_footer())
    await ctx.send(embed=embed)


# ─────────────────────────────────────────
#  Run
# ─────────────────────────────────────────
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise ValueError("❌ ไม่พบ DISCORD_TOKEN — ดู .env.example")
    bot.run(DISCORD_TOKEN)
