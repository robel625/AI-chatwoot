import aiohttp
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from dotenv import load_dotenv
from functools import partial
from aiogram import types
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter
from aiogram import F
from aiogram.filters import BaseFilter
from django.db import IntegrityError
from aiogram.fsm.context import FSMContext
from asgiref.sync import sync_to_async
from aiogram import Router
import os, sys, django
from utils.calander_component import CalendarModule
from EEU_datas.Eeu_updated_tree_data import Eeu_complaint_types, Eeu_CSCsForReg, Eeu_regionForGeo, geo_loc
from utils.verify import Verify
from utils.redirect import Redirect
from eeu_api import STATUS_UPDATE_API_HEADER, STATUS_UPDATE_API_URL
from aiohttp_socks import ProxyConnector, ProxyType  # For HTTP proxy support
from urllib.parse import urlparse  # For proxy parsing
import ssl  # For custom SSL context
from pathlib import Path
import json


load_dotenv()
TOKEN = os.getenv('TOKEN')
PROXY_URL = "http://172.16.2.11:8080"  # Your HTTP proxy (match bot config)

# Set global env vars for aiohttp fallback
os.environ['HTTP_PROXY'] = PROXY_URL
os.environ['HTTPS_PROXY'] = PROXY_URL

#________________________________________working_with_path____________________________________________
# making sure we are on the right path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '../')) #../..
# Add the project directory to the Python path
sys.path.append(project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "eeuBotProject.settings")
django.setup()
#________________________________________/path_______________________________________________________
from eeuBotApp.models import UserInfo

class MultiTextStateFilter(BaseFilter):
    """allowed_states:List , text: List =[] (i.e text is optional)"""
    #use when you want to filter multipple states with or without text
    #the text can be a "message.text" or a "call.data",so works when a router is invoked by a types.Message or a callback query
    #the text workd same if it's upppercase/lowercase
    # a single state also works fine
    #it returns True/False


    def __init__(self,allowed_states:list,text:list = []) -> bool:
        self.allowed_states = allowed_states
        self.text =text
    async def __call__(self,update,state):
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
    phone = State()
    ticket = State()
    diplay_status = State()
    finished = State()
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



