import io

import aiohttp
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from dotenv import load_dotenv
from functools import partial
from aiogram import types
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter
from aiogram import F
from aiogram.filters import BaseFilter
from django.db import IntegrityError
from aiogram.fsm.context import FSMContext
from asgiref.sync import sync_to_async
from aiogram import Router
import os, sys, django
# from utils.calander_component import CalendarModule
from EEU_datas.Eeu_updated_tree_data import Eeu_complaint_types, Eeu_CSCsForReg, Eeu_regionForGeo, geo_loc
from utils.verify import Verify
from utils.caNumberMarkup import CaNumberMarkup
from utils.myCustomFilter import FromGen, MultiTextStateFilter, generate_btn
from bot_logger import get_bot_logger, LogCategory
from shared_aiohttp import get_shared_session
from eeu_api import PLANNED_INTERRUPTION_TODAY_URL, PLANNED_INTERRUPTION_FUTURE_URL
import json,io
from pathlib import Path
from datetime import datetime,date,timedelta
import uuid
# Force UTF-8 encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ________________________________________working_with_path____________________________________________
# making sure we are on the right path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '../')) #../..
# Add the project directory to the Python path
sys.path.append(project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "eeuBotProject.settings")
django.setup()
#________________________________________/path_______________________________________________________
load_dotenv()

# Exit keyboard definition
EXIT_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Exit")]], 
    resize_keyboard=True
)

multiFilter = partial(MultiTextStateFilter, service_name="showHistory")

logger = get_bot_logger("show_history_service")

class StatForm(StatesGroup):
    ca = State()

class Show_history(StatesGroup):
    menu = State()
    payment = State()
    bill = State()
    ca = State()
    
    
