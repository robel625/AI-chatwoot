from operator import call
from turtle import mode
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
from datetime import datetime,timedelta,date
from django.db import transaction
from utils.redirect import Redirect
from zoneinfo import ZoneInfo
# from ethiopian_date import EthiopianDateConverter as EDC
from ethiopian_date_converter.ethiopian_date_convertor import to_ethiopian, EthDate, to_gregorian, get_et_month_name, get_day_no_ethiopian,get_day_of_week_name_et
import uuid
from pathlib import Path
import json
from aiogram.types import WebAppInfo
from utils.myCustomFilter import FromGen, MultiTextStateFilter, generate_btn
from bot_logger import get_bot_logger, LogCategory
from shared_aiohttp import get_shared_session

#________________________________________working_with_path____________________________________________
# making sure we are on the right path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '../')) #../..
# Add the project directory to the Python path
sys.path.append(project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "eeuBotProject.settings")
django.setup()
#________________________________________/path_______________________________________________________
# from eeuBotApp.models import MreadTgID,MreadCA,MReadReport,UserInfo,BotActivityLog,ActivityType
from eeuBotApp.models import UserInfo,BotActivityLog,ActivityType,MeterReadingSubmission
from dotenv import load_dotenv
load_dotenv()
meter_type_URL = os.getenv("meter_type_URL")
meter_type_username =  os.getenv("meter_type_username")
meter_reading_password = os.getenv("meter_reading_password")
meter_recieve_data_url = os.getenv("meter_recieve_data_url")

multiFilter = partial(MultiTextStateFilter, service_name="bilcalc")

logger = get_bot_logger("bill_calculation_service")

class BillCalcForm(StatesGroup):
    mode = State()
    catagory = State()
    caNumber = State()
    kwh= State()
    calculate = State()
    finish =State()

    
    


