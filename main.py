# === IMPORTLAR ===
import io
import os
import time
from datetime import datetime, date
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.utils import executor
from keep_alive import keep_alive
from database import (
    init_db,
    add_user,
    get_user_count,
    add_kino_code,
    get_kino_by_code,
    get_all_codes,
    delete_kino_code,
    get_code_stat,
    increment_stat,
    get_all_user_ids,
    update_anime_code,
    get_today_users
)


# === YUKLAMALAR ===
load_dotenv()
keep_alive()

API_TOKEN = os.getenv("API_TOKEN")
CHANNELS = []
MAIN_CHANNELS = []
BOT_USERNAME = os.getenv("BOT_USERNAME")

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

async def make_subscribe_markup(code):
    keyboard = InlineKeyboardMarkup(row_width=1)
    for channel in CHANNELS:
        try:
            invite_link = await bot.create_chat_invite_link(channel.strip())
            keyboard.add(InlineKeyboardButton("📢 Obuna bo‘lish", url=invite_link.invite_link))
        except Exception as e:
            print(f"❌ Link yaratishda xatolik: {channel} -> {e}")
    keyboard.add(InlineKeyboardButton("✅ Tekshirish", callback_data=f"check_sub:{code}"))
    return keyboard

ADMINS = {6486825926, 6549594161}

# === HOLATLAR ===

# Adminlar uchun barcha holatlar
class AdminStates(StatesGroup):
    waiting_for_kino_data = State()
    waiting_for_delete_code = State()
    waiting_for_stat_code = State()
    waiting_for_broadcast_data = State()
    waiting_for_admin_id = State()  
    waiting_for_user_list = State()

# Admin reply (javob) uchun holat
class AdminReplyStates(StatesGroup):
    waiting_for_reply_message = State()

# Kod tahrirlash uchun holatlar
class EditCode(StatesGroup):
    WaitingForOldCode = State()
    WaitingForNewCode = State()
    WaitingForNewTitle = State()

# Foydalanuvchi bilan chatlashish holati
class UserStates(StatesGroup):
    waiting_for_admin_message = State()

# Qidiruv (masalan, anime nomi bo‘yicha)
class SearchStates(StatesGroup):
    waiting_for_anime_name = State()

# Post yuborish jarayoni
class PostStates(StatesGroup):
    waiting_for_image = State()
    waiting_for_title = State()
    waiting_for_link = State()
    
class KanalStates(StatesGroup):
    waiting_for_channel = State()

# === OBUNA TEKSHIRISH FUNKSIYASI ===
async def get_unsubscribed_channels(user_id):
    unsubscribed = []
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(channel.strip(), user_id)
            if member.status not in ["member", "administrator", "creator"]:
                unsubscribed.append(channel)
        except Exception as e:
            print(f"❗ Obuna tekshirishda xatolik: {channel} -> {e}")
            unsubscribed.append(channel)
    return unsubscribed


