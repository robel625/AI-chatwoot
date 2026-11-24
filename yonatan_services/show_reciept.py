from operator import call
from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup,ReplyKeyboardMarkup,ReplyKeyboardRemove,KeyboardButton,WebAppInfo
from aiogram.types import Message,CallbackQuery
from functools import partial
from aiogram import types
from aiogram.fsm.state import State,StatesGroup
from aiogram.filters import  Command,StateFilter
from aiogram import F
from aiogram.filters import BaseFilter
from django.db import IntegrityError
from aiogram.fsm.context import FSMContext
from asgiref.sync import sync_to_async
from aiogram import Router
import os,sys,django
from utils.verify import Verify
from utils.caNumberMarkup import CaNumberMarkup
from utils.myCustomFilter import FromGen, MultiTextStateFilter, generate_btn
from bot_logger import get_bot_logger, LogCategory
from shared_aiohttp import get_shared_session
from main_handler import MainHandler
from main_handler import Main_menu
import aiohttp
import json
from datetime import datetime,timedelta
from django.db import transaction
from django.db.models import Q
from utils.redirect import Redirect
from zoneinfo import ZoneInfo
# from utils.multiTextStateFilter import MultiTextStateFilter,FromGen
import uuid
from pathlib import Path
import json

RECEIPT_API_URL = os.getenv('RECEIPT_API_URL')
RECEIPT_API_ANYMONTH = os.getenv('RECEIPT_API_ANYMONTH')
RECEIPT_API_USERNAME = os.getenv('RECEIPT_API_USERNAME')
RECEIPT_API_PASSWORD = os.getenv('RECEIPT_API_PASSWORD')

#working_with_path____
# making sure we are on the right path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '../')) #../..
# Add the project directory to the Python path
sys.path.append(project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "eeuBotProject.settings")
django.setup()
#____________________________________/path___________________________________________________
from eeuBotApp.models import UserInfo,BotActivityLog,ActivityType,MeterReadingSubmission
from dotenv import load_dotenv
load_dotenv()

# Exit keyboard definition
EXIT_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Exit")]], 
    resize_keyboard=True
)

multiFilter = partial(MultiTextStateFilter, service_name="show_reciept")

logger = get_bot_logger("show_reciept_service")

class RecieptForm(StatesGroup):
    caNumber = State()
    showReciept = State()

