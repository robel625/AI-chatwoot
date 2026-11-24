from operator import call
from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup,ReplyKeyboardMarkup,ReplyKeyboardRemove,KeyboardButton
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
from main_handler import MainHandler
from main_handler import Main_menu
import aiohttp
import json
from datetime import datetime,timedelta
from django.db import transaction
from django.db.models import Q
from utils.redirect import Redirect
from zoneinfo import ZoneInfo
import uuid
from pathlib import Path
import json

#working_with_path____
#making sure we are on the right path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '../../')) #../..
print("find_location.py: project_root:",project_root)
#Add the project directory to the Python path
sys.path.append(project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "eeuBotProject.settings")
django.setup()
#____________________________________/path___________________________________________________

from eeuBotApp.models import UserInfo,BotActivityLog,ActivityType,MeterReadingSubmission,Staff
from dotenv import load_dotenv
load_dotenv()

# ── IMPORTS FROM CUSTOM FILTER, LOGGER, AND SHARED SESSION ─
from utils.myCustomFilter import FromGen, MultiTextStateFilter, generate_btn
from bot_logger import get_bot_logger, LogCategory
from shared_aiohttp import get_shared_session

meter_type_URL = os.getenv("meter_type_URL")
meter_type_username =  os.getenv("meter_type_username")
meter_reading_password = os.getenv("meter_reading_password")
meter_recieve_data_url = os.getenv("meter_recieve_data_url")

# 1. Create the partial filter baked with the service name
multiFilter = partial(MultiTextStateFilter, service_name="find_location")

# 2. Initialize the custom logger for this service
logger = get_bot_logger("find_location")

class FindLocForm(StatesGroup):
    caNumber = State()