# === OBUNA TEKSHIRISH FUNKSIYASI ===
async def is_user_subscribed(user_id):
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(channel.strip(), user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception as e:
            print(f"❗ Obuna holatini aniqlab bo‘lmadi: {channel} -> {e}")
            return False
    return True

# === BARCHA KANALLAR UCHUN OBUNA MARKUP ===
async def make_full_subscribe_markup(code):
    markup = InlineKeyboardMarkup(row_width=1)
    for ch in CHANNELS:
        try:
            channel = await bot.get_chat(ch.strip())
            invite_link = channel.invite_link or (await channel.export_invite_link())
            markup.add(InlineKeyboardButton(f"➕ {channel.title}", url=invite_link))
        except Exception as e:
            print(f"❗ Kanalni olishda xatolik: {ch} -> {e}")
    markup.add(InlineKeyboardButton("✅ Tekshirish", callback_data=f"checksub:{code}"))
    return markup

# === /start HANDLER – to‘liq versiya (statistika bilan) ===
@dp.message_handler(commands=['start'])
async def start_handler(message: types.Message):
    await add_user(message.from_user.id)
    args = message.get_args()

    if args and args.isdigit():
        code = args
        await increment_stat(code, "init")
        await increment_stat(code, "searched")

        unsubscribed = await get_unsubscribed_channels(message.from_user.id)
        if unsubscribed:
            markup = await make_full_subscribe_markup(code)
            await message.answer(
                "❗ Animeni olishdan oldin quyidagi homiy kanal(lar)ga obuna bo‘ling:",
                reply_markup=markup
            )
        else:
            await send_reklama_post(message.from_user.id, code)
            await increment_stat(code, "searched")
        return

    # === Oddiy /start ===
    if message.from_user.id in ADMINS:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("➕ Anime qo‘shish")
        kb.add("📊 Statistika", "📈 Kod statistikasi")
        kb.add("❌ Kodni o‘chirish", "📄 Kodlar ro‘yxati")
        kb.add("✏️ Kodni tahrirlash", "📤 Post qilish")
        kb.add("📢 Habar yuborish", "📘 Qo‘llanma")
        kb.add("➕ Admin qo‘shish", "📡 Kanal boshqaruvi")
        await message.answer("👮‍♂️ Admin panel:", reply_markup=kb)
    else:
        kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        kb.add(
            KeyboardButton("🎞 Barcha animelar"),
            KeyboardButton("✉️ Admin bilan bog‘lanish")
        )
        await message.answer("✨", reply_markup=kb)

# === TEKSHIRUV CALLBACK – faqat obuna bo‘lmaganlar uchun ===
@dp.callback_query_handler(lambda c: c.data.startswith("checksub:"))
async def check_subscription_callback(call: CallbackQuery):
    code = call.data.split(":")[1]
    unsubscribed = await get_unsubscribed_channels(call.from_user.id)

    if unsubscribed:
        markup = InlineKeyboardMarkup(row_width=1)
        for ch in unsubscribed:
            try:
                channel = await bot.get_chat(ch.strip())
                invite_link = channel.invite_link or (await channel.export_invite_link())
                markup.add(InlineKeyboardButton(f"➕ {channel.title}", url=invite_link))
            except Exception as e:
                print(f"❗ Kanalni olishda xatolik: {ch} -> {e}")
        markup.add(InlineKeyboardButton("✅ Yana tekshirish", callback_data=f"checksub:{code}"))
        await call.message.edit_text("❗ Obuna bo‘lmagan kanal(lar):", reply_markup=markup)
    else:
        await call.message.delete()
        await send_reklama_post(call.from_user.id, code)
        await increment_stat(code, "searched")
# === 🎞 Barcha animelar tugmasi
@dp.message_handler(lambda m: m.text == "🎞 Barcha animelar")
async def show_all_animes(message: types.Message):
    kodlar = await get_all_codes()
    if not kodlar:
        await message.answer("⛔️ Hozircha animelar yoʻq.")
        return

    kodlar = sorted(kodlar, key=lambda x: int(x["code"]))  # raqam bo‘yicha tartib
    text = "📄 *Barcha animelar:*\n\n"
    for row in kodlar:
        text += f"`{row['code']}` – *{row['title']}*\n"

    await message.answer(text, parse_mode="Markdown")

# === ✉️ Admin bilan bog‘lanish ===
@dp.message_handler(lambda m: m.text == "✉️ Admin bilan bog‘lanish")
async def contact_admin(message: types.Message):
    await UserStates.waiting_for_admin_message.set()
    await message.answer("✍️ Adminlarga yubormoqchi bo‘lgan xabaringizni yozing.\n\n❌ Bekor qilish uchun '❌ Bekor qilish' tugmasini bosing.")

@dp.message_handler(state=UserStates.waiting_for_admin_message)
async def forward_to_admins(message: types.Message, state: FSMContext):
    await state.finish()
    user = message.from_user

    for admin_id in ADMINS:
        try:
            keyboard = InlineKeyboardMarkup().add(
                InlineKeyboardButton("✉️ Javob yozish", callback_data=f"reply_user:{user.id}")
            )

            await bot.send_message(
                admin_id,
                f"📩 <b>Yangi xabar:</b>\n\n"
                f"<b>👤 Foydalanuvchi:</b> {user.full_name} | <code>{user.id}</code>\n"
                f"<b>💬 Xabar:</b> {message.text}",
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except Exception as e:
            print(f"Adminga yuborishda xatolik: {e}")

    await message.answer("✅ Xabaringiz yuborildi. Tez orada admin siz bilan bog‘lanadi.")

@dp.callback_query_handler(lambda c: c.data.startswith("reply_user:"), user_id=ADMINS)
async def start_admin_reply(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    await state.update_data(reply_user_id=user_id)
    await AdminReplyStates.waiting_for_reply_message.set()
    await callback.message.answer("✍️ Endi foydalanuvchiga yubormoqchi bo‘lgan xabaringizni yozing.")
    await callback.answer()

@dp.message_handler(state=AdminReplyStates.waiting_for_reply_message, user_id=ADMINS)
async def send_admin_reply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("reply_user_id")

    try:
        await bot.send_message(user_id, f"✉️ Admindan javob:\n\n{message.text}")
        await message.answer("✅ Javob foydalanuvchiga yuborildi.")
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")
    finally:
        await state.finish()

# === 📡 KANAL BOSHQARUVI ===
@dp.message_handler(lambda m: m.text == "📡 Kanal boshqaruvi", user_id=ADMINS)
async def kanal_boshqaruvi(message: types.Message):
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("🔗 Majburiy obuna", callback_data="channel_type:sub"),
        InlineKeyboardButton("📌 Asosiy kanallar", callback_data="channel_type:main")
    )
    await message.answer("📡 Qaysi kanal turini boshqarasiz?", reply_markup=kb)


# === TUR TANLASH ===
@dp.callback_query_handler(lambda c: c.data.startswith("channel_type:"), user_id=ADMINS)
async def select_channel_type(callback: types.CallbackQuery, state: FSMContext):
    ctype = callback.data.split(":")[1]

    # Tanlangan turini saqlaymiz
    await state.update_data(channel_type=ctype)

    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("➕ Kanal qo‘shish", callback_data="action:add"),
        InlineKeyboardButton("📋 Kanal ro‘yxati", callback_data="action:list")
    )
    kb.add(
        InlineKeyboardButton("❌ Kanal o‘chirish", callback_data="action:delete"),
        InlineKeyboardButton("⬅️ Orqaga", callback_data="action:back")
    )

    if ctype == "sub":
        await callback.message.edit_text("📡 Majburiy obuna kanallari menyusi:", reply_markup=kb)
    else:
        await callback.message.edit_text("📌 Asosiy kanallar menyusi:", reply_markup=kb)

    await callback.answer()


# === ACTION TANLASH ===
@dp.callback_query_handler(lambda c: c.data.startswith("action:"), user_id=ADMINS)
async def channel_actions(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]
    data = await state.get_data()
    ctype = data.get("channel_type")

    if not ctype:
        await callback.answer("❗ Avval kanal turini tanlang.")
        return

    if action == "add":
        await KanalStates.waiting_for_channel.set()
        await callback.message.answer("📎 Kanal username yuboring (masalan: @mychannel):")

    elif action == "list":
        if ctype == "sub":
            if not CHANNELS:
                await callback.message.answer("📭 Majburiy obuna kanali yo‘q.")
            else:
                text = "📋 Majburiy obuna kanallari:\n\n"
                for i, ch in enumerate(CHANNELS, 1):
                    text += f"{i}. {ch}\n"
                await callback.message.answer(text)
        else:
            if not MAIN_CHANNELS:
                await callback.message.answer("📭 Asosiy kanal yo‘q.")
            else:
                text = "📌 Asosiy kanallar:\n\n"
                for i, ch in enumerate(MAIN_CHANNELS, 1):
                    text += f"{i}. {ch}\n"
                await callback.message.answer(text)

    elif action == "delete":
        kb = InlineKeyboardMarkup()
        if ctype == "sub":
            if not CHANNELS:
                await callback.message.answer("📭 Majburiy obuna kanali yo‘q.")
                return
            for ch in CHANNELS:
                kb.add(InlineKeyboardButton(f"O‘chirish: {ch}", callback_data=f"delch:{ch}"))
        else:
            if not MAIN_CHANNELS:
                await callback.message.answer("📭 Asosiy kanal yo‘q.")
                return
            for ch in MAIN_CHANNELS:
                kb.add(InlineKeyboardButton(f"O‘chirish: {ch}", callback_data=f"delmain:{ch}"))

        await callback.message.answer("❌ Qaysi kanalni o‘chirmoqchisiz?", reply_markup=kb)

    elif action == "back":
        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton("🔗 Majburiy obuna", callback_data="channel_type:sub"),
            InlineKeyboardButton("📌 Asosiy kanallar", callback_data="channel_type:main")
        )
        await callback.message.edit_text("📡 Qaysi kanal turini boshqarasiz?", reply_markup=kb)

    await callback.answer()