class Bill_calculation:
    service_name = "bilcalc"
    def __init__(self):
        self.service_name = Bill_calculation.service_name
        self.mainHandler = MainHandler()
        self.verify = Verify()
        self.router = Router()
        self.caNumberMarkup = CaNumberMarkup(self.gen)
        self.redirect =  Redirect()
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
        @self.router.callback_query(lambda call: call.data.casefold() in ["mainhandler$btn>show bill calculation".casefold()])
        async def pilot(call: CallbackQuery,state:FSMContext):
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
            
            username = call.from_user.username
            tg_id = call.from_user.id

            session_id = str(uuid.uuid4())
            await state.update_data(session_id=session_id, tg_id=str(tg_id))
            logger.info(f"User {tg_id} entered the bill calculation service", extra=await self.extra(state, LogCategory.SERVICE_ENTRY))

            all_Data = await state.get_data()
            last_interaction_time = all_Data.get("last_interaction_time")
            session_id = all_Data.get("session_id")
            tg_id = all_Data.get("tg_id")
            await state.clear()
            updates = {"last_interaction_time": last_interaction_time}
            if session_id: updates["session_id"] = session_id
            if tg_id: updates["tg_id"] = tg_id
            await state.update_data(**updates)
            # await state.set_state(BillCalcForm.catagory)
            # await self.get_catagory(call,state)
            await state.set_state(BillCalcForm.mode)
            await self.get_mode(call,state)
            
        @self.router.callback_query(multiFilter(text=["my bill","new calculation"]))
        async def _(call:CallbackQuery,state:FSMContext):
            await call.answer()
            mode = FromGen.get_callData(call.data)
            logger.info(f"Bill calculation mode selected: {mode}, tg_id {call.from_user.id}", extra=await self.extra(state, LogCategory.USER_INPUT))
            await state.update_data(mode = mode)
            await state.set_state(BillCalcForm.catagory)
            await self.get_catagory(call,state)
        
        
        @self.router.callback_query(multiFilter([BillCalcForm.catagory], text=["domestic","commercial"]))
        async def _(call:CallbackQuery,state:FSMContext):
            await call.answer()
            catagory = FromGen.get_callData(call.data)
            logger.info(f"Bill calculation category selected: {catagory}, tg_id {call.from_user.id}", extra=await self.extra(state, LogCategory.USER_INPUT))
            await state.update_data(catagory = catagory)
            await state.set_state(BillCalcForm.caNumber)
            await self.get_ca_number(call,state)
        
        @self.router.message(multiFilter([BillCalcForm.caNumber]))
        async def _(message:CallbackQuery,state:FSMContext):
            if await self.verify.ca_bp_number(message,buttons=["Exit"],allow_multiCANumber=False):
                caNumber = message.text
                await state.update_data(caNumber = caNumber)
                keyboard = [[KeyboardButton(text = "Exit")]]
                markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
                
                response = await self.get_meter_type(message,state,ca = caNumber)
                print("The response:\t",response)
                all_data = await state.get_data()
                mode = all_data.get('mode')
                valueKWH = all_data.get('valueKWH')
                readTime = all_data.get('readTime')
                taskBookId = await state.get_value("taskBookId")
                customerName = all_data.get('customerName',"")
                smrDate = datetime.strptime(all_data.get('smrDate'),"%Y-%m-%d").date() if all_data.get('smrDate') else None
                smrDate_end = datetime.strptime(all_data.get('smrDate_end'),"%Y-%m-%d").date() if all_data.get('smrDate_end') else None
                
                if response == "invalid contractAccountNo":
                    # await message.answer(f"❗️Invalid Contract Account Number. Please enter a valid Contract Account Number(CA-Number)")
                    # await message.answer(f"❗️Invalid Contract Account Number")
                    logger.warning(f"invalid contractAccountNo for CA {caNumber}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                    await message.answer(f"⚠️ Bill calculation can't be done using your CA-Number for now. Please try again later.")

                    await self.get_ca_number(message,state)
                    
                elif response == 'error':
                    logger.error(f"get_meter_type returned error for CA {caNumber}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.API_FAIL))
                    await message.answer("❗️Sorry Something went wrong while trying to get your Meter type. try again later!")
                    # await self.log_activity(message,state,activity_type=ActivityType.MeterTypeNotFound)
                    all_data = await state.get_data()
                    last_interaction_time = all_data.get("last_interaction_time")
                    await state.clear()
                    await state.update_data(last_interaction_time = last_interaction_time)
                    #redirect to the list of services(main_menu with the main menu state)
                    await state.set_state(Main_menu.main_menu)
                    await self.mainHandler.list_services(message)
                    return
                
                elif response in ['NoMeterReadingForCurrentMonth','meterReadingExists']:
                    logger.info(f"get_meter_type returned {response} for CA {caNumber}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.GENERAL))
                    if mode == 'My Bill'.casefold().strip():
                        if response =="NoMeterReadingForCurrentMonth":
                            print("am in nometer reading")
                            await state.set_state(BillCalcForm.kwh)
                            await self.kwh_get(message,state)
                        elif response == "meterReadingExists":
                            await state.set_state(BillCalcForm.calculate)
                            await self.bill_calculation(message,state)

                    elif mode == 'New Calculation'.strip().casefold():
                        if response in ['NoMeterReadingForCurrentMonth','meterReadingExists']:
                            await state.set_state(BillCalcForm.kwh)
                            await self.kwh_get(message,state)
                
                # elif response =="NoMeterReadingForCurrentMonth":
                #     print("am in nometer reading")
                #     await state.set_state(BillCalcForm.kwh)
                #     await self.kwh_get(message,state)
                # elif response == "meterReadingExists":
                #     await state.set_state(BillCalcForm.calculate)
                #     await self.bill_calculation(message,state)
                else:
                    print(f"{response}")
                    logger.error(f"Uncaught get_meter_type response for CA {caNumber}: {response}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.CODE_CRASH))
                    await message.answer(f"⚠️ We couldn't retrieve your energy meter data. Please try again later.")
                    await self.log_activity(call,state,activity_type=ActivityType.MeterTypeNotFound,metadata={"error":"response from the get_meter_type response isn't caught in =>  @self.router.message(MultiTextStateFilter(allowed_states=[BillCalcForm.caNumber]))"})
                    await self.get_ca_number(call,message)
            
        @self.router.callback_query(multiFilter([BillCalcForm.caNumber]))
        async def _(call:CallbackQuery, state:FSMContext):
            await call.answer()
            tg_id = call.from_user.id
            # await self.log_activity(tg_id=tg_id, activity_type=ActivityType.MREADING_STARTED)
            await state.update_data()
            message = call.message
            keyboard = [[KeyboardButton(text = "Exit")]]
            markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
           
            if await self.verify.ca_bp_number(call,buttons=["Exit"],allow_multiCANumber=False):
                caNumber = FromGen.get_callData(call.data)
                await state.update_data(caNumber = caNumber)
                
                print("caNumber\t:",caNumber,"type:",type(caNumber))
                
                
                    
                    # Get the meter Type
                response = await self.get_meter_type(message,state,ca = caNumber)
                print("The response:\t",response)
                all_data = await state.get_data()
                mode = all_data.get('mode')
                valueKWH = all_data.get('valueKWH')
                readTime = all_data.get('readTime')
                taskBookId = await state.get_value("taskBookId")
                customerName = all_data.get('customerName',"")
                smrDate_end = all_data.get('smrDate_end')
                    

                if response == "invalid contractAccountNo":
                    # await message.answer(f"❗️Invalid Contract Account Number. Please enter a valid Contract Account Number(CA-Number)")
                    logger.warning(f"invalid contractAccountNo for CA {caNumber}, tg_id {tg_id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                    await message.answer(f"⚠️ Bill calculation can't be done using your CA-Number for now. Please try again later.")
                    await self.get_ca_number(message,state)
                    return
                    
                elif response == 'error':
                    logger.error(f"get_meter_type returned error for CA {caNumber}, tg_id {tg_id}", extra=await self.extra(state, LogCategory.API_FAIL))
                    await message.answer("❗️Sorry Something went wrong while trying to get your Meter type. try again later!")
                    # await self.log_activity(call,state,activity_type=ActivityType.MeterTypeNotFound)
                    all_data = await state.get_data()
                    last_interaction_time = all_data.get("last_interaction_time")
                    await state.clear()
                    await state.update_data(last_interaction_time = last_interaction_time)
                    #redirect to the list of services(main_menu with the main menu state)
                    await state.set_state(Main_menu.main_menu)
                    await self.mainHandler.list_services(message)
                    return
                    
                elif response in ['NoMeterReadingForCurrentMonth','meterReadingExists']:
                    logger.info(f"get_meter_type returned {response} for CA {caNumber}, tg_id {tg_id}", extra=await self.extra(state, LogCategory.GENERAL))
                    if mode == 'My Bill'.casefold().strip():
                        if response =="NoMeterReadingForCurrentMonth":
                            print("am in nometer reading")
                            await state.set_state(BillCalcForm.kwh)
                            await self.kwh_get(message,state)
                        elif response == "meterReadingExists":
                            await state.set_state(BillCalcForm.calculate)
                            await self.bill_calculation(message,state)

                    elif mode == 'New Calculation'.strip().casefold():
                        if response in ['NoMeterReadingForCurrentMonth','meterReadingExists']:
                            await state.set_state(BillCalcForm.kwh)
                            await self.kwh_get(message,state)
                
                
                else:
                    print(f"{response}")
                    logger.error(f"Uncaught get_meter_type response for CA {caNumber}: {response}, tg_id {tg_id}", extra=await self.extra(state, LogCategory.CODE_CRASH))
                    await message.answer(f"⚠️ We couldn't retrieve your energy meter data. Please try again later.")
                    await self.log_activity(call,state,activity_type=ActivityType.MeterTypeNotFound,metadata={"error":"response from the get_meter_type isn't caught in =>  @self.router.callback_query(MultiTextStateFilter(allowed_states=[BillCalcForm.caNumber]) "})
                    await self.get_ca_number(call,message)

        @self.router.message(multiFilter([BillCalcForm.kwh]))
        async def _(message:Message,state:FSMContext):
            print("recieved kwh message")
            now = datetime.now().date()
            all_data = await state.get_data()
            meter_type = all_data.get("meterType")
            lastTimeKWH = all_data.get("lastTimeKWH")
            valueKWH = all_data.get("valueKWH")
            readTime = all_data.get("readTime")
            lastTimeDate = all_data.get("lastTimeDate")
            
            
            mode = all_data.get("mode")
            # valueKWH = all_data.get("valueKWH")
            keyboard = [[KeyboardButton(text = "Exit")]]
            markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
            print("in kwh")
            def isfloat(value):
                try:
                    float(value)
                    return True
                except ValueError:
                    return False
            kwh_input = message.text.replace(" ","")
            print("kwh_input",kwh_input)
            
            # ! Ths was added later to allow a person to re-submit his reading if he made a mistake and the previous reading was already submitted for the current month. This is done by updating the lastTimeKWH and valueKWH in the state so that the new reading can be compared with the previous reading.
            if mode == 'New Calculation'.strip().casefold():
                print("am in new calculation")
                print("mode\t",mode , '   type=>',type(mode))
                if readTime:
                    print("readtime:/t", readTime,"\t", type(readTime))
                    print("lastTimeDate:/t", lastTimeDate,"\t", type(lastTimeDate))
                    lastTimeKWH = valueKWH
                    valueKWH =  kwh_input
                    lastTimeDate = readTime
                    readTime = datetime.strftime(now, "%Y-%m-%d")
            
            if (not isfloat(kwh_input)) :  #if it is negative
                logger.info(f"Invalid KWH input (not a number): {kwh_input}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                await message.answer("❗️Make sure to enter only digits. please try again ")
                await self.kwh_get(message,state)
                return
            elif ( float(kwh_input) <  0):
                logger.info(f"Invalid KWH input (negative): {kwh_input}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                await message.answer("❗️Make sure to enter only digits. please try again ")
                await self.kwh_get(message,state)
                return
                
            # kwh_input = kwh_input[0:kwh_input.find(".")] if kwh_input.find(".")!=-1 else kwh_input
            kwh_input = int(float(kwh_input))
            print(kwh_input)
            #check validity, then allow a person to resend and  update the middleware before it is sent to SAP so that he can re-correct his mistake.
        
            
            if (kwh_input is not None) and (isfloat(kwh_input)):
                # if message.text < lastTimeKWH:
                lastTimeKWH = lastTimeKWH if lastTimeKWH else 0
                if float(kwh_input) < float(lastTimeKWH):
                    logger.warning(f"SmallerThanPreviousReading: kwh_input={kwh_input} < lastTimeKWH={lastTimeKWH}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                    text = f'''❗️The meter reading you submitted <b>👉 {float(kwh_input)} KWH</b> is <b>less than</b> the previous reading <b>➡️ {lastTimeKWH} KWH</b> .\n\nPlease ensure you enter a <b>valid reading</b>. If your meter has <b>reversed</b> or if you believe this is an error, kindly visit the <b>Customer Service Center</b> for further assistance.
                    '''
                    await self.log_activity(message,state,activity_type=ActivityType.SmallerThanPreviousReading)
                    await message.answer(text = text,reply_markup=markup)
                    await self.kwh_get(message,state)
                    return
                await state.update_data(kwh = str(kwh_input))
                if meter_type == '0':
                    print("meter_type\t",meter_type)
                    #! made changes here... when we considered adding modes
                    print("before new calculation")
                    print("mode == 'New Calculation'.strip().casefold():\t",mode == 'New Calculation'.strip().casefold() , '   mode type=>',type(mode)   )
                    if mode == 'New Calculation'.strip().casefold():                    
                        print("after new calculation"  )
                        await state.update_data(valueKWH = str(kwh_input))
                        await state.update_data(lastTimeDate = lastTimeDate )
                        await state.update_data(readTime = str(now))
                    await state.set_state(BillCalcForm.calculate)
                    await self.bill_calculation(message,state)
                else:
                    logger.warning(f"WrongMeterType (three phase) for CA {await state.get_value('caNumber')}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                    await message.answer("❗️This is service is only for Single-Phase meters")
            else:
                await message.answer("❗️Make sure to enter only digits. please try again ")
                await self.kwh_get(message,state)
                return
        
        
    async def log_activity(self,update,state:FSMContext, activity_type: str, metadata :dict = None):
        tg_id = update.from_user.id
        ca_number = await state.get_value("caNumber")
        username = update.from_user.username
        session_id = await state.get_value("session_id")
        try:
            # await sync_to_async(BotActivityLog.objects.create)(
            await BotActivityLog.objects.acreate(
                session_id = session_id if session_id else str(uuid.uuid4()),
                username = username if username else None,
                tg_id=str(tg_id),
                ca_number=ca_number,
                activity_type=activity_type,
                metadata=metadata or {}
            )
        except Exception as e:
            logger.error(f"Logging failed for activity_type={activity_type}, tg_id={tg_id}: {e}", extra=await self.extra(state, LogCategory.CODE_CRASH))
    
    async def get_mode(self,update,state:FSMContext):
        message = update if isinstance(update,Message) else update.message
        modes = ["My Bill","New Calculation"]
        
        inline_Keyboards = [[InlineKeyboardButton(text = i, callback_data=self.gen(callback=i) )] for i in modes]
        inline_markup = InlineKeyboardMarkup(inline_keyboard=inline_Keyboards)
        await message.answer("Choose your mode",reply_markup=inline_markup)
    
    async def get_catagory(self,update,state:FSMContext):
        message = update if isinstance(update,Message) else update.message
        catagories = ["Domestic","Commercial"]
        
        inline_Keyboards = [[InlineKeyboardButton(text = i, callback_data=self.gen(callback=i) )] for i in catagories]
        inline_markup = InlineKeyboardMarkup(inline_keyboard=inline_Keyboards)
        await message.answer("Chootse your meter catagory",reply_markup=inline_markup)
        
        
        # button = InlineKeyboardButton(
        #                         text="Open Form",
        #                         web_app=WebAppInfo(url="http://10.0.2.239:8081/index.html")
        #                     )
        # await message.answer("webtesting",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button]]))

    async def get_ca_number(self,update,state):
        tg_id = update.from_user.id
        message = update if isinstance(update,Message) else update.message
        query = await sync_to_async(UserInfo.objects.filter)(tgID=tg_id)
        user = await sync_to_async(query.first)()
        Inline_markup = await self.caNumberMarkup.get_Ca_InlineKeyboardMarkup(tg_id)
        await message.answer("Enter your Contract Account Number(CA-Number)")
        if Inline_markup:
            await message.answer("Your CA-Number",reply_markup=Inline_markup)
    
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

        session, proxy = await get_shared_session()
        try:
            async with session.post(
                url=f"{meter_type_URL}",
                json = json_data,
                headers= headers,
                proxy=proxy,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:

                text= await response.text() # in this case, it ddin't return json format but just plain/text format
                result = json.loads(text)
                logger.info(f"get_meter_type API response for CA {ca}: status={response.status}", extra=await self.extra(state, LogCategory.API_SUCCESS))
                print("result MeterType after aiohttp:\t",result)
                if response.status == 200:
                    # if waiting_message:
                    #     await waiting_message.delete()
                    if result.get("message"):
                        logger.warning(f"get_meter_type returned message for CA {ca}: {result.get('message')}", extra=await self.extra(state, LogCategory.API_FAIL))
                        return result.get("message") # it can be 'invalid contractAccountNo'
                    else:
                        customerName = result.get('customerName')
                        lastTimeKWH = result.get('lastTimeKWH',None)
                        lastTimeDate = datetime.strptime(result.get('lastTimeDate'), "%d/%m/%Y").date() if result.get('lastTimeDate') else None
                        smrDate = datetime.strptime (result.get('scheduledMRDate'), "%d/%m/%Y").date()
                        taskBookId = result.get('taskBookId',None)
                        region = result.get('taskBookId')[:2] if result else None
                        # smrDate_end = smrDate + timedelta(days=self.days_for_NorthandSouth) if region.casefold() in ['ab','ad'] else smrDate + timedelta(days=self.days_for_All)
                        eat_datetime = message.date.astimezone(ZoneInfo("Africa/Nairobi")) # getting Telegrams date time
                        print(f"eat_datetime\t{eat_datetime}")
                        print(f"h:m:s\t{eat_datetime.strftime("%H:%M:%S")}")
                        eat_date_str = eat_datetime.strftime("%d/%m/%Y")
                        print("eat_date_str:\t",eat_date_str)
                        now = datetime.strptime(eat_date_str, "%d/%m/%Y").date()

                        #!for showing prototype while being at different time
                        #region
                        # now_long = datetime.strptime("28/11/2025","%d/%m/%Y")
                        
                        # now = datetime.strptime("28/08/2025","%d/%m/%Y").date() # before submission window
                        # now = now_long.date() # on submission window
                        # now = datetime.strptime("3/09/2025","%d/%m/%Y").date() # after deadline
                        #endregion

                        print("Now:\t",now)
                        readTime = datetime.strptime(result.get('readTime'), "%d/%m/%Y").date() if result.get('readTime') else None
                        meterType = result.get('meterType',None) if result else None
                        valueKWH = result.get('valueKWH',None)
                        valueKWH = valueKWH if None else valueKWH.replace(" ","").replace(',','')
                        
                        await state.update_data(now = str(now))
                        await state.update_data(customerName = customerName)
                        await state.update_data(lastTimeKWH = lastTimeKWH)
                        await state.update_data(lastTimeDate = str(lastTimeDate) if lastTimeDate else None)
                        await state.update_data(smrDate = str(smrDate) if smrDate else None)
                        # await state.update_data(smrDate_end = str(smrDate_end) if smrDate_end else None)
                        await state.update_data(taskBookId = taskBookId[:4])
                        await state.update_data(region = region)
                        await state.update_data(readTime = str(readTime) if readTime else None)
                        await state.update_data(meterType = meterType)
                        await state.update_data(valueKWH = valueKWH)
                        all_data = await state.get_data()
                        print('all_data in getmeter type:\t',all_data)
                        print("readTime:-->\t",readTime, type(readTime))

                        if readTime:
                            # print("readTime:\t",readTime)
                            # print("smrDate:\t",smrDate)
                            # # print("smrDate_end:\t",smrDate_end)
                            # if smrDate <= readTime <= smrDate_end:
                            #     print ("meterReadingExists")
                                return "meterReadingExists"
                            # if smrDate <= readTime <= smrDate_end+timedelta(days=3):
                            #     print ("meterReadingExists")
                            #     return "meterReadingExists"
                        else:
                            return "NoMeterReadingForCurrentMonth"

                        # if smrDate_end < now <= smrDate_end + timedelta(days=3):
                        #     meterType = result.get('meterType',None)
                        #     print("meterType:\t",meterType)
                        #     return str(meterType)

                        # if now > smrDate_end + timedelta(days=3):
                        #     print("DeadlineClosed")
                        #     return "DeadlineClosed"

        # need to work on the error messges here ... remember to add error conditions
        except Exception as e:
            # if waiting_message:
            #     await waiting_message.delete()
            logger.error(f"get_meter_type network error for CA {ca}: {e}", extra=await self.extra(state, LogCategory.NETWORK_ERROR))
            print(f"Error at getting meter type: \n{e}")
            await self.log_activity(update,state,activity_type=ActivityType.MeterTypeNotFound,metadata={"error":str(e)})
            return "error"
            
    async def kwh_get(self,update,state:FSMContext):
        print("in bill_calc kwh")
        mode = await state.get_value("mode")
        readTime = await state.get_value("readTime")
        lastTimeDate = await state.get_value('lastTimeDate')
        valueKWH = await state.get_value('valueKWH')
        lastTimeKWH = await state.get_value('lastTimeKWH')
        customerName = await state.get_value("customerName")
        caNumber = await state.get_value('caNumber')
        message = update if isinstance(update,Message) else update.message
        previous_reading = valueKWH if valueKWH else lastTimeKWH
        previous_reading_date = readTime if readTime else lastTimeDate
        markup = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Exit")]],one_time_keyboard=True,resize_keyboard=True)
        await message.answer(f"<b>👤 {customerName}</b>({caNumber})\n<b>🕐 Previous reading date:</b>  {previous_reading_date}\n<b>🔋 Previous KWH reading:</b>  {previous_reading}\n\nEnter your <b>KWH</b> reading. Please only write the digits ",reply_markup=markup)
    
    
    async def get_ETdate_Quartile(self, gregorian_date):
        """Returns Ethiopian quarter in 'YYYY-Q' format with CORRECT inclusive boundaries"""
        et_date = to_ethiopian( date(gregorian_date.year, gregorian_date.month, gregorian_date.day))
        et_year = et_date.year
        et_month = et_date.month
        # if et_month == 1:
        #     return f"{et_year}-1"  # January is in the 4th quarter of the previous Ethiopian year
        # if 2 <= et_month <=4:
        #     return f"{et_year}-2"
        # elif 5 <= et_month <= 7:
        #     return f"{et_year}-3"
        # elif 8 <= et_month <= 10:
        #     return f"{et_year}-4"
        # else:  # Months 11, 12, 13 (Pagume)
        #     return f"{et_year+1}-1"
        if et_month >= 11 : 
            return f"{et_year + 1}-1"
        elif et_month == 1:
            return f"{et_year}-1"
        elif 2 <= et_month <= 4:
            return f"{et_year}-2"
        elif 5 <= et_month <= 7:
            return f"{et_year}-3"
        elif 8 <= et_month <= 10:
            return f"{et_year}-4"
        else:
            return f"{et_year}-4"
 
    async def get_block(self, consumption):
        """Returns correct tariff block with NON-OVERLAPPING boundaries"""
        if consumption <= 50:
            return "1"
        elif consumption <= 100:
            return "2"
        elif consumption <= 200:
            return "3"
        elif consumption <= 300:
            return "4"
        elif consumption <= 400:
            return "5"
        elif consumption <= 500:
            return "6"
        else:  # > 500
            return "7"


    async def get_tarrif(self, catagory=None, consumption=None, date=None):
        """Fetches tariff using ACTUAL date's quarter (critical fix)"""
        path = Path(__file__).parent.parent / "EEU_datas/tarrif.json"
        with open(path, 'r', encoding='utf-8') as f:
            tariff_data = json.load(f)
        
        lookup_date = date if date else datetime.now().date()
        date_Q = await self.get_ETdate_Quartile(lookup_date)
        
        if catagory.casefold() == "domestic":
            block = await self.get_block(consumption)
            return tariff_data['blocks'][block][date_Q]
        elif catagory.casefold() == "commercial":
            return tariff_data['commercial'][date_Q]
        else:
            raise ValueError(f"Unsupported category: {catagory}")


    async def get_service_charge(self, catagory=None, consumption=None, date=None):
        """Fetches service charge using ACTUAL date's quarter with consumption-based tiering"""
        path = Path(__file__).parent.parent / "EEU_datas/service_charge.json"
        with open(path, 'r', encoding='utf-8') as f:
            sc_data = json.load(f)
        
        lookup_date = date if date else datetime.now().date()
        date_Q = await self.get_ETdate_Quartile(lookup_date)
        
        if catagory.casefold() == "domestic":
            key = ">50" if consumption > 50 else "<50"
            return sc_data['domestic'][key][date_Q]
        elif catagory.casefold() == "commercial":
            return sc_data['commercial'][date_Q]
        else:
            raise ValueError(f"Unsupported category: {catagory}")
    
    
    async def bill_calculation(self, update, state: FSMContext):
        message = update if isinstance(update, Message) else update.message
        try:
            # =============== DATA EXTRACTION ===============
            all_data = await state.get_data()
            category = all_data.get('catagory', '').casefold()
            customer_name = all_data.get('customerName', 'N/A')
            ca_number = all_data.get('caNumber', 'N/A')
            valueKWH = all_data.get("valueKWH")
            kwh_input = valueKWH if valueKWH and valueKWH.strip() != "" else all_data.get('kwh')
            current_kwh = float(kwh_input)
            readTime_str = all_data.get('readTime')
            readDate = datetime.strptime(readTime_str.strip(), "%Y-%m-%d").date() if readTime_str and readTime_str.strip() else datetime.now().date()
            lastReadingDate_str = all_data.get('lastTimeDate')
            if not lastReadingDate_str or not lastReadingDate_str.strip():
                logger.warning(f"Missing last reading date for CA {ca_number}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                await message.answer("❌ Missing last reading date. Cannot calculate bill.")
                await self.redirect.toMainMenu(update, state)
                return
            lastReadingDate = datetime.strptime(lastReadingDate_str.strip(), "%Y-%m-%d").date()
            lastTimeKWH_str = all_data.get('lastTimeKWH', "0")
            lastTimeKWH = 0.0 if lastTimeKWH_str in [None, "", " "] else float(lastTimeKWH_str)
            
            if current_kwh < lastTimeKWH:
                logger.warning(f"Current reading smaller than previous for CA {ca_number}: {current_kwh} < {lastTimeKWH}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                await message.answer(f"⚠️ Current reading ({current_kwh:,.2f} KWH) is less than previous reading ({lastTimeKWH:,.2f} KWH).")
                await self.redirect.toMainMenu(update, state)
                return
                
            # =============== CORE CALCULATIONS ===============
            total_consumption = current_kwh - lastTimeKWH
            reading_interval = (readDate - lastReadingDate).days
            if reading_interval <= 0:
                logger.warning(f"Invalid billing period for CA {ca_number}: reading_interval={reading_interval}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                await message.answer("❌ Invalid billing period (non-positive days).")
                await self.redirect.toMainMenu(update, state)
                return
                
            Qprevious = await self.get_ETdate_Quartile(lastReadingDate)
            Qcurrent = await self.get_ETdate_Quartile(readDate)
            is_same_quarter = (Qprevious == Qcurrent)
            is_standard_period = (26 <= reading_interval <= 34)
            
            # Reference dictionaries for detailed billing explanations
            QUARTER_MONTHS = {
                1: "Hamle 1 - Meskerem 30 (ሐምሌ ፩ - መስከረም ፴) ≈ Jul 8 - Oct 10",
                2: "Tikimt 1 - Tahsas 30 (ጥቅምት ፩ - ታህሳስ ፴) ≈ Oct 11 - Jan 7",
                3: "Tir 1 - Yekatit 30 (ጥር ፩ - የካቲት ፴) ≈ Jan 8 - Apr 8",
                4: "Megabit 1 - Sene 30 (መጋቢት ፩ - ሰኔ ፴) ≈ Apr 9 - Jul 7"
            }
            BLOCK_RANGES = {
                "1": "0 - 50 kwh", "2": "51 - 100 kwh", "3": "101 - 200 kwh",
                "4": "201 - 300 kwh", "5": "301 - 400 kwh", "6": "401 - 500 kwh", "7": "Above 500 kwh"
            }
            
            # =============== NON-ADJACENT QUARTERS CHECK ===============
            prev_year, prev_q = map(int, Qprevious.split('-'))
            curr_year, curr_q = map(int, Qcurrent.split('-'))
            prev_index = prev_year * 4 + prev_q
            curr_index = curr_year * 4 + curr_q
            
            if curr_index - prev_index > 1:
                logger.warning(f"Non-adjacent tariff quarters for CA {ca_number}: {Qprevious} -> {Qcurrent}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                await message.answer(
                    "⚠️ <b>Billing Period Spans Non-Adjacent Tarrif Quarters</b>\n\n"
                    "Your reading period crosses multiple tariff quarters with significant rate changes. "
                    "Automatic calculation isn't possible due to complex proration requirements.\n\n"
                )
                await self.redirect.toMainMenu(update, state)
                return
                
            # =============== BILLING LOGIC ===============
            bill_explanation = (
                f"👤 <b>Customer</b>: {customer_name}\n"
                f"🆔 <b>CA Number</b>: {ca_number}\n\n"
                f"🧾 <b>Electricity Bill Calculation Breakdown</b>\n\n"
                f"📅 <b>Billing Period</b>: {lastReadingDate.strftime('%d/%m/%Y')} → {readDate.strftime('%d/%m/%Y')} "
                f"(<b>{reading_interval} days</b>)\n\n"
                f"⚡ <b>Previous Reading</b>: {lastTimeKWH:,.2f} KWH ({lastReadingDate.strftime('%d/%m/%Y')})\n"
                f"🔋 <b>Current Reading</b>: {current_kwh:,.2f} KWH ({readDate.strftime('%d/%m/%Y')})\n"
                f"📈 <b>Total Consumption</b>: {total_consumption:,.2f} KWH\n\n"
            )
            
            energy_charge = 0.0
            service_charge_amount = 0.0
            calculation_notes = []
            
            # =============== SAME QUARTER HANDLING ===============
            if is_same_quarter:
                quarter_label = Qcurrent
                q_num = int(quarter_label.split('-')[1])
                q_year = int(quarter_label.split('-')[0])
                
                # Format year display for Q1 to show span (e.g., 2018/2019)
                year_display = f"{q_year - 1}/{q_year}" if q_num == 1 else str(q_year)
                
                bill_explanation += f"✅ <b>Same Quarter Billing</b> ({quarter_label})\n"
                bill_explanation += f"   📅 You are in <b>Quarter {q_num}</b>\n"
                bill_explanation += f"   🗓️ {QUARTER_MONTHS[q_num]}\n"
                
                if is_standard_period:
                    normalized_consumption = total_consumption
                    lookup_consumption = total_consumption
                    bill_explanation += "   → Standard period (26-34 days). Using actual consumption for tariff calculation.\n\n"
                else:
                    normalized_consumption = (total_consumption / reading_interval) * 30
                    lookup_consumption = normalized_consumption
                    bill_explanation += (
                        f"   → Non-standard period ({reading_interval} days). Normalizing to 30-day equivalent:\n"
                        f"   → ({total_consumption:,.2f} ÷ {reading_interval}) × 30 = {normalized_consumption:,.2f} KWH\n\n"
                    )
                    
                tariff = await self.get_tarrif(catagory=category, consumption=lookup_consumption, date=readDate)
                service_charge_full = await self.get_service_charge(catagory=category, consumption=total_consumption, date=readDate)
                energy_charge = total_consumption * tariff
                
                if category == "domestic":
                    block = await self.get_block(lookup_consumption)
                    bill_explanation += f"   📊 <b>Block {block}</b> ({BLOCK_RANGES[block]})\n"
                    bill_explanation += f"   💰 Your tariff for year {year_display} is <b>{tariff:,.4f} Br/Kwh</b>\n\n"
                else:
                    bill_explanation += f"   💰 Your commercial tariff for year {year_display} is <b>{tariff:,.4f} Br/Kwh</b>\n\n"
                
                if is_standard_period:
                    service_charge_amount = service_charge_full
                    service_note = f"Full monthly charge = <b>{service_charge_amount:,.2f} Br</b>"
                else:
                    service_charge_amount = (service_charge_full / 30) * reading_interval
                    service_note = f"({service_charge_full:,.2f} ÷ 30) × {reading_interval} days = <b>{service_charge_amount:,.2f} Br</b>"
                    
                calculation_notes.append(
                    f"💡 <b>Energy Charge</b>\n"
                    f"   {total_consumption:,.2f} KWH × {tariff:,.4f} Br/KWH = <b>{energy_charge:,.2f} Br</b>"
                )
                calculation_notes.append(
                    f"💡 <b>Service Charge</b>\n"
                    f"   {service_note}"
                )
                
            # =============== CROSS-QUARTER HANDLING ===============
            else:
                bill_explanation += f"⚠️ <b>Cross-Quarter Billing</b>\n"
                
                prev_q_num = int(Qprevious.split('-')[1])
                prev_q_year = int(Qprevious.split('-')[0])
                curr_q_num = int(Qcurrent.split('-')[1])
                curr_q_year = int(Qcurrent.split('-')[0])
                
                # Format year display for Q1 to show span (e.g., 2018/2019)
                prev_year_display = f"{prev_q_year - 1}/{prev_q_year}" if prev_q_num == 1 else str(prev_q_year)
                curr_year_display = f"{curr_q_year - 1}/{curr_q_year}" if curr_q_num == 1 else str(curr_q_year)
                
                bill_explanation += f"   → Previous: <b>Quarter {prev_q_num}</b> | Year {prev_year_display}\n"
                bill_explanation += f"     🗓️ {QUARTER_MONTHS[prev_q_num]}\n"
                bill_explanation += f"   → Current: <b>Quarter {curr_q_num}</b> | Year {curr_year_display}\n"
                bill_explanation += f"     🗓️ {QUARTER_MONTHS[curr_q_num]}\n"
                
                # Calculate quarter boundary
                et_start_month = {1: 11, 2: 2, 3: 5, 4: 8}[curr_q_num]  # EEU fiscal year mapping
                et_start_year = curr_q_year
                
                # CRITICAL FIX: For Quarter 1, the fiscal year label (e.g., 2019) 
                # corresponds to the Ethiopian year of Meskerem, but the quarter 
                # actually starts in Hamle of the PREVIOUS Ethiopian year (e.g., 2018).
                if curr_q_num == 1:
                    et_start_year -= 1
                    
                try:
                    greg_start = to_gregorian(EthDate(1, et_start_month, et_start_year)).date()
                    quarter_start_greg = greg_start
                except Exception as e:
                    logger.error(f"Quarter boundary error for CA {ca_number}: {e}", extra=await self.extra(state, LogCategory.CODE_CRASH))
                    await message.answer("❌ Error calculating quarter boundary. Contact support.")
                    print(f"Quarter boundary error: {e}")
                    await self.redirect.toMainMenu(update, state)
                    return
                    
                days_in_prev_q = (quarter_start_greg - lastReadingDate).days - 1
                days_in_curr_q = (readDate - quarter_start_greg).days + 1
                
                if days_in_prev_q <= 0 or days_in_curr_q <= 0 or (days_in_prev_q + days_in_curr_q) != reading_interval:
                    logger.warning(f"Complex billing period for CA {ca_number}: prev_days={days_in_prev_q}, curr_days={days_in_curr_q}, interval={reading_interval}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                    await message.answer(
                        "⚠️ Complex billing period detected. "
                        "Automatic calculation isn't possible due to date alignment issues.\n\n"
                    )
                    await self.redirect.toMainMenu(update, state)
                    return
                    
                bill_explanation += (
                    f"   → Days in Quarter {prev_q_num}: {days_in_prev_q} days "
                    f"({lastReadingDate.strftime('%d/%m/%Y')} → {quarter_start_greg.strftime('%d/%m/%Y')})\n"
                    f"   → Days in Quarter {curr_q_num}: {days_in_curr_q} days "
                    f"({(quarter_start_greg + timedelta(days=1)).strftime('%d/%m/%Y')} → {readDate.strftime('%d/%m/%Y')})\n"
                )
                
                cons_prev_q = (total_consumption * days_in_prev_q) / reading_interval
                cons_curr_q = (total_consumption * days_in_curr_q) / reading_interval
                
                if is_standard_period:
                    lookup_consumption = total_consumption
                    bill_explanation += (
                        f"   → Standard period ({reading_interval} days). "
                        f"Using TOTAL consumption ({total_consumption:,.2f} KWH) to determine tariff blocks for BOTH quarters.\n\n"
                    )
                else:
                    lookup_consumption = (total_consumption / reading_interval) * 30
                    bill_explanation += (
                        f"   → Non-standard period ({reading_interval} days). "
                        f"Normalizing TOTAL consumption to 30-day equivalent for tariff lookup in BOTH quarters.\n"
                        f"   → Normalized total: ({total_consumption:,.2f} ÷ {reading_interval}) × 30 = <b>{lookup_consumption:,.2f} KWH</b>\n\n"
                    )
                    
                tariff_prev = await self.get_tarrif(catagory=category, consumption=lookup_consumption, date=lastReadingDate)
                tariff_curr = await self.get_tarrif(catagory=category, consumption=lookup_consumption, date=readDate)
                
                if category == "domestic":
                    block = await self.get_block(lookup_consumption)
                    block_str = f"Block {block} ({BLOCK_RANGES[block]})"
                else:
                    block_str = "Commercial Rate"
                    
                energy_prev = (lookup_consumption * tariff_prev * days_in_prev_q) / 30
                energy_curr = (lookup_consumption * tariff_curr * days_in_curr_q) / 30
                
                sc_prev_full = await self.get_service_charge(catagory=category, consumption=cons_prev_q, date=lastReadingDate)
                sc_curr_full = await self.get_service_charge(catagory=category, consumption=cons_curr_q, date=readDate)
                sc_prev = (sc_prev_full * days_in_prev_q) / 30
                sc_curr = (sc_curr_full * days_in_curr_q) / 30
                
                energy_charge = energy_prev + energy_curr
                service_charge_amount = sc_prev + sc_curr
                
                calculation_notes.append(
                    f"💡 <b>Quarter {prev_q_num} Segment (Energy)</b>\n"
                    f"   📅 {QUARTER_MONTHS[prev_q_num]}\n"
                    f"   📊 {block_str} | 💰 Tariff for year {prev_year_display}: {tariff_prev:,.4f} Br/KWH\n"
                    f"   [({lookup_consumption:,.2f} KWH × {tariff_prev:,.4f} Br/KWH) ÷ 30] × {days_in_prev_q} days\n"
                    f"   = <b>{energy_prev:,.2f} Br</b>"
                )
                calculation_notes.append(
                    f"💡 <b>Quarter {curr_q_num} Segment (Energy)</b>\n"
                    f"   📅 {QUARTER_MONTHS[curr_q_num]}\n"
                    f"   📊 {block_str} | 💰 Tariff for year {curr_year_display}: {tariff_curr:,.4f} Br/KWH\n"
                    f"   [({lookup_consumption:,.2f} KWH × {tariff_curr:,.4f} Br/KWH) ÷ 30] × {days_in_curr_q} days\n"
                    f"   = <b>{energy_curr:,.2f} Br</b>"
                )
                calculation_notes.append(
                    f"💡 <b>Quarter {prev_q_num} Segment (Service)</b>\n"
                    f"   [({sc_prev_full:,.2f} Br ÷ 30) × {days_in_prev_q} days] = <b>{sc_prev:,.2f} Br</b>"
                )
                calculation_notes.append(
                    f"💡 <b>Quarter {curr_q_num} Segment (Service)</b>\n"
                    f"   [({sc_curr_full:,.2f} Br ÷ 30) × {days_in_curr_q} days] = <b>{sc_curr:,.2f} Br</b>"
                )
                
            # =============== FEES CALCULATION (WITH EXPLICIT FORMULAS) ===============
            regulatory_fee = (energy_charge + service_charge_amount) * 0.005
            vat = (energy_charge + service_charge_amount) * 0.15 if total_consumption > 200 else 0.0
            tv_levy = 10.0 if (is_standard_period and total_consumption > 50) else ((10.0 / 30) * reading_interval if total_consumption > 50 else 0.0)
            total_bill = energy_charge + service_charge_amount + regulatory_fee + vat + tv_levy
            
            # =============== BUILD FINAL EXPLANATION ===============
            bill_explanation += "\n".join(calculation_notes) + "\n\n"
            
            bill_explanation += (
                f"💡 <b>Regulatory Fee (0.5%)</b>\n"
                f"   Formula: 0.5% × (Energy Charge + Service Charge)\n"
                f"   0.5% × ({energy_charge:,.2f} + {service_charge_amount:,.2f}) = <b>{regulatory_fee:,.2f} Br</b>\n\n"
            )
            
            bill_explanation += f"💡 <b>VAT (15%)</b>\n"
            if total_consumption > 200:
                bill_explanation += (
                    f"   Formula: 15% × (Energy Charge + Service Charge)\n"
                    f"   Applied (consumption > 200 KWH)\n"
                    f"   15% × ({energy_charge:,.2f} + {service_charge_amount:,.2f}) = <b>{vat:,.2f} Br</b>\n\n"
                )
            else:
                bill_explanation += "   ❌ Not applied (consumption ≤ 200 KWH)\n\n"
                
            bill_explanation += f"💡 <b>TV Levy</b>\n"
            if total_consumption > 50:
                if is_standard_period:
                    bill_explanation += (
                        f"   Formula: Fixed 10.00 Br (standard period)\n"
                        f"   Applied (consumption > 50 KWH) = <b>{tv_levy:,.2f} Br</b>\n\n"
                    )
                else:
                    bill_explanation += (
                        f"   Formula: (10.00 Br ÷ 30) × {reading_interval} days\n"
                        f"   Applied (consumption > 50 KWH) = <b>{tv_levy:,.2f} Br</b>\n\n"
                    )
            else:
                bill_explanation += "   ❌ Not applied (consumption ≤ 50 KWH)\n\n"
                
            bill_explanation += (
                f"✅ <b>Total Estimated Bill</b>\n"
                f"   {energy_charge:,.2f} Br (Energy Charge)\n"
                f" + {service_charge_amount:,.2f} Br (Service Charge)\n"
                f" + {regulatory_fee:,.2f} Br (Regulatory Fee)\n"
                f" + {vat:,.2f} Br (VAT)\n"
                f" + {tv_levy:,.2f} Br (TV Levy)\n"
                f"{'─' * 35}\n"
                f" = <b>{total_bill:,.2f} Br</b>\n\n"
            )
            
            period_type = "Standard period (26–34 days)" if is_standard_period else f"Non-standard period ({reading_interval} days)"
            quarter_note = (
                "Same-quarter pricing" if is_same_quarter 
                else "Cross-quarter proration: Energy charge uses [ (Consumption × Tariff) ÷ 30 ] × Segment Days for BOTH quarters"
            )
            
            bill_explanation += (
                f"ℹ️ <b>Calculation Notes</b>\n"
                f"• {period_type}\n"
                f"• {quarter_note}\n" 
                f"• Ethiopian calendar quarters used per EEU billing rules"
            )
            
            # =============== SEND RESULT ===============
            keyboard = [[KeyboardButton(text="Exit")]]
            markup = ReplyKeyboardMarkup(keyboard=keyboard, one_time_keyboard=True, resize_keyboard=True)
            await message.answer(bill_explanation, parse_mode="HTML", reply_markup=markup)
            logger.info(f"Bill calculated successfully for CA {ca_number}, total_bill={total_bill:,.2f}", extra=await self.extra(state, LogCategory.API_SUCCESS))
            
        except Exception as e:
            logger.error(f"Bill calculation error for CA {ca_number}: {e}", extra=await self.extra(state, LogCategory.CODE_CRASH))
            await message.answer("⚠️ Bill calculation failed. Please contact support with your CA number.")
            print(f"Bill calculation error: {e}")
            import traceback
            traceback.print_exc()
            await self.redirect.toMainMenu(update, state)
    
    # async def bill_calculation(self, update, state: FSMContext):
    #     message = update if isinstance(update, Message) else update.message
    #     try:
    #         # =============== DATA EXTRACTION ===============
    #         all_data = await state.get_data()
    #         category = all_data.get('catagory', '').casefold()
    #         customer_name = all_data.get('customerName', 'N/A')
    #         ca_number = all_data.get('caNumber', 'N/A')
            
    #         valueKWH = all_data.get("valueKWH")
    #         kwh_input = valueKWH if valueKWH and valueKWH.strip() != "" else all_data.get('kwh')
    #         current_kwh = float(kwh_input)
            
    #         readTime_str = all_data.get('readTime')
    #         readDate = datetime.strptime(readTime_str.strip(), "%Y-%m-%d").date() if readTime_str and readTime_str.strip() else datetime.now().date()
            
    #         lastReadingDate_str = all_data.get('lastTimeDate')
    #         if not lastReadingDate_str or not lastReadingDate_str.strip():
    #             await message.answer("❌ Missing last reading date. Cannot calculate bill.")
    #             await self.redirect.toMainMenu(update, state)
    #             return
    #         lastReadingDate = datetime.strptime(lastReadingDate_str.strip(), "%Y-%m-%d").date()
            
    #         lastTimeKWH_str = all_data.get('lastTimeKWH', "0")
    #         lastTimeKWH = 0.0 if lastTimeKWH_str in [None, "", " "] else float(lastTimeKWH_str)
            
    #         if current_kwh < lastTimeKWH:
    #             await message.answer(f"⚠️ Current reading ({current_kwh:,.2f} KWH) is less than previous reading ({lastTimeKWH:,.2f} KWH).")
    #             await self.redirect.toMainMenu(update, state)
    #             return
            
    #         # =============== CORE CALCULATIONS ===============
    #         total_consumption = current_kwh - lastTimeKWH
    #         reading_interval = (readDate - lastReadingDate).days
            
    #         if reading_interval <= 0:
    #             await message.answer("❌ Invalid billing period (non-positive days).")
    #             await self.redirect.toMainMenu(update, state)
    #             return
            
    #         Qprevious = await self.get_ETdate_Quartile(lastReadingDate)
    #         Qcurrent = await self.get_ETdate_Quartile(readDate)
    #         is_same_quarter = (Qprevious == Qcurrent)
    #         is_standard_period = (26 <= reading_interval <= 34)
            
    #         # =============== NON-ADJACENT QUARTERS CHECK ===============
    #         prev_year, prev_q = map(int, Qprevious.split('-'))
    #         curr_year, curr_q = map(int, Qcurrent.split('-'))
    #         prev_index = prev_year * 4 + prev_q
    #         curr_index = curr_year * 4 + curr_q
            
    #         if curr_index - prev_index > 1:
    #             await message.answer(
    #                 "⚠️ <b>Billing Period Spans Non-Adjacent Tarrif Quarters</b>\n\n"
    #                 "Your reading period crosses multiple tariff quarters with significant rate changes. "
    #                 "Automatic calculation isn't possible due to complex proration requirements.\n\n"
    #             )
    #             await self.redirect.toMainMenu(update, state)
    #             return
            
    #         # =============== BILLING LOGIC ===============
    #         bill_explanation = (
    #             f"👤 <b>Customer</b>: {customer_name}\n"
    #             f"🆔 <b>CA Number</b>: {ca_number}\n\n"
    #             f"🧾 <b>Electricity Bill Calculation Breakdown</b>\n\n"
    #             f"📅 <b>Billing Period</b>: {lastReadingDate.strftime('%d/%m/%Y')} → {readDate.strftime('%d/%m/%Y')} "
    #             f"(<b>{reading_interval} days</b>)\n\n"
    #             f"⚡ <b>Previous Reading</b>: {lastTimeKWH:,.2f} KWH ({lastReadingDate.strftime('%d/%m/%Y')})\n"
    #             f"🔋 <b>Current Reading</b>: {current_kwh:,.2f} KWH ({readDate.strftime('%d/%m/%Y')})\n"
    #             f"📈 <b>Total Consumption</b>: {total_consumption:,.2f} KWH\n\n"
    #         )
            
    #         energy_charge = 0.0
    #         service_charge_amount = 0.0
    #         calculation_notes = []
            
    #         # =============== SAME QUARTER HANDLING (UNCHANGED) ===============
    #         if is_same_quarter:
    #             quarter_label = Qcurrent
    #             bill_explanation += f"✅ <b>Same Quarter Billing</b> ({quarter_label})\n"
                
    #             if is_standard_period:
    #                 normalized_consumption = total_consumption
    #                 bill_explanation += "   → Standard period (26-34 days). Using actual consumption for tariff calculation.\n\n"
    #             else:
    #                 normalized_consumption = (total_consumption / reading_interval) * 30
    #                 bill_explanation += (
    #                     f"   → Non-standard period ({reading_interval} days). Normalizing to 30-day equivalent:\n"
    #                     f"   → ({total_consumption:,.2f} ÷ {reading_interval}) × 30 = {normalized_consumption:,.2f} KWH\n\n"
    #                 )
                
    #             tariff = await self.get_tarrif(catagory=category, consumption=normalized_consumption, date=readDate)
    #             service_charge_full = await self.get_service_charge(catagory=category, consumption=total_consumption, date=readDate)
    #             energy_charge = total_consumption * tariff
                
    #             if is_standard_period:
    #                 service_charge_amount = service_charge_full
    #                 service_note = f"Full monthly charge = <b>{service_charge_amount:,.2f} Br</b>"
    #             else:
    #                 service_charge_amount = (service_charge_full / 30) * reading_interval
    #                 service_note = f"({service_charge_full:,.2f} ÷ 30) × {reading_interval} days = <b>{service_charge_amount:,.2f} Br</b>"
                
    #             calculation_notes.append(
    #                 f"💡 <b>Energy Charge</b>\n"
    #                 f"   {total_consumption:,.2f} KWH × {tariff:,.4f} Br/KWH = <b>{energy_charge:,.2f} Br</b>"
    #             )
    #             calculation_notes.append(
    #                 f"💡 <b>Service Charge</b>\n"
    #                 f"   {service_note}"
    #             )
            
    #         # =============== CROSS-QUARTER HANDLING (CRITICAL FIX PER YOUR SPEC) ===============
    #         else:
    #             bill_explanation += f"⚠️ <b>Cross-Quarter Billing</b>\n"
    #             bill_explanation += f"   → Previous: Quarter {Qprevious.split('-')[1]} | Current: Quarter {Qcurrent.split('-')[1]}\n"
                
    #             # Calculate quarter boundary
    #             curr_q_num = int(Qcurrent.split('-')[1])
    #             et_start_month = {1: 11, 2: 2, 3: 5, 4: 8}[curr_q_num]  # EEU fiscal year mapping
    #             et_start_year = int(Qcurrent.split('-')[0])
    #             if curr_q_num == 1 :
    #                 et_start_year -= 1
                
    #             try:
    #                 greg_start = to_gregorian(EthDate(1, et_start_month,et_start_year)).date()
    #                 quarter_start_greg = greg_start
    #             except Exception as e:
    #                 await message.answer("❌ Error calculating quarter boundary. Contact support.")
    #                 print(f"Quarter boundary error: {e}")
    #                 await self.redirect.toMainMenu(update, state)
    #                 return
                
    #             days_in_prev_q = (quarter_start_greg - lastReadingDate).days -1
    #             days_in_curr_q = (readDate - quarter_start_greg).days + 1
                
    #             if days_in_prev_q <= 0 or days_in_curr_q <= 0 or (days_in_prev_q + days_in_curr_q) != reading_interval:
    #                 await message.answer(
    #                     "⚠️ Complex billing period detected. "
    #                     "Automatic calculation isn't possible due to date alignment issues.\n\n"
    #                 )
    #                 await self.redirect.toMainMenu(update, state)
    #                 return
                
    #             bill_explanation += (
    #                 f"   → Days in Quarter {Qprevious.split('-')[1]}: {days_in_prev_q} days "
    #                 f"({lastReadingDate.strftime('%d/%m/%Y')} → {quarter_start_greg.strftime('%d/%m/%Y')})\n"
    #                 f"   → Days in Quarter {Qcurrent.split('-')[1]}: {days_in_curr_q} days "
    #                 f"({(quarter_start_greg + timedelta(days=1)).strftime('%d/%m/%Y')} → {readDate.strftime('%d/%m/%Y')})\n"
    #             )
                
    #             # Calculate actual consumption per segment for service charge tier
    #             cons_prev_q = (total_consumption * days_in_prev_q) / reading_interval
    #             cons_curr_q = (total_consumption * days_in_curr_q) / reading_interval
                
    #             if is_standard_period:
    #                 # ===== STANDARD CROSS-QUARTER (26-34 days) =====
    #                 bill_explanation += (
    #                     f"   → Standard period ({reading_interval} days). "
    #                     f"Using TOTAL consumption ({total_consumption:,.2f} KWH) to determine tariff blocks for BOTH quarters.\n\n"
    #                 )
                    
    #                 # Get tariffs using TOTAL consumption for BOTH quarters
    #                 tariff_prev = await self.get_tarrif(catagory=category, consumption=total_consumption, date=lastReadingDate)
    #                 tariff_curr = await self.get_tarrif(catagory=category, consumption=total_consumption, date=readDate)
                    
    #                 # ENERGY CHARGE FORMULA (PER YOUR SPEC - WITH CONSTANT 30):
    #                 # Energy = [(Total Consumption × Tariff) ÷ 30] × Segment Days
    #                 energy_prev = (total_consumption * tariff_prev * days_in_prev_q) / 30
    #                 energy_curr = (total_consumption * tariff_curr * days_in_curr_q) / 30
                    
    #                 # SERVICE CHARGE FORMULA (PER YOUR SPEC - WITH CONSTANT 30):
    #                 # Service = (Full Service Charge ÷ 30) × Segment Days
    #                 sc_prev_full = await self.get_service_charge(catagory=category, consumption=cons_prev_q, date=lastReadingDate)
    #                 sc_curr_full = await self.get_service_charge(catagory=category, consumption=cons_curr_q, date=readDate)
    #                 sc_prev = (sc_prev_full * days_in_prev_q) / 30
    #                 sc_curr = (sc_curr_full * days_in_curr_q) / 30
                    
    #                 energy_charge = energy_prev + energy_curr
    #                 service_charge_amount = sc_prev + sc_curr
                    
    #                 calculation_notes.append(
    #                     f"💡 <b>Quarter {Qprevious.split('-')[1]} Segment (Energy)</b>\n"
    #                     f"   [({total_consumption:,.2f} KWH × {tariff_prev:,.4f} Br/KWH) ÷ 30] × {days_in_prev_q} days\n"
    #                     f"   = <b>{energy_prev:,.2f} Br</b>"
    #                 )
    #                 calculation_notes.append(
    #                     f"💡 <b>Quarter {Qcurrent.split('-')[1]} Segment (Energy)</b>\n"
    #                     f"   [({total_consumption:,.2f} KWH × {tariff_curr:,.4f} Br/KWH) ÷ 30] × {days_in_curr_q} days\n"
    #                     f"   = <b>{energy_curr:,.2f} Br</b>"
    #                 )
    #                 calculation_notes.append(
    #                     f"💡 <b>Quarter {Qprevious.split('-')[1]} Segment (Service)</b>\n"
    #                     f"   Actual consumption: {cons_prev_q:,.2f} KWH\n"
    #                     f"   [({sc_prev_full:,.2f} Br ÷ 30) × {days_in_prev_q} days] = <b>{sc_prev:,.2f} Br</b>"
    #                 )
    #                 calculation_notes.append(
    #                     f"💡 <b>Quarter {Qcurrent.split('-')[1]} Segment (Service)</b>\n"
    #                     f"   Actual consumption: {cons_curr_q:,.2f} KWH\n"
    #                     f"   [({sc_curr_full:,.2f} Br ÷ 30) × {days_in_curr_q} days] = <b>{sc_curr:,.2f} Br</b>"
    #                 )
                
    #             else:
    #                 # ===== NON-STANDARD CROSS-QUARTER (OUTSIDE 26-34 days) =====
    #                 normalized_total = (total_consumption / reading_interval) * 30
    #                 bill_explanation += (
    #                     f"   → Non-standard period ({reading_interval} days). "
    #                     f"Normalizing TOTAL consumption to 30-day equivalent for tariff lookup in BOTH quarters.\n"
    #                     f"   → Normalized total: ({total_consumption:,.2f} ÷ {reading_interval}) × 30 = <b>{normalized_total:,.2f} KWH</b>\n\n"
    #                 )
                    
    #                 # Get tariffs using NORMALIZED TOTAL consumption for BOTH quarters
    #                 tariff_prev = await self.get_tarrif(catagory=category, consumption=normalized_total, date=lastReadingDate)
    #                 tariff_curr = await self.get_tarrif(catagory=category, consumption=normalized_total, date=readDate)
                    
    #                 # ENERGY CHARGE FORMULA (PER YOUR SPEC - WITH CONSTANT 30):
    #                 # Energy = [(Normalized Total × Tariff) ÷ 30] × Segment Days
    #                 energy_prev = (normalized_total * tariff_prev * days_in_prev_q) / 30
    #                 energy_curr = (normalized_total * tariff_curr * days_in_curr_q) / 30
                    
    #                 # SERVICE CHARGE FORMULA (UNCHANGED - WITH CONSTANT 30):
    #                 sc_prev_full = await self.get_service_charge(catagory=category, consumption=cons_prev_q, date=lastReadingDate)
    #                 sc_curr_full = await self.get_service_charge(catagory=category, consumption=cons_curr_q, date=readDate)
    #                 sc_prev = (sc_prev_full * days_in_prev_q) / 30
    #                 sc_curr = (sc_curr_full * days_in_curr_q) / 30
                    
    #                 energy_charge = energy_prev + energy_curr
    #                 service_charge_amount = sc_prev + sc_curr
                    
    #                 calculation_notes.append(
    #                     f"💡 <b>Quarter {Qprevious.split('-')[1]} Segment (Energy)</b>\n"
    #                     f"   Normalized total: {normalized_total:,.2f} KWH\n"
    #                     f"   [({normalized_total:,.2f} KWH × {tariff_prev:,.4f} Br/KWH) ÷ 30] × {days_in_prev_q} days\n"
    #                     f"   = <b>{energy_prev:,.2f} Br</b>"
    #                 )
    #                 calculation_notes.append(
    #                     f"💡 <b>Quarter {Qcurrent.split('-')[1]} Segment (Energy)</b>\n"
    #                     f"   Normalized total: {normalized_total:,.2f} KWH\n"
    #                     f"   [({normalized_total:,.2f} KWH × {tariff_curr:,.4f} Br/KWH) ÷ 30] × {days_in_curr_q} days\n"
    #                     f"   = <b>{energy_curr:,.2f} Br</b>"
    #                 )
    #                 calculation_notes.append(
    #                     f"💡 <b>Quarter {Qprevious.split('-')[1]} Segment (Service)</b>\n"
    #                     f"   Actual consumption: {cons_prev_q:,.2f} KWH\n"
    #                     f"   [({sc_prev_full:,.2f} Br ÷ 30) × {days_in_prev_q} days] = <b>{sc_prev:,.2f} Br</b>"
    #                 )
    #                 calculation_notes.append(
    #                     f"💡 <b>Quarter {Qcurrent.split('-')[1]} Segment (Service)</b>\n"
    #                     f"   Actual consumption: {cons_curr_q:,.2f} KWH\n"
    #                     f"   [({sc_curr_full:,.2f} Br ÷ 30) × {days_in_curr_q} days] = <b>{sc_curr:,.2f} Br</b>"
    #                 )
            
    #         # =============== FEES CALCULATION (WITH EXPLICIT FORMULAS) ===============
    #         regulatory_fee = (energy_charge + service_charge_amount) * 0.005
    #         vat = (energy_charge + service_charge_amount) * 0.15 if total_consumption > 200 else 0.0
    #         tv_levy = 10.0 if (is_standard_period and total_consumption > 50) else ((10.0 / 30) * reading_interval if total_consumption > 50 else 0.0)
    #         total_bill = energy_charge + service_charge_amount + regulatory_fee + vat + tv_levy
            
    #         # =============== BUILD FINAL EXPLANATION ===============
    #         bill_explanation += "\n".join(calculation_notes) + "\n\n"
            
    #         # Regulatory Fee with formula description
    #         bill_explanation += (
    #             f"💡 <b>Regulatory Fee (0.5%)</b>\n"
    #             f"   Formula: 0.5% × (Energy Charge + Service Charge)\n"
    #             f"   0.5% × ({energy_charge:,.2f} + {service_charge_amount:,.2f}) = <b>{regulatory_fee:,.2f} Br</b>\n\n"
    #         )
            
    #         # VAT with formula description
    #         bill_explanation += f"💡 <b>VAT (15%)</b>\n"
    #         if total_consumption > 200:
    #             bill_explanation += (
    #                 f"   Formula: 15% × (Energy Charge + Service Charge)\n"
    #                 f"   Applied (consumption > 200 KWH)\n"
    #                 f"   15% × ({energy_charge:,.2f} + {service_charge_amount:,.2f}) = <b>{vat:,.2f} Br</b>\n\n"
    #             )
    #         else:
    #             bill_explanation += "   ❌ Not applied (consumption ≤ 200 KWH)\n\n"
            
    #         # TV Levy with formula description
    #         bill_explanation += f"💡 <b>TV Levy</b>\n"
    #         if total_consumption > 50:
    #             if is_standard_period:
    #                 bill_explanation += (
    #                     f"   Formula: Fixed 10.00 Br (standard period)\n"
    #                     f"   Applied (consumption > 50 KWH) = <b>{tv_levy:,.2f} Br</b>\n\n"
    #                 )
    #             else:
    #                 bill_explanation += (
    #                     f"   Formula: (10.00 Br ÷ 30) × {reading_interval} days\n"
    #                     f"   Applied (consumption > 50 KWH) = <b>{tv_levy:,.2f} Br</b>\n\n"
    #                 )
    #         else:
    #             bill_explanation += "   ❌ Not applied (consumption ≤ 50 KWH)\n\n"
            
    #         # Final Summary
    #         bill_explanation += (
    #             f"✅ <b>Total Estimated Bill</b>\n"
    #             f"   {energy_charge:,.2f} Br (Energy Charge)\n"
    #             f" + {service_charge_amount:,.2f} Br (Service Charge)\n"
    #             f" + {regulatory_fee:,.2f} Br (Regulatory Fee)\n"
    #             f" + {vat:,.2f} Br (VAT)\n"
    #             f" + {tv_levy:,.2f} Br (TV Levy)\n"
    #             f"{'─' * 35}\n"
    #             f" = <b>{total_bill:,.2f} Br</b>\n\n"
    #         )
            
    #         # Contextual footer
    #         period_type = "Standard period (26–34 days)" if is_standard_period else f"Non-standard period ({reading_interval} days)"
    #         quarter_note = (
    #             "Same-quarter pricing" if is_same_quarter 
    #             else "Cross-quarter proration: Energy charge uses [ (Consumption × Tariff) ÷ 30 ] × Segment Days for BOTH quarters"
    #         )
    #         bill_explanation += (
    #             f"ℹ️ <b>Calculation Notes</b>\n"
    #             f"• {period_type}\n"
    #             f"• {quarter_note}\n" 
    #             # f"• Service charges will be the actual tarrif it is stanard billing days(i.e 26-34 days) otherwise use  [ (Full Charge ÷ 30) × Segment Days ]\n"
    #             # f"• The same applies for fees calculated on TOTAL consumption ({total_consumption:,.2f} KWH)\n"
    #             # f"• Constant divisor '30' represents standard billing cycle days\n"
    #             f"• Ethiopian calendar quarters used per EEU billing rules"
    #         )
            
    #         # =============== SEND RESULT ===============
    #         keyboard = [[KeyboardButton(text="Exit")]]
    #         markup = ReplyKeyboardMarkup(keyboard=keyboard, one_time_keyboard=True, resize_keyboard=True)
    #         await message.answer(bill_explanation, parse_mode="HTML", reply_markup=markup)
            
    #     except Exception as e:
    #         await message.answer("⚠️ Bill calculation failed. Please contact support with your CA number.")
    #         print(f"Bill calculation error: {e}")
    #         import traceback
    #         traceback.print_exc()
    #         await self.redirect.toMainMenu(update, state)
        
        
        