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

from eeuBotApp.models import UserInfo,BotActivityLog,ActivityType,MeterReadingSubmission
from dotenv import load_dotenv
load_dotenv()

# ── IMPORTS FROM CUSTOM FILTER, LOGGER, AND SHARED SESSION ─
from utils.myCustomFilter import FromGen, MultiTextStateFilter, generate_btn
from bot_logger import get_bot_logger, LogCategory
from shared_aiohttp import get_shared_session

# ═══ CSC locator mini-app — the button opens this INSIDE Telegram ═══
FIND_CENTER_WEBAPP_URL = "https://chatbot.eeu.et:300/csc_loc/"

# Initialize the custom logger for this service
logger = get_bot_logger("find_location")

class FindLocForm(StatesGroup):
    menu = State()

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
        # Entry point: user selects Find Nearest Center
        @self.router.callback_query(lambda call: call.data.casefold() in ["mainHandler$btn>location".casefold()])
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
            logger.info(f"User {call.from_user.id} entered find nearest center service", extra=await self.extra(state, LogCategory.SERVICE_ENTRY))

            tg_id = str(call.from_user.id)
            last_interaction_time = await state.get_value('last_interaction_time')
            await state.clear()
            await state.update_data(last_interaction_time =last_interaction_time, session_id=session_id, tg_id=tg_id)
            await state.set_state(FindLocForm.menu)
            await call.message.answer("You are now in Find Nearest Center service.", reply_markup=self.exit_keyboard())
            await call.message.answer(
                "Tap the button below to open the nearest center locator:",
                reply_markup=self.center_keyboard()
            )

    def exit_keyboard(self):
        return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Exit")]], resize_keyboard=True, one_time_keyboard=True)

    def center_keyboard(self):
        """Button that opens the CSC locator web form inside Telegram."""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📍 Find Nearest Center",
                web_app=WebAppInfo(url=FIND_CENTER_WEBAPP_URL)   # opens INSIDE Telegram
            )]
        ])
