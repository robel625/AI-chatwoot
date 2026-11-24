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
from utils.verify import FromGen, Verify
from utils.caNumberMarkup import CaNumberMarkup
from eeu_api import PLANNED_INTERRUPTION_TODAY_URL, PLANNED_INTERRUPTION_FUTURE_URL
import json,io
from pathlib import Path
from datetime import datetime,date,timedelta
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

class MultiTextStateFilter(BaseFilter):
    """allowed_states:List , text: List =[] (i.e text is optional)"""
    #use when you want to filter multipple states with or without text
    #the text can be a "message.text" or a "call.data",so works when a router is invoked by a types.Message or a callback query
    #the text workd same if it's upppercase/lowercase
    # a single state also works fine
    #it returns True/False

    this_service = "showHistory"

    def __init__(self,allowed_states:list,text:list = []) -> bool:
        self.allowed_states = allowed_states
        self.text =text
        self.this_service = MultiTextStateFilter.this_service
    async def __call__(self,update,state):
        if self.this_service:
            if isinstance(update,types.CallbackQuery):
                call =  update
                print(f"current_service:{self.this_service} \t Triggers_service:{FromGen.get_service(call.data)}")
                if FromGen.get_service(call.data).casefold() != self.this_service.casefold():
                    print(f'current_service:{self.this_service} \t Triggers_service:{FromGen.get_service(call.data)}')
                    return False
        if self.text == []:
            pass
        elif isinstance(update,types.Message):
            message = update
            if not (message.content_type == "text"):
                return False
            text_match = (getattr(message,'text',None) is not None) and ( (getattr(message,'text','').casefold() in [i.casefold() for i in self.text]))
            if not text_match:
                return False
        elif isinstance(update,types.CallbackQuery):
            call =  update
            text_match = call.data.casefold() in  [i.casefold() for i in self.text]
            if not text_match:
                return False

        current_state = await state.get_state()
        return current_state in self.allowed_states

class StatForm(StatesGroup):
    ca = State()