# === ➕ KANAL QO‘SHISH (STATE) ===
@dp.message_handler(state=KanalStates.waiting_for_channel, user_id=ADMINS)
async def add_channel_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ctype = data.get("channel_type")

    channel = message.text.strip()
    if not channel.startswith("@"):
        await message.answer("❗ Kanal @ bilan boshlanishi kerak.")
        return

    if ctype == "sub":
        if channel in CHANNELS:
            await message.answer("ℹ️ Bu kanal allaqachon ro‘yxatda bor.")
        else:
            CHANNELS.append(channel)
            await message.answer(f"✅ {channel} qo‘shildi (majburiy obuna).")
    else:
        if channel in MAIN_CHANNELS:
            await message.answer("ℹ️ Bu kanal allaqachon ro‘yxatda bor.")
        else:
            MAIN_CHANNELS.append(channel)
            await message.answer(f"✅ {channel} qo‘shildi (asosiy kanal).")

    await state.finish()


# === ❌ O‘CHIRISH HANDLERLARI ===
@dp.callback_query_handler(lambda c: c.data.startswith("delch:"), user_id=ADMINS)
async def delete_channel_confirm_sub(callback: types.CallbackQuery):
    channel = callback.data.split(":", 1)[1]
    if channel in CHANNELS:
        CHANNELS.remove(channel)
        await callback.message.edit_text(f"✅ {channel} (majburiy obuna) o‘chirildi.")
    else:
        await callback.message.edit_text("⚠️ Bu kanal topilmadi.")
    await callback.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("delmain:"), user_id=ADMINS)
