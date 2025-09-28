# ----------------------------------------------------------------------------------
# # 💎 بوت صياد الجواهر - النسخة النهائية (التصحيح الأخير الكامل) 💎
# ----------------------------------------------------------------------------------
#
# الإصدار: 11.0 (تصحيح معالجات الأوامر)
#
# التصحيح:
#   - تمت إزالة كلمة `async` من تعريف دوال `start_command` و `button_callback`
#     لحل مشكلة عدم الاستجابة للأوامر بسبب تعارض التزامن.

import logging
import asyncio
import os
import re
import aiohttp
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler
from web3 import Web3
from dotenv import load_dotenv
from telethon import TelegramClient, events

# --- تحميل متغيرات البيئة ---
load_dotenv()

# --- الإعدادات الرئيسية (يتم قراءتها من متغيرات البيئة) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ALCHEMY_HTTPS_URL = os.getenv("ALCHEMY_HTTPS_URL")
GOPLUS_API_KEY = os.getenv("GOPLUS_API_KEY")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

# --- أهداف المراقبة ---
TARGET_CHANNELS = ['MEXCofficialNews', 'Kucoin_News']
LISTING_KEYWORDS = ['will list', 'listing', 'kickstarter', 'new listing', 'new token']

# --- إعدادات التسجيل (Logging) ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- التحقق من وجود جميع المفاتيح ---
def check_env_vars():
    required_vars = {
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
        "ALCHEMY_HTTPS_URL": ALCHEMY_HTTPS_URL,
        "GOPLUS_API_KEY": GOPLUS_API_KEY,
        "API_ID": API_ID,
        "API_HASH": API_HASH,
    }
    missing_vars = [key for key, value in required_vars.items() if value is None]
    if missing_vars:
        logger.error(f"FATAL: Missing environment variables: {', '.join(missing_vars)}")
        return False
    return True

# --- دوال المساعدة والتحليل (مع التصحيحات) ---
def escape_markdown_v2(text: str) -> str:
    if not isinstance(text, str): text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

async def analyze_contract_with_goplus(contract_address):
    url = f"https://api.gopluslabs.io/api/v1/token_security/56?contract_addresses={contract_address}"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {GOPLUS_API_KEY}"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as response:
                response.raise_for_status()
                data = await response.json()
                if data.get("result") and contract_address.lower() in data["result"]:
                    return data["result"][contract_address.lower()]
    except Exception as e:
        logger.error(f"GoPlus API request failed: {e}")
    return None

async def scrape_bscscan_for_socials(contract_address):
    url = f"https://bscscan.com/token/{contract_address}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    socials = {}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as response:
                response.raise_for_status()
                content = await response.text()
                soup = BeautifulSoup(content, 'lxml')
                social_profiles_div = soup.find('div', id='ContentPlaceHolder1_divSummary')
                if social_profiles_div:
                    links = social_profiles_div.select('a.text-break')
                    for link in links:
                        href = link.get('href')
                        if 't.me' in href: socials['telegram'] = href
                        elif 'twitter.com' in href: socials['twitter'] = href
                        else: socials.setdefault('website', href)
    except Exception as e:
        logger.error(f"BscScan scraping failed for {contract_address}: {e}")
    return socials

async def get_telegram_subscriber_count(telegram_link):
    if not telegram_link or 't.me/' not in telegram_link: return None
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(telegram_link, headers=headers, timeout=10) as response:
                response.raise_for_status()
                content = await response.text()
                soup = BeautifulSoup(content, 'html.parser')
                div = soup.find('div', class_='tgme_page_extra')
                if div and 'members' in div.text:
                    count_str = div.text.split(' members')[0].replace(' ', '').replace('\xa0', '')
                    return int(count_str)
    except Exception as e:
        logger.error(f"Failed to get Telegram subscribers for {telegram_link}: {e}")
    return None

