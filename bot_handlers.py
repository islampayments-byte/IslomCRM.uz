import telebot
from telebot import types
from models import Driver

def process_bot_update(token, update_json, org, app_context):
    """
    Processes a single Telegram update for a specific organization's bot.
    """
    bot = telebot.TeleBot(token, threaded=False)
    update = types.Update.de_json(update_json)
    
    if not update or not update.message:
        return
    
    message = update.message
    chat_id = message.chat.id
    
    # Handle /start command
    if message.text and message.text.startswith('/start'):
        telegram_id = str(message.from_user.id)
        
        with app_context:
            # Check if this telegram user is registered as a driver in this organization
            driver = Driver.query.filter_by(user_id=org.id, telegram_id=telegram_id).first()
            
            if driver:
                welcome_text = (
                    f"Assalomu alaykum, <b>{driver.first_name}</b>!\n\n"
                    "Siz muvaffaqiyatli ro'yxatdan o'tgansiz va botdan foydalanishingiz mumkin."
                )
                bot.send_message(chat_id, welcome_text, parse_mode='HTML')
            else:
                # Custom registration link (The Mini App URL)
                # We can also use direct mini app button if org has tg_mini_app_url
                reg_url = f"https://islomcrm.uz/m/{org.org_link_code}/{org.org_slug}"
                
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🚀 Ro'yxatdan o'tish", web_app=types.WebAppInfo(url=reg_url)))
                
                text = (
                    f"Assalomu alaykum! <b>{org.yandex_park_name or org.org_name}</b> botiga xush kelibsiz.\n\n"
                    "Siz hali tizimdan ro'yxatdan o'tmagansiz. To'lovlarni amalga oshirish va balansni nazorat qilish uchun "
                    "pastdagi tugma orqali Mini App-ga kiring va ro'yxatdan o'ting."
                )
                bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=markup)