class ShowHistoryRouter():
    service_name = "showHistory"

    def __init__(self):
        self.router = Router()
        self.verify = Verify()
        self.from_gen = FromGen()
        self.caNumberMarkup = CaNumberMarkup(self.gen)
        self.setup_handlers()

    @staticmethod
    def get_gen_from_text(text):
         gen = text.split('\n')[0]
         print("text:\t",text)
         return gen

    def gen(self, callback: str, btn_group: str = "btn") -> str:
        return generate_btn(self.service_name, callback, btn_group)

    async def extra(self, state: FSMContext, event: str) -> dict:
        """Build the logger 'extra' dict from FSM state."""
        return {
            "catagory": event,
            "session_id": await state.get_value("session_id", "unknown"),
            "tg_id": await state.get_value("tg_id", "unknown"),
        }

    def is_ca_button(self, call: CallbackQuery) -> bool:
        """True only for the saved CA-Number buttons this service generated (btn_group == 'ca')."""
        data = getattr(call, 'data', '') or ''
        if '$' not in data or '>' not in data:
            return False
        return (FromGen.get_service(data) == self.service_name.casefold()
                and FromGen.get_btnGroup(data) == "ca")

    def exit_reply_markup(self):
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Exit")]],
            one_time_keyboard=True,
            resize_keyboard=True
        )

    def setup_handlers(self):
        @self.router.callback_query(lambda call: call.data.casefold() in ["mainHandler$btn>Show Bill History".casefold()])
        async def pilot(call: CallbackQuery, state: FSMContext):
            await call.answer()
            service_path = Path(__file__).parent.parent / "services_status.json"
            with open(service_path, 'r', encoding='utf-8') as f:
                services = json.load(f)

            this_service = FromGen.get_callData(call.data).casefold()
            service = services.get(this_service)
            if service is None:
                await call.message.answer("This service is currently unavailable.")
                return

            if service.get("status") == 'inactive':
                return
            
            if service.get("status") == "disabled":
                if service.get('message'):
                    await call.message.answer(service['message'])
                return

            tg_id = call.from_user.id
            username = call.from_user.username

            session_id = str(uuid.uuid4())
            await state.update_data(session_id=session_id, tg_id=str(tg_id))
            logger.info(f"User {tg_id} entered the show history service", extra=await self.extra(state, LogCategory.SERVICE_ENTRY))

            all_Data = await state.get_data()
            last_interaction_time = all_Data.get("last_interaction_time")
            session_id = all_Data.get("session_id")
            tg_id = all_Data.get("tg_id")
            await state.clear()
            updates = {"last_interaction_time": last_interaction_time}
            if session_id: updates["session_id"] = session_id
            if tg_id: updates["tg_id"] = tg_id
            await state.update_data(**updates)
            # Display entry message with Exit keyboard
            await call.message.answer("You are now in Show History service.", reply_markup=EXIT_KEYBOARD)

            await state.set_state(Show_history.menu)
            inline_markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Billing History", callback_data=self.gen("Billing History"))],
                [InlineKeyboardButton(text="Invoice History", callback_data=self.gen("Invoice History"))]
            ])
            await call.message.answer("Choose a history option:", reply_markup=inline_markup)

        # ✅ Single handler for the menu state (removed the duplicate dead code)
        # @self.router.callback_query(MultiTextStateFilter(allowed_states=[Show_history.menu]))
        # @self.router.message(MultiTextStateFilter(allowed_states=[],text=[self.gen("Billing History"), self.gen("Invoice History")]))
        @self.router.callback_query(
            multiFilter([Show_history.menu, Show_history.ca]),
            lambda call: FromGen.get_callData(call.data).casefold() in ["billing history", "invoice history"]
        )
        async def handle_history_choice(call: CallbackQuery, state: FSMContext):
            await call.answer()
            await state.update_data(selected_history=FromGen.get_callData(call.data))
            logger.info(f"Show history option selected: {FromGen.get_callData(call.data)}, tg_id {call.from_user.id}", extra=await self.extra(state, LogCategory.USER_INPUT))
            await state.set_state(Show_history.ca)
            # show the CA-Numbers already saved on the user's profile, if there are any
            inline_markup = await self.caNumberMarkup.get_Ca_InlineKeyboardMarkup(call.from_user.id)
            await self.get_ca_number(call, reply_markup=inline_markup)

        @self.router.message(multiFilter([Show_history.ca]))
        async def _(message:Message,state:FSMContext):
            if await self.verify.ca_bp_number(message,buttons=["Exit"]):
                await state.update_data(ca_number=message.text.strip())
                # await message.answer("Fetching your history, please wait...")
                await self.fetch_and_show_history(message, state)

        @self.router.callback_query(multiFilter([Show_history.ca]), lambda call: self.is_ca_button(call))
        async def _(call: CallbackQuery, state: FSMContext):
            #fires when the user picks one of their saved CA-Numbers instead of typing it
            await call.answer()
            if await self.verify.ca_bp_number(call, buttons=["Exit"], allow_multiCANumber=False):
                await state.update_data(ca_number=FromGen.get_callData(call.data))
                fetching_message  = await call.message.answer("Fetching receipt, please wait...")
                await self.fetch_and_show_history(call.message, state)
                await fetching_message.delete()  # Delete the "Fetching receipt" message after processing

    async def get_ca_number(self, update, reply_markup=None):
        """Asks for the CA-Number. When the user has CA-Numbers saved they come attached as inline buttons."""
        message = update if isinstance(update, types.Message) else update.message
        if reply_markup:
            await message.answer("Please Enter your Ca-Number, or pick one of your saved CA-Numbers below.", reply_markup=reply_markup)
        else:
            await message.answer("Please Enter your Ca-Number.")

    async def fetch_and_show_history(self, message: types.Message, state: FSMContext):
        ca_number = await state.get_value("ca_number")
        selected_history = await state.get_value("selected_history")
        title = selected_history.title()
        
        # ✅ Reverted to your original .env variable names
        url = os.getenv("billing_history_url") if selected_history.casefold() == "billing history" else os.getenv("payment_history_url")
        username = os.getenv("billing_history_username")
        password = os.getenv("billing_history_password")
        exit_markup = self.exit_reply_markup()

        if not all([url, username, password]):
            logger.error(f"History config missing for CA {ca_number}", extra=await self.extra(state, LogCategory.API_FAIL))
            await message.answer("❌ Configuration missing. Please contact support.", reply_markup=exit_markup)
            return

        # 🔑 REMOVED custom headers. Using standard HTTP Basic Auth instead.
        auth = aiohttp.BasicAuth(login=username, password=password)

        json_payload = {
            "Record": {
                "ContractAccount": ca_number
            }
        }

        timeout = aiohttp.ClientTimeout(total=20)
        session, proxy = await get_shared_session()
        proxy = None
        try:
            async with session.post(
                url=url,
                json=json_payload,
                auth=auth,  # ✅ Proper Basic Auth
                proxy=proxy,
                timeout=timeout
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
        except aiohttp.ClientResponseError as exc:
            logger.error(f"History API error for CA {ca_number}: status={exc.status}", extra=await self.extra(state, LogCategory.API_FAIL))
            await message.answer(f"🌐 API Error: {exc.status}. Please check credentials or try again later.", reply_markup=exit_markup)
            return
        except Exception as e:
            logger.error(f"History fetch network error for CA {ca_number}: {e}", extra=await self.extra(state, LogCategory.NETWORK_ERROR))
            print(f"❌ History Fetch Exception: {e}")
            await message.answer("⏳ Could not retrieve history at the moment. Please try again later.", reply_markup=exit_markup)
            return

        records = payload.get("Record") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            logger.warning(f"Unexpected history response format for CA {ca_number}", extra=await self.extra(state, LogCategory.API_FAIL))
            await message.answer("️ Unexpected response format from history service.", reply_markup=exit_markup)
            return

        if not records:
            logger.info(f"{title} returned no records for CA {ca_number}", extra=await self.extra(state, LogCategory.GENERAL))
            await message.answer(f" {title} returned no records.", reply_markup=exit_markup)
            return

        # ──────────────────────────────────────────────────────────────
        # 📝 SINGLE-MESSAGE FORMATTING LOGIC
        # ──────────────────────────────────────────────────────────────
        is_invoice = selected_history.casefold() == "invoice history"
        total_records = len(records)
        msg_parts = [
            f"📜 <b>{title}</b>\n",
            f"<b>Total Records Found:</b> {total_records}\n\n"
        ]

        for idx, rec in enumerate(records, 1):
            doc_no = str(rec.get("DocumentNo", "N/A")).strip()
            acct   = str(rec.get("ContractAccount", "N/A")).strip()
            counter = f"({idx}/{total_records})"

            if is_invoice:
                amount     = str(rec.get("PaymentAmount", "0.00")).strip()
                pay_date   = rec.get("PaymentDate", "N/A")
                pay_type   = str(rec.get("PayDocType", "N/A")).strip()
                extra_info = str(rec.get("AdditionalInfo", "N/A")).strip()

                # ✅ Emojis completely removed
                record_block = (
                    f"<b>{counter}</b>\n"
                    f"Document: <code>{doc_no}</code>\n"
                    f"Account: <code>{acct}</code>\n"
                    f"Amount: <b>{amount}</b>\n"
                    f"Date: {pay_date}\n"
                    f"Type: {pay_type} | Ref: <code>{extra_info}</code>\n"
                    f"{'━' * 32}\n"
                )
            else:
                # Billing history fields
                bp          = str(rec.get("BusinessPartner", "N/A")).strip()
                amount      = str(rec.get("Amount", "0.00")).strip()
                consumption = str(rec.get("Consumption", "N/A")).strip()
                post_date   = rec.get("PostingDate", "N/A")
                due_date    = rec.get("NetDueDate", "N/A")
                bill_period = rec.get("BillingPeriod", "N/A")
                bill_range  = rec.get("BillPeriod", "N/A")
                prev_read   = str(rec.get("PreviousRead", "N/A")).strip()
                curr_read   = str(rec.get("CurrentRead", "N/A")).strip()

                # ✅ Emojis completely removed
                record_block = (
                    f"<b>{counter}</b>\n"
                    f"Document: <code>{doc_no}</code>\n"
                    f"BP: <code>{bp}</code> | Account: <code>{acct}</code>\n"
                    f"Amount: <b>{amount}</b>\n"
                    f"Consumption: {consumption} | Meter: {prev_read} → {curr_read}\n"
                    f"Posted: {post_date} | Due: {due_date}\n"
                    f"Period: {bill_period} ({bill_range})\n"
                    f"{'━' * 32}\n"
                )
            msg_parts.append(record_block)

        final_message = "".join(msg_parts)

        if len(final_message) > 4090:
            final_message = final_message[:4090] + "\n\n⚠️ <i>Message truncated due to Telegram length limits.</i>"

        await message.answer(final_message, parse_mode='HTML', reply_markup=exit_markup)
        logger.info(f"{title} fetched successfully for CA {ca_number} ({total_records} records)", extra=await self.extra(state, LogCategory.API_SUCCESS))