def generate_recommendation(analysis_data, social_data, telegram_subs):
    score, strengths, risks = 5, [], []
    if analysis_data.get('is_honeypot') == '0':
        score += 2; strengths.append("✅ *عقد آمن:* ليس فخًا (Honeypot).")
    else:
        score -= 5; risks.append("🚨 *خطر فادح:* العقد هو فخ (Honeypot)!")
    buy_tax, sell_tax = float(analysis_data.get('buy_tax', '101')) * 100, float(analysis_data.get('sell_tax', '101')) * 100
    if buy_tax < 5 and sell_tax < 5:
        score += 1; strengths.append(f"✅ *ضرائب مقبولة:* شراء:`{buy_tax:.1f}%`|بيع:`{sell_tax:.1f}%`.")
    else: risks.append(f"⚠️ *ضرائب مرتفعة:* شراء:`{buy_tax:.1f}%`|بيع:`{sell_tax:.1f}%`.")
    if analysis_data.get('owner_address') in ['', '0x0000000000000000000000000000000000000000']:
        score += 1; strengths.append("✅ *ملكية متخلى عنها:* لا يمكن للمطور تغيير العقد.")
    if social_data.get('website') and social_data.get('telegram'):
        score += 1; strengths.append("✅ *وجود أساسي:* تم العثور على موقع وتليجرام.")
    else: risks.append("⚠️ *غياب الروابط:* لم يتم العثور على موقع أو تليجرام.")
    if telegram_subs:
        if telegram_subs > 1000:
            score += 1; strengths.append(f"📈 *مجتمع جيد:* يمتلك `{telegram_subs}` عضو.")
        else: risks.append(f"📉 *مجتمع ناشئ:* عدد الأعضاء صغير (`{telegram_subs}` عضو).")
    if score >= 8: decision = "💡 *القرار المقترح: فرصة واعدة.* يستحق دراسة أعمق."
    elif 5 <= score < 8: decision = "💡 *القرار المقترح: إضافة لقائمة المراقبة.*"
    else: decision = "💡 *القرار المقترح: تجنب حاليًا.* يحمل مخاطر عالية."
    return {"score": f"{max(0, min(10, score))}/10", "strengths": strengths, "risks": risks, "decision": decision}

def format_recommendation_report(token_name, recommendation, analysis_data, social_data):
    header = f"💎 *توصية استثمارية: {escape_markdown_v2(token_name)}*\n\n"
    score_line = f"**التقييم الأولي: {escape_markdown_v2(recommendation['score'])}**\n\n"
    summary = f"*{escape_markdown_v2(recommendation['decision'])}*\n\n---\n\n"
    strengths_section = "*✅ نقاط القوة:*\n" + "\n".join(recommendation['strengths']) + "\n\n" if recommendation['strengths'] else ""
    risks_section = "*⚠️ نقاط المخاطرة:*\n" + "\n".join(recommendation['risks']) + "\n\n" if recommendation['risks'] else ""
    links_section = "🔗 *روابط للتحقق بنفسك:*\n" + f"[فحص العقد](https://bscscan.com/token/{analysis_data.get('contract_address')})\n"
    if social_data.get('website'): links_section += f"[الموقع الرسمي]({social_data['website']})\n"
    if social_data.get('telegram'): links_section += f"[قناة تليجرام]({social_data['telegram']})\n"
    return header + score_line + summary + strengths_section + risks_section + links_section

# --- دوال بوت التحكم (مع التصحيح) ---
def start_command(update: Update, context: CallbackContext):
    update.message.reply_text("أهلاً بك في بوت صياد الجواهر (النسخة النهائية).", reply_markup=get_main_keyboard(context))

def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    action = query.data
    if action == 'toggle_blockchain':
        job_name = 'blockchain_monitor_job'
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        if current_jobs:
            for job in current_jobs: job.schedule_removal()
            query.edit_message_text(text="تم إيقاف مراقبة البلوك تشين.", reply_markup=get_main_keyboard(context))
        else:
            context.job_queue.run_repeating(blockchain_monitoring_job, interval=60, first=1, name=job_name)
            query.edit_message_text(text="تم بدء مراقبة البلوك تشين.", reply_markup=get_main_keyboard(context))

