import os, sys, json, django
from pathlib import Path

from dotenv import load_dotenv
from aiogram import Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
    WebAppInfo,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from utils.myCustomFilter import FromGen, generate_btn
from bot_logger import get_bot_logger, LogCategory
import uuid

load_dotenv()
TOKEN = os.getenv('TOKEN')

# ═══ Mini-app base URL — loaded from .env ═══
OUTAGE_WEBAPP_URL = os.getenv('OUTAGE_WEBAPP_URL')

#________________________________________working_with_path____________________________________________
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '../'))
sys.path.append(project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "eeuBotProject.settings")
django.setup()
#________________________________________/path_______________________________________________________


class PlannedInterruptionForm(StatesGroup):
    menu = State()


logger = get_bot_logger("planned_interruption_service")


class PlannedInterruptionService:
    service_name = "plannedInt"

    def __init__(self):
        self.service_name = PlannedInterruptionService.service_name
        self.router = Router()
        self.webapp_url = OUTAGE_WEBAPP_URL.rstrip('/') + '/'
        self.setup_handlers()

    def gen(self, callback: str, btn_group: str = "btn") -> str:
        """Generate unique callback data for this service"""
        return generate_btn(self.service_name, callback, btn_group)

    async def extra(self, state: FSMContext, event: str) -> dict:
        """Build the logger 'extra' dict from FSM state."""
        return {
            "catagory": event,
            "session_id": await state.get_value("session_id", "unknown"),
            "tg_id": await state.get_value("tg_id", "unknown"),
        }

    def setup_handlers(self):
        @self.router.callback_query(
            lambda call: call.data.lower().strip().casefold()
                         == "mainHandler$btn>planned interruption".casefold()
        )
        async def handle_planned_interruption(call: CallbackQuery, state: FSMContext):
            await call.answer()

            # ── service on/off switch (unchanged) ──
            service_path = Path(__file__).parent.parent / "services_status.json"
            with open(service_path, 'r', encoding='utf-8') as f:
                services = json.load(f)

            this_service = FromGen.get_callData(call.data)
            if services[this_service]["status"] == "disabled":
                if services[this_service]['message']:
                    await call.message.answer(services[this_service]['message'])
                return

            # ── FSM housekeeping: preserve last_interaction_time ──
            tg_id = str(call.from_user.id)
            session_id = str(uuid.uuid4())
            await state.update_data(session_id=session_id, tg_id=tg_id)
            logger.info(f"User {tg_id} entered the planned interruption service", extra=await self.extra(state, LogCategory.SERVICE_ENTRY))

            all_data = await state.get_data()
            last_interaction_time = all_data.get("last_interaction_time")
            session_id = all_data.get("session_id")
            tg_id = all_data.get("tg_id")
            await state.clear()
            updates = {"last_interaction_time": last_interaction_time}
            if session_id: updates["session_id"] = session_id
            if tg_id: updates["tg_id"] = tg_id
            await state.update_data(**updates)
            await state.set_state(PlannedInterruptionForm.menu)

            # ── 1) entry notice + Exit reply keyboard ──
            reply_keyboard = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="Exit")]],
                resize_keyboard=True
            )
            await call.message.answer(
                "🔌 You are now in the <b>Planned Interruption</b> service.\n",
   
                reply_markup=reply_keyboard
            )

            # ── 2) mini-app button ──
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="📅 View Outage Schedule",
                    web_app=WebAppInfo(url=self.webapp_url),   # opens INSIDE Telegram
                    # url=self.webapp_url                     # fallback: external browser
                )]
            ])
            await call.message.answer(
                "Tap the button below to open the live outage schedule:",
                reply_markup=markup
            )

#🏭 redEnd

#🏭 redEnd

#         @self.router.callback_query(lambda call: self.gen("today") in call.data)
#         async def handle_today_interruptions(call: CallbackQuery, state: FSMContext):
#             await call.answer()

#             # Get all data to preserve last_interaction_time
#             all_data = await state.get_data()
#             last_interaction_time = all_data.get("last_interaction_time")

#             # Clear state and restore last_interaction_time
#             await state.clear()
#             await state.update_data(last_interaction_time=last_interaction_time)

#             # Set state to viewing_today
#             await state.set_state(PlannedInterruptionForm.viewing_today)

#             reply_keyboard = ReplyKeyboardMarkup(
#                 keyboard=[[KeyboardButton(text="Exit")]],
#                 resize_keyboard=True
#             )

#             await call.message.answer("🔄 Fetching today's planned outages...", reply_markup=reply_keyboard)
#             # await call.message.answer("📢 No planned power interruptions found for the selected period.")


#             try:
#                 async with aiohttp.ClientSession() as session:
#                     async with session.get(
#                         url=self.TODAY_URL,
#                         timeout=aiohttp.ClientTimeout(total=45)
#                     ) as response:
#                         if response.status == 200:
#                             api_response = await response.json()
#                             data = api_response.get('data', [])
#                             print("Today's Data:",data)
#                             if data:
#                                 await self.format_and_send_interruptions(call.message, data)
#                             else:
#                                 await call.message.answer("No planned interruptions for today.")
#                         else:
#                             await call.message.answer("❌ Failed to fetch interruption data. Please try again later.")
#             except Exception as e:
#                 print ("Error fetching today's interruptions:", e)
#                 await call.message.answer("❌ Failed to fetch interruption data. Please try again later.")

#         @self.router.callback_query(lambda call: self.gen("future") in call.data)
#         async def handle_future_interruptions(call: CallbackQuery, state: FSMContext):
#             await call.answer()

#             # Get all data to preserve last_interaction_time
#             all_data = await state.get_data()
#             last_interaction_time = all_data.get("last_interaction_time")