async def delete_channel_confirm_main(callback: types.CallbackQuery):
    channel = callback.data.split(":", 1)[1]
    if channel in MAIN_CHANNELS:
        MAIN_CHANNELS.remove(channel)
        await callback.message.edit_text(f"✅ {channel} (asosiy kanal) o‘chirildi.")
    else:
        await callback.message.edit_text("⚠️ Bu kanal topilmadi.")
    await callback.answer()



# === 📋 KANAL RO‘YXATI ===
@dp.message_handler(lambda m: m.text == "📋 Kanal ro‘yxati", user_id=ADMINS)
async def list_channels(message: types.Message):
    if not CHANNELS:
        await message.answer("📭 Hozircha hech qanday kanal yo‘q.")
        return
    text = "📋 Majburiy obuna kanallari:\n\n"
    for i, ch in enumerate(CHANNELS, 1):
        text += f"{i}. {ch}\n"
    await message.answer(text)


# === ❌ KANAL O‘CHIRISH ===
@dp.message_handler(lambda m: m.text == "❌ Kanal o‘chirish", user_id=ADMINS)
async def delete_channel_start(message: types.Message):
    if not CHANNELS:
        await message.answer("📭 Hozircha hech qanday kanal yo‘q.")
        return
    kb = InlineKeyboardMarkup()
    for ch in CHANNELS:
        kb.add(InlineKeyboardButton(f"O‘chirish: {ch}", callback_data=f"delch:{ch}"))
    await message.answer("❌ Qaysi kanalni o‘chirmoqchisiz?", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("delch:"), user_id=ADMINS)
async def delete_channel_confirm(callback: types.CallbackQuery):
    channel = callback.data.split(":", 1)[1]
    if channel in CHANNELS:
        CHANNELS.remove(channel)
        await callback.message.edit_text(f"✅ {channel} o‘chirildi.")
    else:
        await callback.message.edit_text("⚠️ Bu kanal topilmadi.")
    await callback.answer()
# ⬅️ Orqaga qaytish (Admin panelga)
@dp.message_handler(lambda m: m.text == "⬅️ Orqaga", user_id=ADMINS)
async def back_to_admin_menu(message: types.Message):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ Anime qo‘shish")
    kb.add("📊 Statistika", "📈 Kod statistikasi")
    kb.add("❌ Kodni o‘chirish", "📄 Kodlar ro‘yxati")
    kb.add("✏️ Kodni tahrirlash", "📤 Post qilish")
    kb.add("📢 Habar yuborish", "📘 Qo‘llanma")
    kb.add("➕ Admin qo‘shish", "📡 Kanal boshqaruvi")
    await message.answer("🔙 Admin menyu:", reply_markup=kb)

# ==== QO‘LLANMA MENYUSI ====
@dp.message_handler(lambda m: m.text == "📘 Qo‘llanma")
async def qollanma(message: types.Message):
    kb = (
        InlineKeyboardMarkup(row_width=1)
        .add(InlineKeyboardButton("📥 1. Anime qo‘shish", callback_data="help_add"))
        .add(InlineKeyboardButton("📡 2. Kanal yaratish", callback_data="help_channel"))
        .add(InlineKeyboardButton("🆔 3. Reklama ID olish", callback_data="help_id"))
        .add(InlineKeyboardButton("🔁 4. Kod ishlashi", callback_data="help_code"))
        .add(InlineKeyboardButton("❓ 5. Savol-javob", callback_data="help_faq"))
    )
    await message.answer("📘 Qanday yordam kerak?", reply_markup=kb)