class Check_comp_status:
    service_name = 'chckCorrStat'

    def __init__(self):
        self.service_name = Check_comp_status.service_name
        self.router = Router()
        self.verify = Verify()
        self.service_status_path = Path(__file__).parent.parent/"services_status.json"
        self.redirect = Redirect()
        
        
        self.setup_handlers()
    def gen(self, callback: str, btn_group: str = "btn") -> str:
        """Makes all call.data unique to its respective service"""
        return self.service_name.casefold().strip() + "$" + btn_group.casefold().strip() + ">" + callback.casefold().strip()
    
    def setup_handlers(self):
        def gen(target):
            return f"{self.service}{target}"

        # @self.router.callback_query(lambda call:"Check Status".lower().strip() in call.data.casefold())
        @self.router.callback_query(lambda call:call.data.casefold() in ["mainhandler$btn>Check Status".casefold()])
        async def pilot(call:types.CallbackQuery,state:FSMContext):
            #first make sure the user is registered
            
            try:
                with open(self.service_status_path,'r',encoding='utf-8') as f:
                    services = json.load(f)
                # print(f"services:\t{services}")
                this_service = FromGen.get_callData(call.data)
                if services["report corruption"]["status"] =='inactive':
                    await call.answer()
                    return
                if services["report corruption"]["status"] == "disabled":
                    text = services["report corruption"]['message']
                    if text:
                        await call.answer(text, show_alert=True)
                        await call.answer()
                        return
                    else:
                        return
            except Exception as e:
                print("error:\t",e)
                await call.answer("Something went wrong ")
                await call.answer()
                await self.redirect.toMainMenu(call,state)
                return
            
            all_Data = await state.get_data()
            last_interaction_time = all_Data.get("last_interaction_time")
            await state.clear()
            await state.update_data(last_interaction_time = last_interaction_time) #clear previous history
            await state.set_state(StatForm.phone)
            # await call.answer("WellCome to Check My Status service")
            await call.answer()
            await self.phone_handler(call)

        @self.router.message(MultiTextStateFilter(allowed_states=[StatForm.phone]))
        async def _(message:types.Message,state:FSMContext):
            if await self.verify.phone_number(message,buttons=["Exit"]):
                print("after")
                await state.update_data(phoneNumber= "+251" + message.text[-9:])
                await state.set_state(StatForm.ticket)
                await self.ticket_handler(message)

        @self.router.message(MultiTextStateFilter(allowed_states=[StatForm.ticket]))
        async def _(message:types.Message,state:FSMContext):
            if (message.content_type == 'text') and (message.text.isdigit()):
                await state.update_data(ticketNumber = message.text)
                await state.set_state(StatForm.diplay_status)
                await self.generate_status(message,state)
            else:
                await message.answer("⚠️")
                await message.answer("Enter your <b>Ticket number</b> only in digits,Please try again",reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text = "Exit")]],one_time_keyboard=True,resize_keyboard=True),parse_mode='HTML'   )



    def gen(self,callback:str,btn_group:str="btn")->str:
        """ for example gen("region","Addis Ababa")"""
        return self.service_name+"$"+btn_group+">"+callback

    async def phone_handler(self,update):
        text1 =  "📞 Tell us your <b>Phone number</b>."
        text2 = "Please enter your correct phone number as +2519xx xx xx xx, 09xx xx xx xx, +2517xx xx xx xx, 07xx xx xx xx xx. Make sure you wrote only in digits(numbers) "
        keyboard =[]
        user = await sync_to_async(UserInfo.objects.filter)(tgID = update.from_user.id)
        user = await sync_to_async(user.first)()
        if user:
            phoneFromDB = user.phone
            keyboard = [[KeyboardButton(text = f"{phoneFromDB}"),KeyboardButton(text = "Exit")]]
        else:
            keyboard = [[KeyboardButton(text = "Exit")]]
        markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
        if isinstance(update,types.CallbackQuery):
            call = update
            await call.message.answer(f"{text1}\n{text2}",reply_markup = markup,parse_mode='HTML')
        elif isinstance(update,types.Message):
            message = update
            await message.answer(f"{text1}\n{text2}",reply_markup = markup,parse_mode='HTML')

    async def ticket_handler(self,message:types.Message):
        keyboard = [[KeyboardButton(text = "Exit")]]
        markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
        await message.answer("Write down the <b>Ticket number</b> of your complaint. Please enter only digits ",reply_markup=markup,parse_mode='HTML')


    async def generate_status(self,message:types.Message,state:FSMContext):
        await message.answer("🔄 Processing... please wait !")
        all_data = await state.get_data()
        phoneNumber = all_data.get('phoneNumber')
        ticketNumber = all_data.get("ticketNumber")

        data = {
            "phoneNumber": phoneNumber,
            "ticketNumber": ticketNumber
        }
        print(data)

        # Parse proxy for connector
        proxy_parsed = urlparse(PROXY_URL)
        host = proxy_parsed.hostname
        port = proxy_parsed.port

        # Custom SSL: Disable verification for proxy cert issues
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # Configure ProxyConnector for HTTP proxy
        connector = ProxyConnector(
            proxy_type=ProxyType.HTTP,
            host=host,
            port=port,
            ssl=ssl_context,
            limit=100,
            limit_per_host=30,
            ttl_dns_cache=300,
            use_dns_cache=True
        )

        try:
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                    url=STATUS_UPDATE_API_URL,
                    headers=STATUS_UPDATE_API_HEADER,
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=45)
                ) as response:
                    if response.status in [200, 201]:
                        json_response = await response.json()
                        comp_status = json_response.get('lastaction', {}).get('status')
                        keyboard = [[KeyboardButton(text ="Exit")]]
                        reply_markup = ReplyKeyboardMarkup(keyboard=keyboard,one_time_keyboard=False,resize_keyboard=True)
                        print("stat_code\t",response.status)
                        await message.answer(f"✅ Your status is: \t👉 <i><b>{comp_status}</b></i>",parse_mode='HTML',reply_markup=reply_markup)
                        all_data =  await state.get_data()
                        last_interaction_time = all_data.get("last_interaction_time")
                        await state.clear()
                        await state.update_data(last_interaction_time = last_interaction_time)
                        await state.set_state(StatForm.finished)
                        # await message.answer("Thank you for using our Bot! For additional <b>services</b>, hit <b>/start</b> .",parse_mode='HTML')

                    elif response.status == 404 :
                        await message.answer(f"❗️ Status Not Found. Make sure to entered a correct ticket number for the respective phone number. please try again")
                        await state.clear()
                        await state.set_state(StatForm.phone)
                        await self.phone_handler(message)

                    else:
                        # print("code:",response.status_code)
                        await message.answer(f"Something went wrong. Please /start the bot and try again")
        except Exception as e:
            await message.answer(f"We are sorry!. Something went wrong. Please /start the bot and try again")
            print("else:\t",e)