class Find_location():
    service_name = "find_location"
    
    def __init__(self, bot, ami_data):
        self.service_name = Find_location.service_name
        self.mainHandler = MainHandler()
        self.redirect = Redirect()
        self.router = Router()
        self.bot = bot
        self.verify = Verify()
        self.ami_data = ami_data
        self.setup_handlers()

    def gen(self, callback: str = "", btn_group: str = "btn") -> str:
        """Generate callback data using the centralized generate_btn function."""
        return generate_btn(self.service_name, callback, btn_group)

    async def extra(self, state: FSMContext, event: str) -> dict:
        """Build the logger 'extra' dict from FSM state."""
        return {
            "catagory": event,
            "session_id": await state.get_value("session_id", "unknown"),
            "tg_id": await state.get_value("tg_id", "unknown"),
        }

    def setup_handlers(self):
        # Entry point: user selects Find Location
        @self.router.callback_query(lambda call: call.data.casefold() in ["mainHandler$btn>Find Location".casefold()])
        async def pilot(call: CallbackQuery, state: FSMContext):
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
            
            # Create ONE session id for this whole service run
            session_id = str(uuid.uuid4())
            await state.update_data(session_id=session_id, tg_id=str(call.from_user.id))
            logger.info(f"User {call.from_user.id} entered find location service", extra=await self.extra(state, LogCategory.SERVICE_ENTRY))

            tg_id = str(call.from_user.id)
            if await Staff.objects.filter(tgID=tg_id).aexists():
                last_interaction_time = await state.get_value('last_interaction_time') 
                await state.clear()
                await state.update_data(last_interaction_time =last_interaction_time, session_id=session_id, tg_id=tg_id)
                await state.set_state(FindLocForm.caNumber)
                await call.message.answer("You are now in Find Location service.", reply_markup=self.exit_keyboard())
                await call.message.answer("Please enter a 12-digit CA Number:")
            else:
                await call.message.answer("❗️ Sorry! This service is not available for you")
                await self.redirect.toMainMenu(call, state)

        # Handle CA number input (Message)
        @self.router.message(multiFilter([FindLocForm.caNumber]))
        async def handle_ca_number(message: Message, state: FSMContext):
            if await self.verify.ca_bp_number(message, buttons=["Exit"], allow_multiCANumber=False):
                ca_number = message.text.strip()
                await state.update_data(caNumber=ca_number)
                coords = self.ami_data.get(ca_number)
                if coords:
                    lat = coords["y"]
                    lon = coords["x"]
                    gmaps_link = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"
                    await message.answer_location(latitude=lat, longitude=lon, horizontal_accuracy=1)
                    await message.answer(f"Here is your location on Google Maps: {gmaps_link}", reply_markup=self.exit_keyboard())
                    return
                else:
                    result = await self.get_meter_type(message, state, ca_number)
                    if result == "success":
                        lat = await state.get_value("lat")
                        lon = await state.get_value("lon")
                        if lat and lon:
                            gmaps_link = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"
                            await message.answer_location(latitude=lat, longitude=lon, horizontal_accuracy=1)
                            await message.answer(f"Here is your location on Google Maps: {gmaps_link}", reply_markup=self.exit_keyboard())
                            return
                        result = "no_location"
                    if result == "no_location":
                        customer_name = await state.get_value("customerName") or "Customer"
                        logger.warning(f"Location not found for CA {ca_number}", extra=await self.extra(state, LogCategory.API_FAIL))
                        await message.answer(f"️Location for {customer_name} could not be found.", reply_markup=self.exit_keyboard())
                        return
                    logger.error(f"Meter info not found for CA {ca_number}", extra=await self.extra(state, LogCategory.API_FAIL))
                    await message.answer("❗️Your meter information couldn't be found.")
                    await self.redirect.toMainMenu(message, state)
                    return
            else:
                return

    def exit_keyboard(self):
        return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Exit")]], resize_keyboard=True, one_time_keyboard=True)

    async def get_meter_type(self,update,state:FSMContext,ca):
        message = update.message if isinstance(update,CallbackQuery) else update
        waiting_message = await message.answer("🔄 Processing... please wait !")
        messageID =f"{uuid.uuid1()}" #this generates unique Ids that ca be ordered
        json_data ={
                    "messageId": messageID,
                        "username": meter_type_username,
                        "password": meter_reading_password,
                    "contractAccountNo": ca
                    }
        # Mimic headers from requests exactly
        headers = {
            "User-Agent": "python-requests/2.32.3",
            "Accept-Encoding": "gzip, deflate",  # server may ignore this if not supported
            "Accept": "*/*",
            "Connection": "keep-alive",
            "Content-Type": "application/json"
        }
        
        # ✅ USE SHARED SESSION
        session, proxy = await get_shared_session()
        proxy = None 
        try:
            async with session.post(
                url=f"{meter_type_URL}",
                json = json_data,
                headers= headers,
                proxy=proxy,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                text= await response.text() 
                result = json.loads(text)
                
                logger.info(f"get_meter_type API response for CA {ca}: status={response.status}", extra=await self.extra(state, LogCategory.API_SUCCESS))
                
                if response.status == 200:
                    if result.get("message"):
                        logger.warning(f"get_meter_type returned message for CA {ca}: {result.get('message')}", extra=await self.extra(state, LogCategory.API_FAIL))
                        return result.get("message") 
                    else:
                        customerName = result.get('customerName')
                        lastTimeKWH = result.get('lastTimeKWH',None)
                        lastTimeDate = datetime.strptime(result.get('lastTimeDate'), "%d/%m/%Y").date() if result.get('lastTimeDate') else None
                        smrDate = datetime.strptime (result.get('scheduledMRDate'), "%d/%m/%Y").date()
                        taskBookId = result.get('taskBookId',None)
                        taskBookId = taskBookId[:4]
                        region = result.get('taskBookId')[:2] if result else None
                        lat = result.get('curr_lat',None)
                        lon = result.get('curr_long',None)
                        lat,long = str(lat).replace(" ",''),str(lon).replace(" ",'')
                        
                        await state.update_data(customerName = customerName)
                        await state.update_data(lastTimeKWH = lastTimeKWH)
                        await state.update_data(lastTimeDate = str(lastTimeDate) if lastTimeDate else None)
                        await state.update_data(smrDate = str(smrDate) if smrDate else None)
                        await state.update_data(region = region)
                        await state.update_data(lat = lat)
                        await state.update_data(lon = lon)
                        await state.update_data(taskBookId = taskBookId)
                        
                        if lat and long:
                            return 'success'
                        else:
                            return 'no_location'
                else:
                    logger.error(f"get_meter_type HTTP error for CA {ca}: status={response.status}", extra=await self.extra(state, LogCategory.API_FAIL))
                    print(f"Error fetching meter type: {response.status} - {text}")
                    return 'error'
        except Exception as e:
            logger.error(f"get_meter_type network error for CA {ca}: {e}", extra=await self.extra(state, LogCategory.NETWORK_ERROR))
            return 'error'