# ==== MATNLAR ====
HELP_TEXTS = {
    "help_add": (
        "📥 *Anime qo‘shish*\n\n"
        "`KOD @kanal REKLAMA_ID POST_SONI ANIME_NOMI`\n\n"
        "Misol: `91 @MyKino 4 12 Naruto`\n\n"
        "• *Kod* – foydalanuvchi yozadigan raqam\n"
        "• *@kanal* – server kanal username\n"
        "• *REKLAMA_ID* – post ID raqami (raqam)\n"
        "• *POST_SONI* – nechta qism borligi\n"
        "• *ANIME_NOMI* – ko‘rsatiladigan sarlavha\n\n"
        "📩 Endi formatda xabar yuboring:"
    ),
    "help_channel": (
        "📡 *Kanal yaratish*\n\n"
        "1. 2 ta kanal yarating:\n"
        "   • *Server kanal* – post saqlanadi\n"
        "   • *Reklama kanal* – bot ulashadi\n\n"
        "2. Har ikkasiga botni admin qiling\n\n"
        "3. Kanalni public (@username) qiling"
    ),
    "help_id": (
        "🆔 *Reklama ID olish*\n\n"
        "1. Server kanalga post joylang\n\n"
        "2. Post ustiga bosing → *Share* → *Copy link*\n\n"
        "3. Link oxiridagi sonni oling\n\n"
        "Misol: `t.me/MyKino/4` → ID = `4`"
    ),
    "help_code": (
        "🔁 *Kod ishlashi*\n\n"
        "1. Foydalanuvchi kod yozadi (masalan: `91`)\n\n"
        "2. Obuna tekshiriladi → reklama post yuboriladi\n\n"
        "3. Tugmalar orqali qismlarni ochadi"
    ),
    "help_faq": (
        "❓ *Tez-tez so‘raladigan savollar*\n\n"
        "• *Kodni qanday ulashaman?*\n"
        "  `https://t.me/<BOT_USERNAME>?start=91`\n\n"
        "• *Har safar yangi kanal kerakmi?*\n"
        "  – Yo‘q, bitta server kanal yetarli\n\n"
        "• *Kodni tahrirlash/o‘chirish mumkinmi?*\n"
        "  – Ha, admin menyuda ✏️ / ❌ tugmalari bor"
    )
}


# ==== CALLBACK: HAR BIR YORDAM SAHIFASI ====
@dp.callback_query_handler(lambda c: c.data.startswith("help_"))
async def show_help_page(callback: types.CallbackQuery):
    key = callback.data
    text = HELP_TEXTS.get(key, "❌ Ma'lumot topilmadi.")
    
    # Ortga tugmasi
    kb = InlineKeyboardMarkup().add(
        InlineKeyboardButton("⬅️ Ortga", callback_data="back_help")
    )
    
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        # Agar matn o'zgartirilmayotgan bo'lsa (masalan, rasmli xabar bo'lsa)
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        await callback.message.delete()  # Eski xabarni o'chirish
    finally:
        await callback.answer()


# ==== ORTGA TUGMASI ====
@dp.callback_query_handler(lambda c: c.data == "back_help")
async def back_to_qollanma(callback: types.CallbackQuery):
    kb = (
        InlineKeyboardMarkup(row_width=1)
        .add(InlineKeyboardButton("📥 1. Anime qo‘shish", callback_data="help_add"))
        .add(InlineKeyboardButton("📡 2. Kanal yaratish", callback_data="help_channel"))
        .add(InlineKeyboardButton("🆔 3. Reklama ID olish", callback_data="help_id"))
        .add(InlineKeyboardButton("🔁 4. Kod ishlashi", callback_data="help_code"))
        .add(InlineKeyboardButton("❓ 5. Savol-javob", callback_data="help_faq"))
    )
    
    try:
        await callback.message.edit_text("📘 Qanday yordam kerak?", reply_markup=kb)
    except Exception as e:
        await callback.message.answer("📘 Qanday yordam kerak?", reply_markup=kb)
        await callback.message.delete()
    finally:
        await callback.answer()
    
# === Admin qo'shish===
@dp.message_handler(lambda m: m.text == "➕ Admin qo‘shish", user_id=ADMINS)
async def add_admin_start(message: types.Message):
    await message.answer("🆔 Yangi adminning Telegram ID raqamini yuboring.")
    await AdminStates.waiting_for_admin_id.set()