class FromGen:
    @classmethod
    def get_service(cls, gen: str):
        """gen is call.data"""
        return gen[:gen.index('$')]

    @classmethod
    def get_btnGroup(cls, gen: str):
        return gen[gen.index('$') + 1:gen.index('>')]

    @classmethod
    def get_callData(cls, gen: str):
        print("gen:\t",gen)
        return gen[gen.index('>') + 1:]
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
        return self.service_name.casefold().strip() + "$" + btn_group.casefold().strip() + ">" + callback.casefold().strip()

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
        @self.router.callback_query(lambda call: call.data.casefold() in ["mainHandler$btn>Show History".casefold()])
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
            await state.clear()
            # Display entry message with Exit keyboard
            await call.message.answer("You are now in Show History service.", reply_markup=EXIT_KEYBOARD)

            await state.set_state(Show_history.menu)
            inline_markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Billing History", callback_data=self.gen("Billing History"))],
                [InlineKeyboardButton(text="Payment History", callback_data=self.gen("Payment History"))]
            ])
            await call.message.answer("Choose a history option:", reply_markup=inline_markup)

        @self.router.callback_query(MultiTextStateFilter(allowed_states=[Show_history.menu]))
        async def _(call: CallbackQuery, state: FSMContext):
            await call.answer()
            await state.update_data(selected_history=FromGen.get_callData(call.data))
            await state.set_state(Show_history.ca)
            # show the CA-Numbers already saved on the user's profile, if there are any
            inline_markup = await self.caNumberMarkup.get_Ca_InlineKeyboardMarkup(call.from_user.id)
            await self.get_ca_number(call, reply_markup=inline_markup)

        @self.router.message(MultiTextStateFilter(allowed_states=[Show_history.ca]))
        async def _(message:Message,state:FSMContext):
            if await self.verify.ca_bp_number(message,buttons=["Exit"]):
                await state.update_data(ca_number=message.text.strip())
                # await message.answer("Fetching your history, please wait...")
                await self.fetch_and_show_history(message, state)

        @self.router.callback_query(MultiTextStateFilter(allowed_states=[Show_history.ca]), lambda call: self.is_ca_button(call))
        async def _(call: CallbackQuery, state: FSMContext):
            #fires when the user picks one of their saved CA-Numbers instead of typing it
            await call.answer()
            if await self.verify.ca_bp_number(call, buttons=["Exit"], allow_multiCANumber=False):
                await state.update_data(ca_number=FromGen.get_callData(call.data))
                fetching_message  = await call.message.answer("Fetching receipt, please wait...")
                await self.fetch_and_show_history(call.message, state)
                await fetching_message.delete()  # Delete the "Fetching receipt" message after processing


        @self.router.callback_query(MultiTextStateFilter(allowed_states=[Show_history.menu]))
        async def handle_history_choice(call: CallbackQuery, state: FSMContext):
            await call.answer()
            callback_data = FromGen.get_callData(call.data).casefold()
            
            if callback_data == "billing history":
                await self.fetch_and_show_history(call.message, state, "billing_history_url", "Billing History")
            elif callback_data == "payment history":
                await self.fetch_and_show_history(call.message, state, "payment_history_url", "Payment History")

        # @self.router.message(MultiTextStateFilter(allowed_states=[Show_history.menu], text=["Exit"]))
        # async def handle_exit(message: types.Message, state: FSMContext):
        #     await state.clear()
        #     await message.answer("Exited show history.", reply_markup=ReplyKeyboardRemove())

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
        url = os.getenv("billing_history_url") if selected_history.casefold() == "billing history" else os.getenv("payment_history_url")
        username = os.getenv("billing_history_username")
        password = os.getenv("billing_history_password")
        exit_markup = self.exit_reply_markup()

        if not all([url, username, password]):
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
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url=url,
                    json=json_payload,
                    auth=auth,  # ✅ Proper Basic Auth
                    timeout=timeout
                ) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
        except aiohttp.ClientResponseError as exc:
            await message.answer(f"🌐 API Error: {exc.status}. Please check credentials or try again later.", reply_markup=exit_markup)
            return
        except Exception as e:
            print(f"❌ History Fetch Exception: {e}")
            await message.answer("⏳ Could not retrieve history at the moment. Please try again later.", reply_markup=exit_markup)
            return

        records = payload.get("Record") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            await message.answer("️ Unexpected response format from history service.", reply_markup=exit_markup)
            return

        if not records:
            await message.answer(f" {title} returned no records.", reply_markup=exit_markup)
            return

        # ──────────────────────────────────────────────────────────────
        # 📝 SINGLE-MESSAGE FORMATTING LOGIC
        # ──────────────────────────────────────────────────────────────
        is_payment = selected_history.casefold() == "payment history"
        total_records = len(records)
        msg_parts = [
            f"📜 <b>{title}</b>\n",
            f"<b>Total Records Found:</b> {total_records}\n\n"
        ]

        for idx, rec in enumerate(records, 1):
            doc_no = str(rec.get("DocumentNo", "N/A")).strip()
            acct   = str(rec.get("ContractAccount", "N/A")).strip()
            counter = f"({idx}/{total_records})"

            if is_payment:
                amount     = str(rec.get("PaymentAmount", "0.00")).strip()
                pay_date   = rec.get("PaymentDate", "N/A")
                pay_type   = str(rec.get("PayDocType", "N/A")).strip()
                extra_info = str(rec.get("AdditionalInfo", "N/A")).strip()

                record_block = (
                    f"🔹 <b>{counter}</b>\n"
                    f"🆔 Document: <code>{doc_no}</code>\n"
                    f"🏦 Account: <code>{acct}</code>\n"
                    f"💰 Payment Amount: <b>{amount}</b>\n"
                    f"📅 Payment Date: {pay_date}\n"
                    f"📄 Type: {pay_type} | ℹ️ Ref: <code>{extra_info}</code>\n"
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

                record_block = (
                    f"🔹 <b>{counter}</b>\n"
                    f"🆔 Document: <code>{doc_no}</code>\n"
                    f"👤 BP: <code>{bp}</code> | 🏦 Account: <code>{acct}</code>\n"
                    f"💰 Amount: <b>{amount}</b>\n"
                    f"⚡ Consumption: {consumption} | 📏 Meter: {prev_read} → {curr_read}\n"
                    f"📅 Posted: {post_date} | 💳 Due: {due_date}\n"
                    f"🗓️ Period: {bill_period} ({bill_range})\n"
                    f"{'━' * 32}\n"
                )
            msg_parts.append(record_block)

        final_message = "".join(msg_parts)

        if len(final_message) > 4090:
            final_message = final_message[:4090] + "\n\n⚠️ <i>Message truncated due to Telegram length limits.</i>"

        await message.answer(final_message, parse_mode='HTML', reply_markup=exit_markup)