class Show_reciept():
    service_name = "show_reciept"
    MIN_YEAR = 2026 
    MONTH_NAMES = ["Jan(1)", "Feb(2)", "Mar(3)", "Apr(4)", "May(5)", "Jun(6)", "Jul(7)", "Aug(8)", "Sep(9)", "Oct(10)", "Nov(11)", "Dec(12)"]
    
    def __init__(self,redis_client,bot):
        self.service_name = Show_reciept.service_name
        self.mainHandler = MainHandler()
        self.redirect = Redirect()
        self.router = Router()
        self.bot = bot
        self.verify = Verify()
        self.caNumberMarkup = CaNumberMarkup(self.gen)
        self.setup_handlers()

    def gen(self, callback: str, btn_group: str = "btn") -> str:
        """Makes all call.data unique to its respective service"""
        return generate_btn(self.service_name, callback, btn_group)

    async def extra(self, state: FSMContext, event: str) -> dict:
        """Build the logger 'extra' dict from FSM state."""
        return {
            "catagory": event,
            "session_id": await state.get_value("session_id", "unknown"),
            "tg_id": await state.get_value("tg_id", "unknown"),
        }

    def setup_handlers(self):
        @self.router.callback_query(lambda call: call.data.casefold() in ["mainHandler$btn>show reciept".casefold()])
        async def pilot(call:CallbackQuery,state:FSMContext):
            await call.answer()
            service_path = Path(__file__).parent.parent/"services_status.json"
            print(service_path)
            with open(service_path,'r',encoding='utf-8') as f:
                services = json.load(f)
            print(f"services:\t{services}")
            this_service = FromGen.get_callData(call.data)
            if services[this_service]["status"] =='inactive':
                return
            if services[this_service]["status"] == "disabled":
                if services[this_service]['message']:
                    text = services[this_service]['message']
                    await call.message.answer(text)
                    return
                else:
                    return
            print("am in show reciept")

            tg_id = call.from_user.id
            session_id = str(uuid.uuid4())
            await state.update_data(session_id=session_id, tg_id=str(tg_id))
            logger.info(f"User {tg_id} entered the show reciept service", extra=await self.extra(state, LogCategory.SERVICE_ENTRY))

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
            await call.message.answer("You are now in show Reciept service.", reply_markup=EXIT_KEYBOARD)
            inline_markup = await self.caNumberMarkup.get_Ca_InlineKeyboardMarkup(call.from_user.id)  
            if inline_markup:
                await state.set_state(RecieptForm.caNumber)
                await call.message.answer("Enter your Contract Account Number (CA-Number)", reply_markup=inline_markup)
            else:
                await state.set_state(RecieptForm.caNumber)
                await call.message.answer("Enter your Contract Account Number (CA-Number)")

        @self.router.message(multiFilter([RecieptForm.caNumber]))
        async def _(message: Message, state: FSMContext):
            if await self.verify.ca_bp_number(message, buttons=["Exit"], allow_multiCANumber=False):
                ca_number = message.text.strip()
                await state.update_data(ca_number=ca_number)
                logger.info(f"Receipt CA entered via message: {ca_number}", extra=await self.extra(state, LogCategory.USER_INPUT))
                await state.set_state(RecieptForm.showReciept)
                await self.show_receipt_menu(message, state)

        @self.router.callback_query(multiFilter([RecieptForm.caNumber]))
        async def _(call: CallbackQuery, state: FSMContext):
            await call.answer()
            if await self.verify.ca_bp_number(call, buttons=["Exit"], allow_multiCANumber=False):
                ca_number = FromGen.get_callData(call.data)
                await state.update_data(ca_number=ca_number)
                logger.info(f"Receipt CA picked from saved buttons: {ca_number}", extra=await self.extra(state, LogCategory.USER_INPUT))
                await state.set_state(RecieptForm.showReciept)
                await self.show_receipt_menu(call, state)

        # Handle Exit button
        @self.router.message(F.text == "Exit")
        async def handle_exit(message: Message, state: FSMContext):
            await state.clear()
            await message.answer("Exited show Reciept service.", reply_markup=ReplyKeyboardRemove())

        #___________________________________ receipt menu (latest / year / month picker) ___________________________________
        @self.router.callback_query(multiFilter([RecieptForm.showReciept], text=["latest"]))
        async def _(call: CallbackQuery, state: FSMContext):
            await call.answer()
            logger.info(f"Latest receipt requested for CA {await state.get_value('ca_number')}", extra=await self.extra(state, LogCategory.USER_INPUT))
            await self.handle_latest_receipt(call, state)

        @self.router.callback_query(multiFilter([RecieptForm.showReciept], text=["year_back", "year_forward"]))
        async def _(call: CallbackQuery, state: FSMContext):
            await call.answer()
            await self.handle_year_navigation(call, state)

        @self.router.callback_query(multiFilter([RecieptForm.showReciept], text=["noop"]))
        async def _(call: CallbackQuery, state: FSMContext):
            await call.answer()

        @self.router.callback_query(multiFilter([RecieptForm.showReciept], text=[str(m) for m in range(1, 13)]))
        async def _(call: CallbackQuery, state: FSMContext):
            await call.answer()
            message  = await call.message.answer("Fetching receipt, please wait...")
            month = int(FromGen.get_callData(call.data))
            logger.info(f"Month receipt requested: {month}", extra=await self.extra(state, LogCategory.USER_INPUT))
            await self.handle_month_receipt(call, state, month)
            await message.delete()  # Delete the "Fetching receipt" message after processing
            

    #___________________________________ menu building ___________________________________
    def _year_bounds(self):
        current_year = datetime.now().year
        max_year = max(current_year, self.MIN_YEAR) 
        return self.MIN_YEAR, max_year

    def build_receipt_menu(self, year: int) -> InlineKeyboardMarkup:
        min_year, max_year = self._year_bounds()
        keyboard = [
            [InlineKeyboardButton(text="🧾 Latest Receipt", callback_data=self.gen("latest", btn_group="menu"))]
        ]
        back_btn = InlineKeyboardButton(
            text="◀️" if year > min_year else "▪️",
            callback_data=self.gen("year_back", btn_group="menu") if year > min_year else self.gen("noop", btn_group="menu")
        )
        forward_btn = InlineKeyboardButton(
            text="▶️" if year < max_year else "▪️",
            callback_data=self.gen("year_forward", btn_group="menu") if year < max_year else self.gen("noop", btn_group="menu")
        )
        year_btn = InlineKeyboardButton(text=str(year), callback_data=self.gen("noop", btn_group="menu"))
        keyboard.append([back_btn, year_btn, forward_btn])
        
        current_year = datetime.now().year
        current_month = datetime.now().month

        month_buttons = []
        for i, name in enumerate(self.MONTH_NAMES, start=1):
            if year == current_year and i > current_month:
                month_buttons.append(
                    InlineKeyboardButton(text=" ", callback_data=self.gen("noop", btn_group="month"))
                )
            else:
                month_buttons.append(
                    InlineKeyboardButton(text=name, callback_data=self.gen(str(i), btn_group="month"))
                )

        for row_start in range(0, 12, 4):
            keyboard.append(month_buttons[row_start:row_start + 4])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    async def show_receipt_menu(self, update, state: FSMContext):
        message = update.message if isinstance(update, CallbackQuery) else update
        min_year, max_year = self._year_bounds()
        await state.update_data(receipt_year=max_year) 
        
      
        
        markup = self.build_receipt_menu(max_year)
        await message.answer("Choose the receipt you want to view:", reply_markup=markup)

    async def handle_year_navigation(self, call: CallbackQuery, state: FSMContext):
        min_year, max_year = self._year_bounds()
        year = await state.get_value("receipt_year", max_year)
        direction = FromGen.get_callData(call.data)
        if direction == "year_back" and year > min_year:
            year -= 1
        elif direction == "year_forward" and year < max_year:
            year += 1
        else:
            return
        await state.update_data(receipt_year=year)
        markup = self.build_receipt_menu(year)
        try:
            await call.message.edit_reply_markup(reply_markup=markup)
        except Exception as e:
            print(f"Error updating year markup: {e}")

    #___________________________________ fetching & displaying the receipt ___________________________________
    async def handle_latest_receipt(self, update, state: FSMContext):
        ca_number = await state.get_value('ca_number')
        api_url = f"{RECEIPT_API_URL}{ca_number}"
        await self.fetch_and_display_receipt(update, state, api_url)

    async def handle_month_receipt(self, update, state: FSMContext, month: int):
        ca_number = await state.get_value('ca_number')
        year = await state.get_value('receipt_year', datetime.now().year)
        base_url = RECEIPT_API_ANYMONTH.split('?')[0]
        api_url = f"{base_url}?Contract_Account={ca_number}&year={year}&month={month:02d}"
        print(f"api:url:\t{api_url}")
        await self.fetch_and_display_receipt(update, state, api_url, month=month, year=year)

    async def fetch_and_display_receipt(self, update, state: FSMContext, api_url: str, month: int = None, year: int = None):
        message = update.message if isinstance(update, CallbackQuery) else update
        API_TIMEOUT = aiohttp.ClientTimeout(
            total=40,
            connect=20,
            sock_read=20,
            sock_connect=20
        )
        auth = aiohttp.BasicAuth(RECEIPT_API_USERNAME, RECEIPT_API_PASSWORD)
        session, proxy = await get_shared_session()
        proxy = None
        try:
            async with session.get(api_url, auth=auth, proxy=proxy, timeout=API_TIMEOUT) as response:
                if response.status == 200:
                    raw_data = await response.json(content_type=None)
                    if isinstance(raw_data, list):
                        if not raw_data:
                            await message.answer("❌ No payment record found for that period.", reply_markup=EXIT_KEYBOARD)
                            logger.info(f"No receipt record found for CA {await state.get_value('ca_number')}", extra=await self.extra(state, LogCategory.GENERAL))
                            return
                        data = raw_data[0]
                    elif isinstance(raw_data, dict):
                        data = raw_data
                    else:
                        await message.answer(" Unexpected response format from server.", reply_markup=EXIT_KEYBOARD)
                        return
                        
                    await state.update_data(receipt_data=data)
                    logger.info(f"Receipt fetched successfully for CA {await state.get_value('ca_number')}", extra=await self.extra(state, LogCategory.API_SUCCESS))
                        
                    if month and year:
                        header = f"<b>Receipt for {month}/{year}</b>"
                    else:
                        payment_date = data.get('payment_date', '')
                        try:
                            dt = datetime.strptime(payment_date, "%Y-%m-%d")
                            header = f"<b>Receipt for {dt.month}/{dt.year}</b>"
                        except (ValueError, TypeError):
                            header = "<b>Receipt</b>"
                                
                    text = (
                        f"{header}\n\n"
                        f"🧑 Customer Name: {data.get('customer_name', 'N/A')}\n"
                        f"🏠 BP No: {data.get('BP_no', 'N/A')}\n"
                        f"📄 CA No: {data.get('CA_no', 'N/A')}\n"
                        f"🧾 Voucher No: {data.get('voucher_no', 'N/A')}\n"
                        f" Region: {data.get('region', 'N/A')}\n"
                        f"🏢 CSC: {data.get('csc', 'N/A')}\n"
                        f"📅 Payment Date: {data.get('payment_date', 'N/A')}\n"
                        f"💰 Total Excluding VAT: {data.get('total_excluding_vat', 'N/A')}\n"
                        f" VAT Amount: {data.get('vat_amount', 'N/A')}\n"
                        f"💵 Total Including VAT: {data.get('total_including_vat', 'N/A')}\n"
                        f"⚡ EBC Charge: {data.get('ebc_charge', 'N/A')}\n"
                        f"📋 Regulatory Fee: {data.get('regulatory_fee', 'N/A')}\n"
                        f"💳 Total Received: {data.get('total_received', 'N/A')}\n"
                        f"💳 Mode of Payment: {data.get('mode_of_payment', 'N/A')}"
                    )
                    voucher = data.get('voucher_no')
                    if voucher:
                        receipt_url = f"https://receipt.eeu.et:8018/receipts/{voucher}/"
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(
                                text="View Receipt",
                                web_app=WebAppInfo(url=receipt_url)
                            )]
                        ])
                        await message.answer(text, reply_markup=keyboard, parse_mode='HTML')
                    else:
                        await message.answer(text, parse_mode='HTML')
                            
                elif response.status == 404:
                    try:
                        error_data = await response.json(content_type=None)
                        error_message = error_data.get('error', "No payment record found for that period.") if isinstance(error_data, dict) else "No payment record found for that period."
                    except Exception:
                        error_message = "No payment record found for that period."
                    await message.answer(f"❌ {error_message}", reply_markup=EXIT_KEYBOARD)
                    logger.error(f"Receipt API 404 for CA {await state.get_value('ca_number')}: {error_message}", extra=await self.extra(state, LogCategory.API_FAIL))
                else:
                    await message.answer("❌ Failed to fetch receipt. Please check your CA number and try again.", reply_markup=EXIT_KEYBOARD)
                    logger.error(f"Receipt API status {response.status} for CA {await state.get_value('ca_number')}", extra=await self.extra(state, LogCategory.API_FAIL))
        except Exception as e:
            logger.error(f"Receipt fetch error for CA {await state.get_value('ca_number')}: {e}", extra=await self.extra(state, LogCategory.NETWORK_ERROR))
            print(f"Error fetching receipt: {e}")
            await message.answer("❌ An error occurred while fetching the receipt. Please try again later.", reply_markup=EXIT_KEYBOARD)