@dp.message_handler(state=AdminStates.waiting_for_admin_id, user_id=ADMINS)
async def add_admin_process(message: types.Message, state: FSMContext):
    await state.finish()
    text = message.text.strip()
    
    if not text.isdigit():
        await message.answer("❗ Faqat raqam yuboring (Telegram user ID).")
        return

    new_admin_id = int(text)
    if new_admin_id in ADMINS:
        await message.answer("ℹ️ Bu foydalanuvchi allaqachon admin.")
        return

    ADMINS.add(new_admin_id)
    await message.answer(f"✅ <code>{new_admin_id}</code> admin sifatida qo‘shildi.", parse_mode="HTML")

    try:
        await bot.send_message(new_admin_id, "✅ Siz botga admin sifatida qo‘shildingiz.")
    except:
        await message.answer("⚠️ Yangi adminga habar yuborib bo‘lmadi.")

# === Kod statistikasi
@dp.message_handler(lambda m: m.text == "📈 Kod statistikasi")
async def ask_stat_code(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("📥 Kod raqamini yuboring:")
    await AdminStates.waiting_for_stat_code.set()

@dp.message_handler(state=AdminStates.waiting_for_stat_code)
async def show_code_stat(message: types.Message, state: FSMContext):
    await state.finish()
    code = message.text.strip()
    if not code:
        await message.answer("❗ Kod yuboring.")
        return
    stat = await get_code_stat(code)
    if not stat:
        await message.answer("❗ Bunday kod statistikasi topilmadi.")
        return

    await message.answer(
        f"📊 <b>{code} statistikasi:</b>\n"
        f"🔍 Qidirilgan: <b>{stat['searched']}</b>\n"
        f"👁 Ko‘rilgan: <b>{stat['viewed']}</b>",
        parse_mode="HTML"
    )

@dp.message_handler(lambda message: message.text == "✏️ Kodni tahrirlash", user_id=ADMINS)
async def edit_code_start(message: types.Message):
    await message.answer("Qaysi kodni tahrirlashni xohlaysiz? (eski kodni yuboring)")
    await EditCode.WaitingForOldCode.set()

# --- Eski kodni qabul qilish ---
@dp.message_handler(state=EditCode.WaitingForOldCode, user_id=ADMINS)
async def get_old_code(message: types.Message, state: FSMContext):
    code = message.text.strip()
    post = await get_kino_by_code(code)
    if not post:
        await message.answer("❌ Bunday kod topilmadi. Qaytadan urinib ko‘ring.")
        return
    await state.update_data(old_code=code)
    await message.answer(f"🔎 Kod: {code}\n📌 Nomi: {post['title']}\n\nYangi kodni yuboring:")
    await EditCode.WaitingForNewCode.set()

# --- Yangi kodni olish ---
@dp.message_handler(state=EditCode.WaitingForNewCode, user_id=ADMINS)
async def get_new_code(message: types.Message, state: FSMContext):
    await state.update_data(new_code=message.text.strip())
    await message.answer("Yangi nomini yuboring:")
    await EditCode.WaitingForNewTitle.set()

# --- Yangi nomni olish va yangilash ---
@dp.message_handler(state=EditCode.WaitingForNewTitle, user_id=ADMINS)
async def get_new_title(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        await update_anime_code(
            data['old_code'],
            data['new_code'],
            message.text.strip()
        )
        await message.answer("✅ Kod va nom muvaffaqiyatli tahrirlandi.")
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi:\n{e}")
    finally:
        await state.finish()
        
# === Oddiy raqam yuborilganda
@dp.message_handler(lambda message: message.text.isdigit())
async def handle_code_message(message: types.Message):
    code = message.text
    if not await is_user_subscribed(message.from_user.id):
        markup = await make_subscribe_markup(code)
        await message.answer("❗ Kino olishdan oldin quyidagi kanal(lar)ga obuna bo‘ling:", reply_markup=markup)
    else:
        await increment_stat(code, "init")
        await increment_stat(code, "searched")
        await send_reklama_post(message.from_user.id, code)
        await increment_stat(code, "viewed")

# === 📢 Habar yuborish
@dp.message_handler(lambda m: m.text == "📢 Habar yuborish")
async def ask_broadcast_info(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    await AdminStates.waiting_for_broadcast_data.set()
    await message.answer("📨 Habar yuborish uchun format:\n`@kanal xabar_id`", parse_mode="Markdown")

@dp.message_handler(state=AdminStates.waiting_for_broadcast_data)
async def send_forward_only(message: types.Message, state: FSMContext):
    await state.finish()
    parts = message.text.strip().split()
    if len(parts) != 2:
        await message.answer("❗ Format noto‘g‘ri. Masalan: `@kanalim 123`")
        return

    channel_username, msg_id = parts
    if not msg_id.isdigit():
        await message.answer("❗ Xabar ID raqam bo‘lishi kerak.")
        return

    msg_id = int(msg_id)
    users = await get_all_user_ids()  # Foydalanuvchilar ro‘yxati

    success = 0
    fail = 0

    for user_id in users:
        try:
            await bot.forward_message(
                chat_id=user_id,
                from_chat_id=channel_username,
                message_id=msg_id
            )
            success += 1
        except Exception as e:
            print(f"Xatolik {user_id} uchun: {e}")
            fail += 1

    await message.answer(f"✅ Yuborildi: {success} ta\n❌ Xatolik: {fail} ta")

# === Obuna tekshirish callback
@dp.callback_query_handler(lambda c: c.data.startswith("check_sub:"))
async def check_sub_callback(callback_query: types.CallbackQuery):
    code = callback_query.data.split(":")[1]
    user_id = callback_query.from_user.id

    not_subscribed = []
    buttons = []

    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ['left', 'kicked']:
                not_subscribed.append(channel)
                invite_link = await bot.create_chat_invite_link(channel)
                buttons.append([
                    InlineKeyboardButton("🔔 Obuna bo‘lish", url=invite_link.invite_link)
                ])
        except Exception as e:
            print(f"❌ Obuna tekshiruv xatosi: {channel} -> {e}")
            continue

    if not_subscribed:
        buttons.append([InlineKeyboardButton("✅ Tekshirish", callback_data=f"check_sub:{code}")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback_query.message.edit_text(
            "❗ Hali ham barcha kanallarga obuna bo‘lmagansiz. Iltimos, barchasiga obuna bo‘ling:",
            reply_markup=keyboard
        )
    else:
        await callback_query.message.edit_text("✅ Obuna muvaffaqiyatli tekshirildi!")
        await send_reklama_post(user_id, code)

# === Reklama postni yuborish
async def send_reklama_post(user_id, code):
    data = await get_kino_by_code(code)
    if not data:
        await bot.send_message(user_id, "❌ Kod topilmadi.")
        return

    channel, reklama_id, post_count = data["channel"], data["message_id"], data["post_count"]

    buttons = [InlineKeyboardButton(str(i), callback_data=f"kino:{code}:{i}") for i in range(1, post_count + 1)]
    keyboard = InlineKeyboardMarkup(row_width=5)
    keyboard.add(*buttons)

    try:
        await bot.copy_message(user_id, channel, reklama_id - 1, reply_markup=keyboard)
    except:
        await bot.send_message(user_id, "❌ Reklama postni yuborib bo‘lmadi.")

# === Tugma orqali kino yuborish
@dp.callback_query_handler(lambda c: c.data.startswith("kino:"))
async def kino_button(callback: types.CallbackQuery):
    _, code, number = callback.data.split(":")
    number = int(number)

    result = await get_kino_by_code(code)
    if not result:
        await callback.message.answer("❌ Kod topilmadi.")
        return

    channel, base_id, post_count = result["channel"], result["message_id"], result["post_count"]

    if number > post_count:
        await callback.answer("❌ Bunday post yo‘q!", show_alert=True)
        return

    await bot.copy_message(callback.from_user.id, channel, base_id + number - 1)
    await callback.answer()

# === ➕ Anime qo‘shish
@dp.message_handler(lambda m: m.text == "➕ Anime qo‘shish")
async def add_start(message: types.Message):
    if message.from_user.id in ADMINS:
        await AdminStates.waiting_for_kino_data.set()
        await message.answer("📝 Format: `KOD @kanal REKLAMA_ID POST_SONI ANIME_NOMI`\nMasalan: `91 @MyKino 4 12 naruto`", parse_mode="Markdown")

@dp.message_handler(state=AdminStates.waiting_for_kino_data)
async def add_kino_handler(message: types.Message, state: FSMContext):
    rows = message.text.strip().split("\n")
    successful = 0
    failed = 0
    for row in rows:
        parts = row.strip().split()
        if len(parts) < 5:
            failed += 1
            continue

        code, server_channel, reklama_id, post_count = parts[:4]
        title = " ".join(parts[4:])

        if not (code.isdigit() and reklama_id.isdigit() and post_count.isdigit()):
            failed += 1
            continue

        reklama_id = int(reklama_id)
        post_count = int(post_count)

        await add_kino_code(code, server_channel, reklama_id + 1, post_count, title)

        download_btn = InlineKeyboardMarkup().add(
            InlineKeyboardButton("✨Yuklab olish✨", url=f"https://t.me/{BOT_USERNAME}?start={code}")
        )

        try:
            for ch in MAIN_CHANNELS:
                await bot.copy_message(
                    chat_id=ch,
                    from_chat_id=server_channel,
                    message_id=reklama_id,
                    reply_markup=download_btn
        ) 
            successful += 1
        except:
            failed += 1

    await message.answer(f"✅ Yangi kodlar qo‘shildi:\n\n✅ Muvaffaqiyatli: {successful}\n❌ Xatolik: {failed}")
    await state.finish()

@dp.message_handler(lambda m: m.text == "📄 Kodlar ro‘yxati")
async def show_all_animes(message: types.Message):
    kodlar = await get_all_codes()
    if not kodlar:
        await message.answer("Ba'zada hech qanday kodlar yo'q!")
        return

    # Kodlarni raqam bo‘yicha tartiblash
    kodlar = sorted(kodlar, key=lambda x: int(x["code"]))

    # Har 100 tadan bo‘lib yuborish
    chunk_size = 100
    for i in range(0, len(kodlar), chunk_size):
        chunk = kodlar[i:i + chunk_size]
        text = "📄 *Barcha animelar:*\n\n"
        for row in chunk:
            text += f"`{row['code']}` – *{row['title']}*\n"

        await message.answer(text, parse_mode="Markdown")
        
# 📊 Statistika
@dp.message_handler(lambda m: m.text == "📊 Statistika")
async def stats(message: types.Message):
    # ⏱ Pingni o'lchash
    from database import db_pool
    async with db_pool.acquire() as conn:
        start = time.perf_counter()
        await conn.fetch("SELECT 1;")  # oddiy so'rov
        ping = (time.perf_counter() - start) * 1000  # ms ga aylantiramiz

    # 📂 Kodlar va foydalanuvchilar soni
    kodlar = await get_all_codes()
    foydalanuvchilar = await get_user_count()

    # 📅 Bugun qo'shilgan foydalanuvchilar
    today_users = await get_today_users()

    # 📊 Xabar
    text = (
        f"💡 O'rtacha yuklanish: {ping:.2f} ms\n\n"
        f"👥 Foydalanuvchilar: {foydalanuvchilar} ta\n\n"
        f"📂 Barcha yuklangan animelar: {len(kodlar)} ta\n\n"
        f"📅 Bugun qo'shilgan foydalanuvchilar: {today_users} ta"
    )
    await message.answer(text)

    
@dp.message_handler(lambda m: m.text == "📤 Post qilish")
async def start_post_process(message: types.Message):
    if message.from_user.id in ADMINS:
        await PostStates.waiting_for_image.set()
        await message.answer("🖼 Iltimos, post uchun rasm yuboring.")
        
@dp.message_handler(content_types=types.ContentType.PHOTO, state=PostStates.waiting_for_image)
async def get_post_image(message: types.Message, state: FSMContext):
    photo = message.photo[-1].file_id
    await state.update_data(photo=photo)
    await PostStates.waiting_for_title.set()
    await message.answer("📌 Endi rasm ostiga yoziladigan nomni yuboring.")
@dp.message_handler(state=PostStates.waiting_for_title)
async def get_post_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await PostStates.waiting_for_link.set()
    await message.answer("🔗 Yuklab olish uchun havolani yuboring.")
@dp.message_handler(state=PostStates.waiting_for_link)
async def get_post_link(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photo = data.get("photo")
    title = data.get("title")
    link = message.text.strip()

    button = InlineKeyboardMarkup().add(
        InlineKeyboardButton("✨Yuklab olish✨", url=link)
    )

    try:
        await bot.send_photo(
            chat_id=message.chat.id,
            photo=photo,
            caption=title,
            reply_markup=button
        )
        await message.answer("✅ Post muvaffaqiyatli yuborildi.")
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {e}")
    finally:
        await state.finish()


# === ❌ Kodni o‘chirish
@dp.message_handler(lambda m: m.text == "❌ Kodni o‘chirish")
async def ask_delete_code(message: types.Message):
    if message.from_user.id in ADMINS:
        await AdminStates.waiting_for_delete_code.set()
        await message.answer("🗑 Qaysi kodni o‘chirmoqchisiz? Kodni yuboring.")

@dp.message_handler(state=AdminStates.waiting_for_delete_code)
async def delete_code_handler(message: types.Message, state: FSMContext):
    await state.finish()
    code = message.text.strip()
    if not code.isdigit():
        await message.answer("❗ Noto‘g‘ri format. Kod raqamini yuboring.")
        return
    deleted = await delete_kino_code(code)
    if deleted:
        await message.answer(f"✅ Kod {code} o‘chirildi.")
    else:
        await message.answer("❌ Kod topilmadi yoki o‘chirib bo‘lmadi.")

# === START ===
async def on_startup(dp):
    await init_db()
    print("✅ PostgreSQL bazaga ulandi!")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)    
