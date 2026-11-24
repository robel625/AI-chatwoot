import requests
import aiohttp
from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup,ReplyKeyboardMarkup,ReplyKeyboardRemove,KeyboardButton
from dotenv import load_dotenv
from functools import partial
from aiogram import types
from aiogram.types import Message,CallbackQuery
from aiogram.fsm.state import State,StatesGroup
from aiogram.filters import  Command,StateFilter
from aiogram import F
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from asgiref.sync import sync_to_async
from aiogram import Router
import os,sys,django,html
from utils.verify import Verify
from utils.redirect import Redirect
from utils.myCustomFilter import FromGen, MultiTextStateFilter, generate_btn
from bot_logger import get_bot_logger, LogCategory
from shared_aiohttp import get_shared_session
from eeu_api import CHECK_BILL_URL,CHECK_BILL_HEADER
from pathlib import Path
import json
import uuid
load_dotenv()
TOKEN = os.getenv('TOKEN')

#working_with_path____
# making sure we are on the right path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '../')) #../..
# Add the project directory to the Python path
sys.path.append(project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "eeuBotProject.settings")
django.setup()
#____________________________________/path___________________________________________________
from eeuBotApp.models import UserInfo

multiFilter = partial(MultiTextStateFilter, service_name="checkBill")
logger = get_bot_logger("check_bill_service")

class CheckBillForm(StatesGroup):
    enter_ca = State()
    disp_amount = State()
    finished = State