#             # Clear state and restore last_interaction_time
#             await state.clear()
#             await state.update_data(last_interaction_time=last_interaction_time)

#             # Set state to viewing_future
#             await state.set_state(PlannedInterruptionForm.viewing_future)

#             reply_keyboard = ReplyKeyboardMarkup(
#                 keyboard=[[KeyboardButton(text="Exit")]],
#                 resize_keyboard=True
#             )
#             await call.message.answer("🔄 Fetching all planned outages...", reply_markup=reply_keyboard)
#             # await call.message.answer("📢 No planned power interruptions found for the selected period.")


#             # try:
#             async with aiohttp.ClientSession() as session:
#                 async with session.get(
#                     url=self.FUTURE_URL,
#                     timeout=aiohttp.ClientTimeout(total=45)
#                 ) as response:
#                     if response.status == 200:
#                         api_response = await response.json()
#                         data = api_response.get('data', [])
#                         print(data)
#                         if data:
#                             await self.format_and_send_interruptions(call.message, data)
#                         else:
#                             await call.message.answer("No future planned interruptions found.")
#                     else:
#                         await call.message.answer("❌ Failed to fetch interruption data. Please try again later.")
#             # except Exception as e:
#             #     keyboard = [[KeyboardButton(text = "Exit")]]
#             #     markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
#             #     await call.message.answer("❌ Failed to fetch interruption data. Please try again later.",reply_markup=markup)

#     async def format_and_send_interruptions(self, message: Message, data: any):
#         """Format and send interruption data to user in a single continuous message."""
        
#         # 🛡️ BULLETPROOF DATA PARSING (Kept from previous fix)
#         if isinstance(data, str):
#             try:
#                 parsed = json.loads(data)
#                 data = parsed.get("data", parsed) if isinstance(parsed, dict) else parsed
#             except json.JSONDecodeError:
#                 try:
#                     parsed = ast.literal_eval(data)
#                     data = parsed.get("data", parsed) if isinstance(parsed, dict) else parsed
#                 except Exception:
#                     await message.answer("❌ Failed to parse interruption data from server.")
#                     return
                    
#         elif isinstance(data, dict) and "data" in data:
#             data = data["data"]
            
#         if isinstance(data, list) and len(data) > 0 and isinstance(data[0], str):
#             data = [json.loads(item) for item in data if item]

#         if not isinstance(data, list):
#             await message.answer("❌ Invalid data format received from server.")
#             return

#         if not data:
#             await message.answer("📢 No planned power interruptions found for the selected period.")
#             return

#         # Add Exit reply button
#         reply_keyboard = ReplyKeyboardMarkup(
#             keyboard=[[KeyboardButton(text="Exit")]],
#             resize_keyboard=True
#         )

#         # 🟢 Sort data by date from recent to old (descending order)
#         sorted_data = sorted(data, key=lambda item: item.get('date', ''), reverse=True)
#         total_records = len(sorted_data)

#         # 📦 Build the continuous message with chunking to avoid Telegram's 4096 char limit
#         MAX_LENGTH = 4096
#         chunks = []
#         current_chunk = ""
        
#         for index, interruption in enumerate(sorted_data, start=1):
#             if not isinstance(interruption, dict):
#                 continue
                
#             date_str = interruption.get('date')
#             if not date_str:
#                 continue  
                
#             try:
#                 ourDate = datetime.strptime(date_str, "%Y-%m-%d").date()
#                 formatted_date = ourDate.strftime('%b %d, %Y %a')
#             except ValueError:
#                 formatted_date = date_str 

#             # 2) & 4) Indicator (1/18) and line separator
#             record_text = (
#                 f"🔸 <b>{index}/{total_records}</b>\n"
#                 f"⚡️ <b>PLANNED POWER INTERRUPTION</b>\n\n"
#                 f"📅 <b>Date:</b> {formatted_date}\n"
#                 f"⏰ <b>Time:</b> {interruption.get('start_time', 'N/A')} - {interruption.get('end_time', 'N/A')}\n"
#                 f"📍 <b>Areas Affected:</b>\n{interruption.get('areas', 'N/A')}\n\n"
#                 f"🏭 <b>Substation:</b> {interruption.get('substation_name', 'N/A')}\n"
#                 f"🔌 <b>Feeder Line:</b> {interruption.get('feeder_line_name', 'N/A')}\n"
#                 f"ℹ️ <b>Reason:</b> {interruption.get('reason', 'N/A')}\n"
#                 f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
#             )
            
#             # Check if adding this record exceeds the Telegram limit (4096 chars)
#             if len(current_chunk) + len(record_text) > MAX_LENGTH - 100: 
#                 if current_chunk:
#                     chunks.append(current_chunk)
#                 current_chunk = record_text
#             else:
#                 current_chunk += record_text

#         if current_chunk:
#             chunks.append(current_chunk)

#         # 📨 Send the chunk(s)
#         for i, chunk in enumerate(chunks):
#             # 1) Display total number of records at the top
#             if i == 0:
#                 text_to_send = f"📊 <b>Total planned interruptions: {total_records}</b>\n\n{chunk}"
#             else:
#                 text_to_send = f"📊 <b>Total planned interruptions: {total_records} (Continued)</b>\n\n{chunk}"
                
#             # Remove the very last separator line for a cleaner look
#             if i == len(chunks) - 1:
#                 text_to_send = text_to_send.rstrip("━━━━━━━━━━━━━━━━━━━━━━\n\n")
                
#             # Only attach the Exit keyboard to the final message
#             markup = reply_keyboard if i == len(chunks) - 1 else None
            
#             await message.answer(text_to_send, reply_markup=markup)

# #🏭🔌 redEnd