def get_main_keyboard(context: CallbackContext):
    job_name = 'blockchain_monitor_job'
    is_running = bool(context.job_queue.get_jobs_by_name(job_name))
    button_text = "🔴 إيقاف المراقبة" if is_running else "🟢 بدء المراقبة والتحقيق"
    keyboard = [[InlineKeyboardButton(button_text, callback_data='toggle_blockchain')]]
    return InlineKeyboardMarkup(keyboard)

async def blockchain_monitoring_job(context: CallbackContext):
    logger.info("⛓️ Checking for new blocks...")
    try:
        w3 = Web3(Web3.HTTPProvider(ALCHEMY_HTTPS_URL))
        latest_block_number = w3.eth.block_number
        last_checked_block = context.bot_data.get('last_checked_block', latest_block_number - 1)
        for block_num in range(last_checked_block + 1, latest_block_number + 1):
            block = w3.eth.get_block(block_num, full_transactions=True)
            for tx in block.transactions:
                if tx.to is None:
                    receipt = w3.eth.get_transaction_receipt(tx.hash)
                    contract_address = receipt.contractAddress
                    logger.info(f"💎 New contract created: {contract_address}")
                    analysis_data = await analyze_contract_with_goplus(contract_address)
                    if not analysis_data or analysis_data.get('is_honeypot') == '1':
                        logger.warning(f"Skipping honeypot or failed analysis for {contract_address}")
                        continue
                    analysis_data['contract_address'] = contract_address
                    token_name = analysis_data.get('token_name', 'Unknown Token')
                    social_data = await scrape_bscscan_for_socials(contract_address)
                    telegram_subs = await get_telegram_subscriber_count(social_data.get('telegram'))
                    recommendation = generate_recommendation(analysis_data, social_data, telegram_subs)
                    report = format_recommendation_report(token_name, recommendation, analysis_data, social_data)
                    await context.bot.send_message(
                        chat_id=int(TELEGRAM_CHAT_ID), text=report,
                        parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
        context.bot_data['last_checked_block'] = latest_block_number
    except Exception as e:
        logger.error(f"Error in blockchain monitoring job: {e}", exc_info=True)

# --- وحدة مراقب الإعلانات ---
async def news_monitoring_client(bot):
    session_name = "gem_hunter_prod"
    client = TelegramClient(session_name, int(API_ID), API_HASH)
    logger.info("📰 News monitoring client starting...")
    @client.on(events.NewMessage(chats=TARGET_CHANNELS))
    async def handler(event):
        message_text = event.raw_text.lower()
        if any(keyword in message_text for keyword in LISTING_KEYWORDS):
            logger.info(f"🚨🚨🚨 Potential listing announcement in {getattr(event.chat, 'username', 'Unknown')}!")
            alert_header = f"🚨 *تنبيه إدراج محتمل من قناة {escape_markdown_v2(getattr(event.chat, 'username', 'Unknown'))}* 🚨\n\n---\n\n"
            full_message = alert_header + escape_markdown_v2(event.raw_text)
            try:
                await bot.send_message(chat_id=int(TELEGRAM_CHAT_ID), text=full_message, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception as e:
                logger.error(f"Failed to send listing alert via bot: {e}")
    await client.start()
    logger.info("📰 News monitoring client is connected and running.")
    await client.run_until_disconnected()

# --- الدالة الرئيسية للتشغيل ---
async def main():
    if not check_env_vars(): return
    updater = Updater(TELEGRAM_BOT_TOKEN)
    dispatcher = updater.dispatcher
    dispatcher.add_handler(CommandHandler("start", start_command))
    dispatcher.add_handler(CallbackQueryHandler(button_callback))
    updater.start_polling()
    logger.info("🚀 Gem Hunter Control Bot (Final Corrected Version) is running...")
    await news_monitoring_client(updater.bot)
    updater.idle()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot shutting down.")