class CheckBill:
    service_name = "checkBill"
    def __init__(self):
        self.service_name = CheckBill.service_name
        self.router = Router()
        self.verify = Verify()
        self.redirect = Redirect()
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
        @self.router.callback_query(lambda call:call.data.casefold() in  ["mainHandler$btn>check bill".casefold(),"checkbill$btn>check bill".casefold()] )
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
            
            tgID = str(call.from_user.id)
            queryset = await sync_to_async(UserInfo.objects.filter)(tgID = tgID)
            is_registered = await sync_to_async(queryset.exists)()
            session_id = str(uuid.uuid4())
            await state.update_data(session_id=session_id, tg_id=tgID)
            logger.info(f"User {tgID} entered the check bill service", extra=await self.extra(state, LogCategory.SERVICE_ENTRY))
            
            all_Data = await state.get_data()
            last_interaction_time = all_Data.get("last_interaction_time")
            session_id = all_Data.get("session_id")
            tg_id = all_Data.get("tg_id")
            await state.clear()
            updates = {"last_interaction_time": last_interaction_time}
            if session_id: updates["session_id"] = session_id
            if tg_id: updates["tg_id"] = tg_id
            await state.update_data(**updates)
            
            await state.set_state(CheckBillForm.enter_ca)
            await self.caNumber_handler(call,state)

        # Handle text input of CA number
        @self.router.message(multiFilter([CheckBillForm.enter_ca]))
        async def handle_ca_text(message: types.Message, state: FSMContext):
            if await self.verify.ca_bp_number(message,buttons=["Exit"],allow_multiCANumber=False): # we don't want the user to give multi CA-numbers
                ca_number = message.text.strip()
                await state.update_data(ca_number=ca_number)
                logger.info(f"Check bill CA entered via message: {ca_number}", extra=await self.extra(state, LogCategory.USER_INPUT))
                await state.set_state(CheckBillForm.disp_amount)
                await self.generate_bill(message, state)

        # Handle CA number selection from inline buttons
        @self.router.callback_query(multiFilter([CheckBillForm.enter_ca], btn_group=["ca"]))
        async def handle_ca_selection(call: CallbackQuery, state: FSMContext):
            await call.answer()
            print("am in FromGen.get_service(call.data) == 'checkbill' ")
            if await self.verify.ca_bp_number(call,buttons=["Exit"]):
                print("verified --- yes ")
                selected_ca = FromGen.get_callData(call.data)
                await state.update_data(ca_number=selected_ca)
                logger.info(f"Check bill CA picked from saved buttons: {selected_ca}", extra=await self.extra(state, LogCategory.USER_INPUT))
                await state.set_state(CheckBillForm.disp_amount)
                await self.generate_bill(call.message, state)

    async def caNumber_handler(self, call: CallbackQuery, state: FSMContext):
        query = await sync_to_async(UserInfo.objects.filter)(tgID=call.from_user.id)
        user = await sync_to_async(query.first)()
        print("in_bill-> user\t:",user)
        
        # Always show Exit as reply button
        reply_keyboard = [[KeyboardButton(text="Exit")]]
        reply_markup = ReplyKeyboardMarkup(
            keyboard=reply_keyboard,
            one_time_keyboard=True,
            resize_keyboard=True
        )
        
        if (not user) or (getattr(user,'caNumber',None) == None):
            return await call.message.answer("Enter your Contract Account Number(CA-Number)",reply_markup=reply_markup)
        
        ca_number = user.caNumber if user.caNumber else ''
        ca_number = ca_number.replace(" ", "").replace("'","").strip('[]{}').split(",")
        ca_number = ca_number if ca_number!= [''] else ''
        
        if call.data != "checkbill$btn>check bill":
            await call.message.answer("Enter your Contract Account Number(CA-Number)", reply_markup=reply_markup)
            
        if ca_number:
            print("ca_number:\t",ca_number)
            unique_ca_numbers = set(ca_number)
            # Create inline buttons for CA numbers, two per row
            inline_buttons = []
            current_row = []
            for ca in unique_ca_numbers:
                if ca:  # Only add non-empty CA numbers
                    current_row.append(InlineKeyboardButton(
                        text=ca,
                        callback_data=self.gen(callback=ca, btn_group="ca")
                    ))
                    if len(current_row) == 2:  # Two buttons per row
                        inline_buttons.append(current_row)
                        current_row = []
            # Add any remaining button
            if current_row:
                inline_buttons.append(current_row)
            inline_markup = InlineKeyboardMarkup(inline_keyboard=inline_buttons)
            await call.message.answer("Select your CA-Number:", reply_markup=inline_markup)

    async def generate_bill(self, message: Message, state: FSMContext):
        processing = await message.answer("🔄 Processing... please wait !")
        all_data = await state.get_data()
        ca_number = all_data.get("ca_number")
        print("testing caNumber(in bill) \t:",ca_number, "\t types:\t",type(ca_number))
        
        def normalize_amount(val):
            try:
                return float(str(val).replace(',', '').strip())
            except ValueError:
                return 0.0

        def normalize_date(val):
            return str(val).replace('/', '').replace('-', '').strip()

        def format_date(val):
            """Converts YYYYMMDD or YYYY/MM/DD to dd/mm/yyyy"""
            clean = str(val).replace('/', '').replace('-', '').strip()
            if len(clean) == 8:
                return f"{clean[6:8]}/{clean[4:6]}/{clean[:4]}"
            return val

        try:
            json_load = ''
            session, proxy = await get_shared_session()
            proxy = None
            async with session.get(
                url=f"{CHECK_BILL_URL}{ca_number}",
                headers=CHECK_BILL_HEADER,
                proxy=proxy,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    data = data.get('Data')
                    due = data.get('Due_Amount','0.00')
                    due_amount_str = str(due).strip()
                    due_date_str = str(data.get('Due_Date', '')).strip()
                    return_message = str(data.get('Return_Message', '')).strip()
                    
                    if normalize_amount(due_amount_str) == 0.0:
                        json_load = return_message if return_message else "No due amount."
                        parse_mode = None
                    else:
                        history_text = ""
                        consumption_val = "N/A"
                        billing_url = os.getenv("billing_history_url")
                        billing_user = os.getenv("billing_history_username")
                        billing_pass = os.getenv("billing_history_password")
                        
                        if billing_url and billing_user and billing_pass:
                            auth = aiohttp.BasicAuth(login=billing_user, password=billing_pass)
                            json_payload = {
                                "Record": {
                                    "ContractAccount": ca_number
                                }
                            }
                            timeout = aiohttp.ClientTimeout(total=20)
                            try:
                                async with session.post(
                                    url=billing_url,
                                    json=json_payload,
                                    auth=auth,
                                    proxy=None,
                                    timeout=timeout
                                ) as hist_response:
                                    hist_response.raise_for_status()
                                    hist_payload = await hist_response.json(content_type=None)
                                    hist_records = hist_payload.get("Record") if isinstance(hist_payload, dict) else None
                                    
                                    if isinstance(hist_records, list) and hist_records:
                                        matched_rec = None
                                        for rec in hist_records:
                                            rec_amount = rec.get("Amount", "0.00")
                                            rec_due_date = rec.get("NetDueDate", "")
                                            
                                            if normalize_amount(rec_amount) == normalize_amount(due_amount_str) and \
                                               normalize_date(rec_due_date) == normalize_date(due_date_str):
                                                matched_rec = rec
                                                break
                                        
                                        # Only display if a match was found
                                        if matched_rec:
                                            consumption_val = html.escape(str(matched_rec.get("Consumption", "N/A")).strip())
                                            doc_no = html.escape(str(matched_rec.get("DocumentNo", "N/A")).strip())
                                            amount = html.escape(str(matched_rec.get("Amount", "0.00")).strip())
                                            net_due_date = format_date(matched_rec.get("NetDueDate", "N/A"))
                                            bill_period = html.escape(str(matched_rec.get("BillPeriod", "N/A")).strip())
                                            prev_read = html.escape(str(matched_rec.get("PreviousRead", "N/A")).strip())
                                            curr_read = html.escape(str(matched_rec.get("CurrentRead", "N/A")).strip())
                                            
                                            history_text = (
                                                f"\n<b>More Bill Details:</b>\n"
                                                f"Document: {doc_no}\n"
                                                f"Amount: {amount}\n"
                                                f"Due Date: {net_due_date}\n"
                                                f"Consumption: {consumption_val}\n"
                                                f"Period: {bill_period}\n"
                                                f"Previous Reading: {prev_read}\n"
                                                f"Current Reading: {curr_read}"
                                            )
                            except Exception as e:
                                logger.error(f"Failed to fetch billing history for CA {ca_number}: {e}", extra=await self.extra(state, LogCategory.NETWORK_ERROR))

                        contract_account = html.escape(str(data.get('Contract_Account', '')))
                        due_amount_html = html.escape(due_amount_str)
                        due_date_html = format_date(due_date_str)

                        json_load = (
                            f"<b>Contract_Account:</b> {contract_account}\n"
                            f"<b>Due_Amount:</b> {due_amount_html}\n"
                            f"<b>Due_Date:</b> {due_date_html}\n"
                            f"<b>Consumption:</b> {consumption_val}\n"
                            f"{history_text}"
                        )
                        parse_mode = 'HTML'
                    
                    # Add inline button for checking another bill
                    inline_buttons = [[
                        InlineKeyboardButton(
                            text="Check Another Bill",
                            callback_data=self.gen(callback="check bill", btn_group="btn")
                        )
                    ]]
                    inline_markup = InlineKeyboardMarkup(inline_keyboard=inline_buttons)
                    # Add Exit as reply button
                    reply_keyboard = [[KeyboardButton(text="Exit")]]
                    reply_markup = ReplyKeyboardMarkup(
                        keyboard=reply_keyboard,
                        one_time_keyboard=True,
                        resize_keyboard=True
                    )
                    
                    await message.answer(json_load, reply_markup=reply_markup, parse_mode=parse_mode)
                    await message.answer("Would you like to check another bill?", reply_markup=inline_markup)
                    logger.info(f"Bill amount fetched successfully for CA {ca_number}", extra=await self.extra(state, LogCategory.API_SUCCESS))
                else:
                    await message.answer(f"{response.status} Sorry Something went wrong... /start the bot and try again")
                    logger.error(f"Check bill API error for CA {ca_number}: status={response.status}", extra=await self.extra(state, LogCategory.API_FAIL))
        except Exception as e:
            logger.error(f"Check bill fetch error for CA {ca_number}: {e}", extra=await self.extra(state, LogCategory.NETWORK_ERROR))
            print(f"error processing : \t{e}")
            await message.answer("Sorry, Something went wrong... please /start the bot and try again")
            await self.redirect.toMainMenu(message,state)
        finally:
            try:
                await processing.delete()
            except:
                pass