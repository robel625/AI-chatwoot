from typing import Optional, Any, Dict
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
# from ethiopian_date import EthiopianDateConverter as EDC
import uuid
from pathlib import Path
import json
from dateutil.relativedelta import relativedelta
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

multiFilter = partial(MultiTextStateFilter, service_name="meterread")

logger = get_bot_logger("meter_reading_service")

class MeterReadForm(StatesGroup):
    caNumber = State()
    kwh= State()
    kvarh = State()
    kw =State()
    finish =State()
    summary = State()



class MeterRead:
    service_name = "meterread"
    def __init__(self, redis_client, bot, mru_data=None):
        self.service_name = MeterRead.service_name
        self.mainHandler = MainHandler()
        self.redirect = Redirect()
        self.router = Router()
        self.bot = bot
        self.verify = Verify()
        self.mru_data = mru_data
        self.caNumberMarkup = CaNumberMarkup(self.gen)
        self.days_for_Addis_ababa = 13 #Normal reading window for Addis Ababa
        self.days_for_all_Ethiopia = 6 #Normal reading window for all other regions
        self.days_for_customers = 5
        self.tgid_max_sending_limit : int = None #? this is meant to be the limit for how many times a single tgid can send multipple meter readings( eg we want one TG account to send for no more than 10 people's reading)
        self.ca_max_sending_limit : int = None #? this is the limit for a single ca number in a year ( maybe we'd want a person to send readings only 4 times a year.)
        self.selected_regions = ['AD04'] # replace with [] if there are none 
        # self.selected_regions = [] # replace with [] if there are none 
        self.pre_reading_days = 5
        # These currently are not in use 
        self.reading_dates= {14:20,21:27,28:4,5:11,13:26} 
        # self.reading_intervals = {'g1':5,'g2':5,'g3':5,'AA':13}
        self.paying_dates= {
                                14:[26,2],
                                21:[3,9],
                                28:[11,7],
                                5:[19,25],
                                13:[28,4]
                            }
        
        # self.group={14: "g1",21:"g2",28:"g3",5:"g4",13:"AA"}
        self.setup_handlers()

    def gen(self, callback: str, btn_group: str = "btn") -> str:
        """Makes all call.data unique to its respective service"""
        return generate_btn(self.service_name, callback, btn_group)
    
    async def get_extra_data(self, state: FSMContext) -> dict:
        """
        Extracts relevant meter reading context from FSM state for logging.
        """
        data = await state.get_data()
        
        # Calculate ExtendedSmrDate safely
        extended_smr_date = data.get('extendedSmrDate_End')
        smr_date_end_str = data.get('smrDate_end')
        taskBookId = data.get('taskBookId')
        return {
            "now": data.get('now'),
            'taskBookId': taskBookId,
            "preSmrDate": data.get('lastTimeDate'),
            "smrDate": data.get('smrDate'),
            "smrDate_End": smr_date_end_str,
            "ExtendedSmrDate": extended_smr_date,
            "lastTimeKwh": data.get('lastTimeKWH'),
            "kwhInput": data.get('kwh')
            
        }

    async def extra(self, state: FSMContext, event: str) -> dict:
        """Build the logger 'extra' dict from FSM state."""
        return {
            "catagory": event,
            "session_id": await state.get_value("session_id", "unknown"),
            "tg_id": await state.get_value("tg_id", "unknown"),
            "extra_data": await self.get_extra_data(state)
        }

    def setup_handlers(self):
        #Continue case will be here

        #starting meter reading
        @self.router.callback_query(lambda call: call.data.casefold() in ["mainHandler$btn>Send Meter Reading".casefold()])
        async def pilot(call:CallbackQuery,state:FSMContext):
            eat_datetime = call.message.date.astimezone(ZoneInfo("Africa/Nairobi"))
            print("Eat_datetime\t",eat_datetime)
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
            
            # print(uuid.uuid4())
            # eat_datetime = message.date.astimezone(ZoneInfo("Africa/Nairobi")) # getting Telegrams date time
            #checking if this Tgid has reached it's limit
            username = call.from_user.username
            tg_id = call.from_user.id

            session_id = str(uuid.uuid4())
            await state.update_data(session_id=session_id, tg_id=str(tg_id))
            logger.info(f"User {tg_id} entered the meter reading service", extra=await self.extra(state, LogCategory.SERVICE_ENTRY))

    #! Don't Forget to remove this line _______________________________________
            # if tg_id!= 6789738597:
            #     print(f"only {username} can use this service for now")
            #     await call.message.answer("This service is not available at the moment")
            #     await self.redirect.toMainMenu(call,state)
            #     return
    #!_________________________________________________________________________
        # * this part is commented out so that there wouldn't be any limit on the number of submissions
            
                
                # count = await self.get_readingsCount(tg_id=tg_id)
                # print("count in start:\t",count)
                # keyboard = [[KeyboardButton(text = "Exit")]]
                # markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
                # if (count is not None) and (count >= self.max_sending_limit):
                #     await call.message.answer(f"❗️{username}, We regret to inform you that your telegram account has reached the maximum number of allowed meter readings submissions.",reply_markup=markup)
                #     await self.redirect.toMainMenu(call,state)
                #     return
                # elif count == 'Error':
                #     await call.message.answer(f"❗️Something went wrong. please try again later",reply_markup=markup)
                #     await self.redirect.toMainMenu(call,state)
                #     return
                
            all_Data = await state.get_data()
            last_interaction_time = all_Data.get("last_interaction_time")
            session_id = all_Data.get("session_id")
            tg_id = all_Data.get("tg_id")
            await state.clear()
            updates = {"last_interaction_time": last_interaction_time}
            if session_id: updates["session_id"] = session_id
            if tg_id: updates["tg_id"] = tg_id
            await state.update_data(**updates)
            await state.set_state(MeterReadForm.caNumber)
            await self.get_ca_number(call)
        #*______________________________________________________________________________________________________
            
            
        
        @self.router.message(multiFilter([MeterReadForm.caNumber]))
        async def _(message:Message, state:FSMContext):
            if await self.verify.ca_bp_number(message,buttons=["Exit"],allow_multiCANumber=False):
                #remove if error_message (i.e invalid contractAccountNo ) occured
                error_message = await state.get_value("error_message")
                if error_message:
                    await state.update_data(error_message=None)

                caNumber = message.text
                await state.update_data(caNumber = caNumber)
                keyboard = [[KeyboardButton(text = "Exit")]]
                markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
                # customerName = await state.get_value("customerName")
                
                print("caNumber\t:",caNumber,"type:",type(caNumber))
                #checking if the max sending limit for a ca has been reached 
                
                if self.ca_max_sending_limit:
                    count = await self.get_readingsCount(ca=caNumber)
                    print("count checking:\t",count,"\t type:\t",type(count))
                    if count == 'Error':
                        await message.answer("Sorry something went wrong. please try again later")
                        await self.redirect()

                    elif (count is not None) and (count >= self.max_sending_limit):
                        return await message.answer(f"❗️We regret to inform you that CA-Number:<b>{caNumber}</b> has reached the maximum number of allowed meter readings submissions.",reply_markup=markup)


                #region
                # else:
                response = await self.get_meter_type(message,state,ca = caNumber)
                if response == "invalid contractAccountNo":
                    logger.warning(f"invalid contractAccountNo for CA {caNumber}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                    # await message.answer(f"❗️Invalid Contract Account Number. Please enter a valid Contract Account Number(CA-Number)")
                    await message.answer(f"⚠️ You can't submit your meter reading using your CA-Number for now. Please try again later.")
                    await state.update_data(error_message=response)
                    await self.get_ca_number(message)
                    return
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
                
                all_data = await state.get_data()
                valueKWH = all_data.get('valueKWH')
                readTime = all_data.get('readTime')
                taskBookId = await state.get_value("taskBookId")
                customerName = all_data.get('customerName',"")
                smrDate = datetime.strptime(all_data.get('smrDate'),"%Y-%m-%d").date() if all_data.get('smrDate') else None
                smrDate_end = datetime.strptime(all_data.get('smrDate_end'),"%Y-%m-%d").date() if all_data.get('smrDate_end') else None
                
                # ethio_start_obj = EDC.to_ethiopian(smrDate.year, smrDate.month, smrDate.day)
                # ethio_start = f"{ethio_start_obj.day} {self._ethiopian_month_name(ethio_start_obj.month)} {ethio_start_obj.year}"
                # ethio_end_obj = EDC.to_ethiopian(smrDate_end.year, smrDate_end.month, smrDate_end.day)
                # ethio_end = f"{ethio_end_obj.day} {self._ethiopian_month_name(ethio_end_obj.month)} {ethio_end_obj.year}"
                # ethio_extra_obj = EDC.to_ethiopian(smrDate_end.year, smrDate_end.month, smrDate_end.day+self.days_for_customers)
                # ethio_extra = f"{ethio_extra_obj.day} {self._ethiopian_month_name(ethio_extra_obj.month)} {ethio_extra_obj.year}"

                smrDate_end_1 = (smrDate_end + timedelta(days=1))
                print("smrDate_end_1:\t",smrDate_end_1) 
                # ethio_end_obj_1 = EDC.to_ethiopian(smrDate_end_1.year, smrDate_end_1.month, smrDate_end_1.day)
                # ethio_end_obj_1 = EDC.date_to_ethiopian(smrDate_end_1)
                # print("ethio_end_obj_:\t",ethio_end_obj_1) 
                
                # ethio_end_1 = f"{ethio_end_obj_1.day} {self._ethiopian_month_name(ethio_end_obj_1.month)} {ethio_end_obj_1.year}"
                    
                group = all_data.get('group')
                text = f"Group: {group}" if group else ""
                group_line = f"<b>Group:</b> {group}\n" if group else ""
                
                if response == "ExceededMaxSendinglimit":
                        logger.warning(f"ExceededMaxSendinglimit for CA {caNumber}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                        await message.answer("You've exceeded the monthly submission limit.")
                        await self.log_activity(message,state,activity_type=ActivityType.ExceededMaxSendinglimit)
                        await self.redirect.toMainMenu(message,state)
                        return
                if response == "meterReadingExists":
                    logger.info(f"meterReadingExists for CA {caNumber} {text if group else ''}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.GENERAL))
                    await message.answer(f"✅ Meter reading has already been recorded for this customer. No further submission is needed at this time.\n\n"
                                            f"<b>Customer: {customerName}</b> ({caNumber})\n"
                                            f"{group_line}"
                                            f"<b>Existing Reading:</b>\t{valueKWH}KWH \n<b>Reading Date:</b>\t{readTime} ",reply_markup=markup)
                    # await self.kwh_get(message,state)
                    await self.log_activity(message,state,
                                            activity_type= ActivityType.MeterReadingExists,
                                            taskbookid = taskBookId,
                                            smrdate=all_data.get('smrDate') )
                elif response == "PreMeterReadingWindowSubmission":
                    logger.warning(f"PreMeterReadingWindowSubmission for CA {caNumber} {text if group else ''}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                    # await message.answer(f"⚠️ Meter reading submissions are not yet permitted.\n\n<b>{customerName}</b>({caNumber}) is eligible to submit readings during the following period:\n\n <b>➡️Start Date:</b>  {smrDate_end}({smrDate_end.strftime('%A')})\n <b>➡️End Date:</b>  {smrDate_end+timedelta(days=3)}({(smrDate_end+timedelta(days=3)).strftime('%A')}) \n\nPlease ensure submissions are made within this timeframe.",reply_markup=markup)
                    if self.selected_regions and (taskBookId not in self.selected_regions):
                        await message.answer(f"⚠️ Meter reading submissions are not yet permitted.\n\n"
                                             f"<b>{customerName}</b> ({caNumber})\n"
                                             f"{group_line}"
                                             f"is eligible to submit readings during the following period:\n\n"
                                             f"<b>📅</b>  ({smrDate_end_1.strftime('%d %B %Y')}) - ({(smrDate_end + timedelta(self.days_for_customers)).strftime('%d %B %Y')}) \n\n"
                                            #  f"<b>📅Ethiopian:</b>  ከ ({ethio_end_1}) እስከ ({ethio_extra}) \n\n"
                                             f"Please ensure submissions are made within this timeframe.",reply_markup=markup)
                    else:
                        await message.answer(f"⚠️ Meter reading submissions are not yet permitted.\n\n"
                                             f"<b>{customerName}</b> ({caNumber})\n"
                                             f"{group_line}"
                                             f"is eligible to submit readings during the following period:\n\n"
                                             f"<b>📅</b>  ({smrDate.strftime('%d %B %Y')}) - ({smrDate_end.strftime('%d %B %Y')}) \n\n"
                                            #  f"<b>📅Gregorian:</b>  ({smrDate.strftime('%d %B %Y')}) - ({smrDate_end.strftime('%d %B %Y')}) \n\n"
                                            #  f"<b>📅Ethiopian:</b>  ከ {ethio_start} እስከ {ethio_end} \n\n"
                                             f"Please ensure submissions are made within this timeframe.",reply_markup=markup)
                    await self.log_activity(message,state,activity_type=ActivityType.PreMeterReadingWindowSubmission,taskbookid = taskBookId,smrdate=all_data.get('smrDate')  )
                    
                elif response == "DeadlineClosed":
                    logger.warning(f"DeadlineClosed for CA {caNumber} {text if group else ''}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                    await message.answer(f"⚠️<b> Meter Reading Submission Closed</b>\n\nCustomer: <b>{customerName}</b> ({caNumber})\n"
                                            f"{group_line}"
                                            f"Your next Submission date will be around {(smrDate_end_1 + relativedelta(months=1)).strftime("%B %d/%m/%Y") }\n"
                                            f"\n❗️ The meter reading submission  window is now closed. Please wait for the next scheduled submission period.",reply_markup=markup)
                    await self.log_activity(message,state,activity_type=ActivityType.DeadlineClosed,taskbookid = taskBookId,smrdate=all_data.get('smrDate') )
                elif response in ['0','1']:
                    if response == '1':
                        logger.warning(f"WrongMeterType (three phase) for CA {caNumber}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                        await message.answer(f"Name: {customerName} ({caNumber})")
                        await message.answer("Sorry, This is service is only available for single phase meters",reply_markup=markup)
                        await self.get_ca_number(message)
                        await self.log_activity(message,state,activity_type=ActivityType.WrongMeterType)
                        return
                    
                    await state.update_data(meter_type = response)
                    await state.set_state(MeterReadForm.kwh)
                    await self.kwh_get(message,state)
                else: 
                    logger.error(f"Uncaught get_meter_type response for CA {caNumber}: {response}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.CODE_CRASH))
                    await message.answer(f"❗️ Sorry. we couldn't get your meter type. try again")
                    await self.log_activity(message,state,activity_type=ActivityType.MeterTypeNotFound,metadata={"error":"response from the get_meter_type isn't caught"})
                    await self.get_ca_number(message)

                #endregion
        @self.router.callback_query(multiFilter([MeterReadForm.caNumber]))
        async def _(call:CallbackQuery, state:FSMContext):
            await call.answer()
            tg_id = call.from_user.id
            # await self.log_activity(tg_id=tg_id, activity_type=ActivityType.MREADING_STARTED)
            error_message = await state.get_value("error_message")
            if error_message:
                await state.update_data(error_message=None)
            message = call.message
            keyboard = [[KeyboardButton(text = "Exit")]]
            markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
           
            if await self.verify.ca_bp_number(call,buttons=["Exit"],allow_multiCANumber=False):
                caNumber = FromGen.get_callData(call.data)
                await state.update_data(caNumber = caNumber)
                
                print("caNumber\t:",caNumber,"type:",type(caNumber))
                
                if self.ca_max_sending_limit:
                    count = await self.get_readingsCount(ca=caNumber)
                    print("count checking:\t",count,"\t type:\t",type(count))

                    keyboard = [[KeyboardButton(text = "Exit")]]
                    markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
                    
                    if count == 'Error':
                        await call.message.answer("Sorry something went wrong. please try again later")
                        await self.redirect.toMainMenu(call,state)

                    elif (count is not None) and (count >= self.max_sending_limit):
                        return await call.message.answer(f"❗️We regret to inform you that CA-Number: <b>{caNumber}</b> has reached the maximum number of allowed meter readings submissions.",reply_markup=markup)
                else:
                    
                    # Get the meter Type
                    response = await self.get_meter_type(message,state,ca = caNumber)
                    if response == "invalid contractAccountNo":
                        logger.warning(f"invalid contractAccountNo for CA {caNumber}, tg_id {tg_id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                        await message.answer(f"⚠️ You can't submit your meter reading using your CA-Number for now. Please try again later.")
                        await state.update_data(error_message=response)
                        # await message.answer(f"❗️Invalid Contract Account Number. Please enter a valid Contract Account Number(CA-Number)")
                        await self.get_ca_number(message)
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
                    all_data = await state.get_data()
                    valueKWH = all_data.get('valueKWH')
                    readTime = all_data.get('readTime')
                    taskBookId = await state.get_value("taskBookId")
                    customerName = all_data.get('customerName',"")
                    smrDate_end = all_data.get('smrDate_end')
                    smrDate = datetime.strptime(all_data.get('smrDate'),"%Y-%m-%d").date() if all_data.get('smrDate') else None
                    smrDate_end = datetime.strptime(all_data.get('smrDate_end'),"%Y-%m-%d").date() if all_data.get('smrDate_end') else None
                    
                    # ethio_start_obj = EDC.to_ethiopian(smrDate.year, smrDate.month, smrDate.day)
                    # ethio_start = f"{ethio_start_obj.day} {self._ethiopian_month_name(ethio_start_obj.month)} {ethio_start_obj.year}"
                    # ethio_end_obj = EDC.to_ethiopian(smrDate_end.year, smrDate_end.month, smrDate_end.day)
                    # ethio_end = f"{ethio_end_obj.day} {self._ethiopian_month_name(ethio_end_obj.month)} {ethio_end_obj.year}"
                    # ethio_extra_obj = EDC.to_ethiopian(smrDate_end.year, smrDate_end.month, smrDate_end.day+self.days_for_customers)
                    # ethio_extra = f"{ethio_extra_obj.day} {self._ethiopian_month_name(ethio_extra_obj.month)} {ethio_extra_obj.year}"

                    smrDate_end_1 = (smrDate_end + timedelta(days=1))
                    # ethio_end_obj_1 = EDC.to_ethiopian(smrDate_end_1.year, smrDate_end_1.month, smrDate_end_1.day)
                    # ethio_end_1 = f"{ethio_end_obj_1.day} {self._ethiopian_month_name(ethio_end_obj_1.month)} {ethio_end_obj_1.year}"

                    group = all_data.get('group')
                    text = f"Group: {group}" if group else ""
                    group_line = f"<b>Group:</b> {group}\n" if group else ""

                    # check if there are restrictions on selected regions
                    
                    if response == "ExceededMaxSendinglimit":
                        logger.warning(f"ExceededMaxSendinglimit for CA {caNumber}, tg_id {tg_id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                        await message.answer("You've exceeded the monthly submission limit.")
                        await self.log_activity(call,state,activity_type=ActivityType.ExceededMaxSendinglimit)
                        await self.redirect.toMainMenu(message,state)
                        return
                    if response == "meterReadingExists":
                        logger.info(f"meterReadingExists for CA {caNumber} {text if group else ''}, tg_id {tg_id}", extra=await self.extra(state, LogCategory.GENERAL))
                        await message.answer(f"✅ A meter reading has already been recorded for this customer. No further submission is needed at this time.\n\n"
                                             f"<b>Customer: {customerName}</b> ({caNumber})\n"
                                             f"{group_line}"
                                             f"<b>Existing Reading:</b>\t{valueKWH}KWH \n<b>Reading Date:</b>\t{readTime} ",reply_markup=markup)
                        await self.log_activity(call,state,activity_type=ActivityType.MeterReadingExists,taskbookid=taskBookId,smrdate=all_data.get('smrDate') )
                    elif response == "PreMeterReadingWindowSubmission":
                        logger.warning(f"PreMeterReadingWindowSubmission for CA {caNumber} {text if group else ''}, tg_id {tg_id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                        if self.selected_regions and (taskBookId not in self.selected_regions):
                            await message.answer(f"⚠️ Meter reading submissions are not yet permitted.\n\n"
                                                f"<b>{customerName}</b> ({caNumber})\n"
                                                f"{group_line}"
                                                f"is eligible to submit readings during the following period:\n\n"
                                                f"<b>📅</b>  ({smrDate_end_1.strftime('%d %B %Y')}) - ({(smrDate_end + timedelta(self.days_for_customers)).strftime('%d %B %Y')}) \n\n"
                                                # f"<b>📅Gregorian:</b>  ({smrDate_end_1.strftime('%d %B %Y')}) - ({(smrDate_end + timedelta(self.days_for_customers)).strftime('%d %B %Y')}) \n\n"
                                                # f"<b>📅Ethiopian:</b>  ከ ({ethio_end_1}) እስከ ({ethio_extra}) \n\n"
                                                f"Please ensure submissions are made within this timeframe.",reply_markup=markup)
                        else:
                            await message.answer(f"⚠️ Meter reading submissions are not yet permitted.\n\n"
                                                f"<b>{customerName}</b> ({caNumber})\n"
                                                f"{group_line}"
                                                f"is eligible to submit readings during the following period:\n\n"
                                                f"<b>📅</b>  ({smrDate.strftime('%d %B %Y')}) - ({smrDate_end.strftime('%d %B %Y')}) \n\n"
                                                # f"<b>📅Ethiopian:</b>  ከ {ethio_start} እስከ {ethio_end} \n\n"
                                                f"Please ensure submissions are made within this timeframe.",reply_markup=markup)
                        await self.log_activity(message,state,activity_type=ActivityType.PreMeterReadingWindowSubmission,taskbookid = taskBookId,smrdate=all_data.get('smrDate')  )
                    elif response == "DeadlineClosed":
                        logger.warning(f"DeadlineClosed for CA {caNumber} {text if group else ''}, tg_id {tg_id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                        await message.answer(f"⚠️<b> Meter Reading Submission Closed</b>\n\nCustomer: <b>{customerName} </b>({caNumber})\n"
                                             f"{group_line}"
                                             f"Your next Submission date will be around {(smrDate_end_1 + relativedelta(months=1)).strftime("%B %d/%m/%Y") }\n"
                                             f"\n❗️ The meter reading submission window is now closed. Please wait for the next scheduled submission period.",reply_markup=markup)
                        await self.log_activity(call,state,activity_type=ActivityType.DeadlineClosed,smrdate=all_data.get('smrDate') )
                        
                    elif response in ['0','1']:
                        if response == '1':
                            logger.warning(f"WrongMeterType (three phase) for CA {caNumber}, tg_id {tg_id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                            await message.answer(f"Name: {customerName} ({caNumber})")
                            await message.answer("Sorry, This is service is only available for single phase meters",reply_markup=markup)
                            await self.log_activity(call,state,activity_type=ActivityType.WrongMeterType)
                            await self.get_ca_number(message)
                            return
                        await state.update_data(caNumber = caNumber)
                        await state.update_data(meter_type = response)
                        await state.set_state(MeterReadForm.kwh)
                        await self.kwh_get(message,state)
                    else:
                        logger.error(f"Uncaught get_meter_type response for CA {caNumber}: {response}, tg_id {tg_id}", extra=await self.extra(state, LogCategory.CODE_CRASH))
                        await message.answer(f"❗️ Sorry. we couldn't get your meter type. try again")
                        await self.log_activity(call,state,activity_type=ActivityType.MeterTypeNotFound,metadata={"error":"response from the get_meter_type isn't caught"})
                        await self.get_ca_number(message)



        # @self.router.callback_query(lambda call: FromGen.get_callData(call.data) == "How to read KWH?".casefold())
        @self.router.callback_query(lambda call: FromGen.get_callData(call.data) == "How to read KWH?".casefold())
        async def _(call:CallbackQuery,state:FSMContext):
            await call.answer()
            message = call.message
            keyboard = [[KeyboardButton(text = "Exit")]]
            markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
            help_url = "https://media1.eeuethics.et/tests/17e08bb0-4a51-4de8-8ca3-dee6fedaeaf2-Energy_meter copy.png"
            await self.bot.send_photo(
            chat_id=message.chat.id,
            photo=help_url,  # Telegram will fetch and display it inline
            caption="How to read your KWH meter?",
            reply_markup=markup  # Optional: Attach the Exit button here too
                        )
            await message.answer("Enter your <b>KWH reading</b>. Please send only the digits")
            # await self.kwh_get(call,state)

        @self.router.message(multiFilter([MeterReadForm.kwh]))
        async def _(message:Message,state:FSMContext):
            now = datetime.now().date()
            all_data = await state.get_data()
            meter_type = all_data.get("meter_type")
            lastTimeKWH = all_data.get("lastTimeKWH")
            readTime = all_data.get("readTime")
            # valueKWH = all_data.get("valueKWH")
            keyboard = [[KeyboardButton(text = "Exit")]]
            markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )

            def isfloat(value):
                try:
                    float(value)
                    return True
                except ValueError:
                    return False
            kwh_input = message.text.replace(" ","")
            if (not isfloat(kwh_input)) :  #if it is negative
                logger.info(f"Invalid KWH input (not a number): {kwh_input}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                await message.answer("❗️Please send only the digits. please try again ")
                await self.kwh_get(message,state)
                return
            elif ( float(kwh_input) <  0):
                logger.info(f"Invalid KWH input (negative): {kwh_input}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                await message.answer("❗️Please send only the digits. please try again ")
                await self.kwh_get(message,state)
                return
            kwh_input = int(float(kwh_input))
            print(kwh_input)
            if len(str(kwh_input)) >8:
                await message.answer("❗️The number of digits you entered are greater than 8. please try again.")
                await self.kwh_get(message,state)
                return
                
            #check validity, then allow a person to resend and  update the middleware before it is sent to SAP so that he can re-correct his mistake.
            if (kwh_input is not None) and (isfloat(kwh_input)):
                # if message.text < lastTimeKWH:
                lastTimeKWH = lastTimeKWH if lastTimeKWH else 0
                if float(kwh_input) < float(lastTimeKWH):
                    if readTime and datetime.strptime(readTime,"%Y-%m-%d").date() == now:
                        pass
                    else:
                        text = f'''❗️The meter reading you submitted <b>👉 {float(kwh_input)} KWH</b> is <b>less than</b> the previous reading <b>➡️ {lastTimeKWH} KWH</b> .\n\nPlease ensure you enter a <b>valid reading</b>. If your meter has <b>reversed</b> or if you believe this is an error, kindly visit the <b>Customer Service Center</b> for further assistance.
                        '''
                        logger.warning(f"SmallerThanPreviousReading: kwh_input={kwh_input} < lastTimeKWH={lastTimeKWH}, tg_id {message.from_user.id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                        await self.log_activity(message,state,activity_type=ActivityType.SmallerThanPreviousReading)
                        await message.answer(text = text,reply_markup=markup)
                        await self.kwh_get(message,state)
                        return
                await state.update_data(kwh = int(float(kwh_input)))
                if meter_type == '0':
                    await state.set_state(MeterReadForm.summary)
                    await self.summary(message,state)
                # elif meter_type == '1':
                #     await state.set_state(MeterReadForm.kvarh)
                #     await self.kvarh_get(message)
            else:
                await message.answer("❗️Please send only the digits. Try again.")
                await self.kwh_get(message,state)

        #Incase the meter_type ==1 then we need to get KVARH and KW from the user
        # @self.router.message(MultiTextStateFilter(allowed_states=[MeterReadForm.kvarh]))
        # async def _(message:Message,state:FSMContext):
        #     if (message.text is not None) and (message.text.isdigit()):
        #         await state.update_data(kvarh  = message.text)
        #         await state.set_state(MeterReadForm.kw)
        #         await self.kw_get(message)
        #     else:
        #         await message.answer("Make sure to enter only digits. please try again ")
        #         await self.kvarh_get(message)

        # @self.router.message(MultiTextStateFilter(allowed_states=[MeterReadForm.kw]))
        # async def _(message:Message,state:FSMContext):
        #     if (message.text is not None) and (message.text.isdigit()):
        #         await state.update_data(kw  = message.text)
        #         await state.set_state(MeterReadForm.summary)
        #         await self.summary(message,state)
        #     else:
        #         await message.answer("Make sure to enter only digits. please try again ")
        #         await self.kvarh_get(message)

        @self.router.callback_query(multiFilter([MeterReadForm.summary], text=["send","cancel"]))
        async def _(call:CallbackQuery,state:FSMContext):
            await call.answer()
            callback_data = FromGen.get_callData(call.data)
            if callback_data =='cancel':
                await call.message.answer("❗️ Process Cancelled")
                await self.redirect.toMainMenu(call,state)
            elif callback_data == 'send':
                await state.set_state(MeterReadForm.finish)
                await self.submit(call,state)


 



#_________________________________functions_________________________________________________
# Log activity more th
    async def log_activity(self,update:CallbackQuery,state:FSMContext, activity_type: str, metadata :dict = None,smrdate=None,kwh_input=None, taskbookid = None):
        tg_id = update.from_user.id
        ca_number = await state.get_value("caNumber")
        username = update.from_user.username
        customer_name = await state.get_value("customerName")
        session_id = await state.get_value("session_id")
        try:
            # await sync_to_async(BotActivityLog.objects.create)(
            await BotActivityLog.objects.acreate(
                session_id = session_id if session_id else str(uuid.uuid4()),
                username = username if username else None,
                tg_id=str(tg_id),
                ca_number=ca_number,
                customer_name = customer_name,
                activity_type=activity_type,
                metadata=metadata or {},
                smrdate = smrdate if smrdate else None,
                kwh_input = kwh_input if kwh_input else None,
                taskbookid = taskbookid if taskbookid else None
               
                
            )
        except Exception as e:
            logger.error(f"Logging failed for activity_type={activity_type}, tg_id={tg_id}: {e}", extra=await self.extra(state, LogCategory.CODE_CRASH))
    
    
    # async def get_readingsCount(self, *, tg_id=None, ca=None):
    #     try:
    #         if tg_id:
    #             record = await sync_to_async(MreadTgID.objects.filter(tgID=tg_id).first)()
    #             return record.count if record else None
    #         elif ca:
    #             record = await sync_to_async(MreadCA.objects.filter(caNumber=ca).first)()
    #             return record.count if record else None
    #     except Exception as e:
    #         print(f"Error getting readings count: {e}")
    #         return 'Error'

    # async def get_readingsCount(self,*,tg_id=None,ca = None):
    #     try:
    #         @sync_to_async
    #         def for_readingsCount():
    #             if tg_id:
    #                 record  = MreadTgID.objects.filter(tgID = tg_id).first()
    #                 return record.count if record else None

    #             elif ca:
    #                 record = MreadCA.objects.filter(caNumber =ca)
    #                 return record.count if record else None
    #                 # record = MeterReading.objects.filter(caNumber = ca).first()
    #                 # return record.readingsCount_ca if record else None

    #         # return await for_readingsCount()
    #         result = await for_readingsCount()
    #         return result
    #     except Exception as e:
    #         print(f"error in get_readingsCount \t{e}" )
    #         return 'Error'

    async def get_ca_number(self,update):
        tg_id = update.from_user.id
        message = update if isinstance(update,Message) else update.message
        query = await sync_to_async(UserInfo.objects.filter)(tgID=tg_id)
        user = await sync_to_async(query.first)()
        Inline_markup = await self.caNumberMarkup.get_Ca_InlineKeyboardMarkup(tg_id)
        await message.answer("Enter your Contract Account Number(CA-Number)")
        if Inline_markup:
            await message.answer("Your CA-Number",reply_markup=Inline_markup)
        


    async def get_portion_from_mru(self, state: FSMContext, taskBookId_long: str = None) -> Optional[str]:
        """
        1) Accepts a taskBookId_long from the state (or passed directly).
        2) Uses the taskBookId_long to get the value from mru_data, returning the portion (value).
        """
        if not taskBookId_long:
            data = await state.get_data()
            taskBookId_long = data.get("taskBookId_long")
        
        if not taskBookId_long:
            return None

        # Look up in self.mru_data if available, otherwise fallback to GlobalInputs
        mru_dict = self.mru_data
        if not mru_dict:
            try:
                from global_inputs import GlobalInputs
                mru_dict = GlobalInputs.load_mru_groups()
                self.mru_data = mru_dict
            except Exception as e:
                logger.error(f"Error loading MRU data in get_portion_from_mru: {e}")
                return None

        key = str(taskBookId_long).strip()
        return mru_dict.get(key) or mru_dict.get(key.upper())

    # Alias for convenience
    get_portion = get_portion_from_mru

    @staticmethod
    def get_group_from_portion(portion: Optional[str]) -> Optional[str]:
        """
        Determines group from Portion:
        - If 'G0' exists and starts with 'PBE' -> 'Jimma & Agaro'
        - If 'G0' exists (not 'PBE') -> 'Addis Ababa'
        - If 'G1' -> 'G1'
        - If 'G2' -> 'G2'
        - If 'G3' -> 'G3'
        - If 'G4' -> 'G4'
        - It only goes up to G4. If none found, returns None (doesn't assign anything).
        """
        if not portion:
            return None
        p = str(portion).strip().upper()
        if "G0" in p:
            if p.startswith("PBE"):
                return "Jimma & Agaro"
            else:
                return "Addis Ababa"
        elif "G1" in p:
            return "G1"
        elif "G2" in p:
            return "G2"
        elif "G3" in p:
            return "G3"
        elif "G4" in p:
            return "G4"
        return None

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
        proxy = None # since we are in an internal server we don't need to use proxy
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
                if response.status == 200:
                    if result.get("message"):
                        logger.warning(f"get_meter_type returned message for CA {ca}: {result.get('message')}", extra=await self.extra(state, LogCategory.API_FAIL))
                        return result.get("message") # it can be 'invalid contractAccountNo'
                    else:
                        customerName = result.get('customerName')
                        lastTimeKWH = result.get('lastTimeKWH',None)
                        lastTimeDate = datetime.strptime(result.get('lastTimeDate'), "%d/%m/%Y").date() if result.get('lastTimeDate') else None
                        smrDate = datetime.strptime (result.get('scheduledMRDate'), "%d/%m/%Y").date()
                        preSmrDate = smrDate - timedelta(days=self.pre_reading_days)
                        taskBookId_raw = result.get('taskBookId', None)
                        taskBookId_long = taskBookId_raw
                        taskBookId = taskBookId_raw[:4] if taskBookId_raw else None
                        region = taskBookId_raw[:2] if taskBookId_raw else None
                        
                        smrDate_end = smrDate + timedelta(days=self.days_for_Addis_ababa) if region.casefold() in ['aa','ab','ac','ad'] else smrDate + timedelta(days=self.days_for_all_Ethiopia)
                        extendedSmrDate_End = smrDate_end + timedelta(days = self.days_for_customers)
                        eat_datetime = message.date.astimezone(ZoneInfo("Africa/Nairobi")) # getting Telegrams date time
                        print(f"eat_datetime\t{eat_datetime}")
                        print(f"h:m:s\t{eat_datetime.strftime("%H:%M:%S")}")
                        eat_date_str = eat_datetime.strftime("%d/%m/%Y")
                        print("eat_date_str:\t",eat_date_str)
                        now = datetime.strptime(eat_date_str, "%d/%m/%Y").date()

                        #!for showing prototype and for testing server case
                        #region
                        # now_long = datetime.strptime("23/11/2025","%d/%m/%Y")
                        # now_long = datetime.strptime("21/12/2025","%d/%m/%Y")
                        # now = now_long.date() # on submission window
                        # print("now long : ",now_long)
                        
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
                        await state.update_data(smrDate_end = str(smrDate_end) if smrDate_end else None)
                        await state.update_data(preSmrDate = str(smrDate - timedelta(days=self.pre_reading_days)) if smrDate else None)
                        await state.update_data(extendedSmrDate_End = str(smrDate_end + timedelta(days = self.days_for_customers)))
                        await state.update_data(taskBookId = taskBookId)
                        await state.update_data(taskBookId_long = taskBookId_long)
                        await state.update_data(region = region)
                        await state.update_data(readTime = str(readTime) if readTime else None)
                        await state.update_data(meterType = meterType)
                        await state.update_data(valueKWH = valueKWH)

                        # Update state data of Portion from mru_data
                        portion = await self.get_portion_from_mru(state)
                        await state.update_data(Portion = portion)

                        # Determine group and update state data with group
                        group = self.get_group_from_portion(portion)
                        if group is not None:
                            await state.update_data(group = group)
                        all_data = await state.get_data()
                        print('all_data in getmeter type:\t',all_data)
                        print("readTime:-->\t",readTime, type(readTime))
                        
                        if await self.has_exceeded_logs_limit(update,state):
                            logger.warning(f"Exceeded max sending limit for tg_id {update.from_user.id}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                            return "ExceededMaxSendinglimit"
                        if readTime:
                            logger.info(f"Meter reading already exists for CA {ca}, readTime={readTime}", extra=await self.extra(state, LogCategory.GENERAL))
                            return "meterReadingExists" 
                        
                        #making an exception for robel
                        tg_id = update.from_user.id
                        if str(tg_id) in ['354202197']: #Access For Robel
                            if now < smrDate:
                                logger.warning(f"PreMeterReadingWindowSubmission for CA {ca}, tg_id {tg_id}, now={now}, smrDate={smrDate}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                                return "PreMeterReadingWindowSubmission"
                            if smrDate <= now <= extendedSmrDate_End:
                                meterType = result.get('meterType',None)
                                return str(meterType)
                            if now > extendedSmrDate_End:
                                logger.warning(f"DeadlineClosed for CA {ca}, tg_id {tg_id}, smrDate_end={smrDate_end}, now={now}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                                return "DeadlineClosed"

                        #If self.selected_regions is given, then only the selected regions are allowed to submit reading between the smrDate and smrDate_end.
                        if self.selected_regions:
                            #If you are not amongst selected regions. 
                            # Regions ,that are not amongst the selected regions, are allowed to submit reading in the 7 consecutive days after the  last reading date(smrDate_end).
                            if taskBookId not in self.selected_regions: 
                                #if within the 7 days after smrDate_end
                                if smrDate_end < now <= smrDate_end+timedelta(days=self.days_for_customers):
                                    meterType = result.get('meterType',None)
                                    return str(meterType)
                                #if after the 7 days after smrDate_end
                                elif now > smrDate_end+timedelta(days=self.days_for_customers):
                                    logger.warning(f"DeadlineClosed for unselected region CA {ca}, tg_id {tg_id}, smrDate_end={smrDate_end}, now={now}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                                    return "DeadlineClosed"
                                # if before the smrDate_end
                                elif now <= smrDate_end :
                                    logger.warning(f"PreMeterReadingWindowSubmission for unselected region CA {ca}, tg_id {tg_id}, now={now}, smrDate_end={smrDate_end}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                                    return "PreMeterReadingWindowSubmission"
                        
                        
                        print("Am here now")
                        #pre_meter_reading_window_submission is allowed 5 days before the smrDate and the submission window is closed after the smrDate_end + self.days_for_customers
                        if (smrDate - timedelta(days=self.pre_reading_days))  <= now <= smrDate_end:
                            print("Am here now 2")
                            meterType = result.get('meterType',None)
                            return str(meterType)
                        if now > smrDate_end + timedelta(days = self.days_for_customers) :
                            logger.warning(f"DeadlineClosed for CA {ca}, tg_id {tg_id}, smrDate_end={smrDate_end}, now={now}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                            return "DeadlineClosed"
                        if now < (smrDate - timedelta(days=self.pre_reading_days)):
                            logger.warning(f"PreMeterReadingWindowSubmission for CA {ca}, tg_id {tg_id}, now={now}, smrDate={smrDate}", extra=await self.extra(state, LogCategory.VALIDATION_ERROR))
                            return "PreMeterReadingWindowSubmission"
                        

        # need to work on the error messges here ... remember to add error conditions
        except Exception as e:
            logger.error(f"get_meter_type network error for CA {ca}: {e}", extra=await self.extra(state, LogCategory.NETWORK_ERROR))
            await self.log_activity(update,state,activity_type=ActivityType.MeterTypeNotFound,metadata={"error":str(e)})
            return "error"
    async def has_exceeded_logs_limit(self,update,state:FSMContext) -> bool:
        """
        Asynchronously checks if the tg_id has more than 'limit' logs for the given smrdate.
        
        Args:
            tg_id: The Telegram user ID as string.
            smrdate: A date object (e.g., date(2025, 12, 30)).
            limit: Threshold (default 5).
        
        Returns:
            bool: True if count > limit.
        """
        # print("in has_exceeded_logs_limit")
        # if not self.tgid_max_sending_limit:
        #     print("just passing")
        #     return False
        tg_id = update.from_user.id
        smrdate = await state.get_value("smrDate")
        limit = self.tgid_max_sending_limit
        if self.tgid_max_sending_limit:
            try:
                count = await BotActivityLog.objects.filter(
                    tg_id=str(tg_id),
                    # smrdate="2025-11-24",
                    activity_type = ActivityType.SuccessfulMeterReadingSubmission
                    # activity_type = ActivityType.AdminLogin
                ).acount()  # Async count query
                
                logger.info(f"Number of submissions for {smrdate}, tg_id {tg_id} count={count}", extra=await self.extra(state, LogCategory.GENERAL))
                return count > limit
            except Exception as e:
                logger.error(f"has_exceeded_logs_limit query failed for tg_id {tg_id}: {e}", extra=await self.extra(state, LogCategory.CODE_CRASH))
                return False  # Or raise, depending on your error handling
        else:
            return False

        
    async def kwh_get(self, update, state: FSMContext):
        all_data = await state.get_data()
        customerName = await state.get_value("customerName")
        caNumber = await state.get_value('caNumber')
        group = all_data.get('group')
        group_line = f"<b>Group:</b> {group}\n" if group else ""
        message = update if isinstance(update, Message) else update.message
        previous_reading = await state.get_value('lastTimeKWH')
        previous_reading_date = await state.get_value('lastTimeDate')
        taskBookId = await state.get_value('taskBookId')
        # region = await state.get_value('region')
        
        
        smrDate = datetime.strptime(all_data.get('smrDate'), "%Y-%m-%d").date() if all_data.get('smrDate') else None
        smrDate_end = datetime.strptime(all_data.get('smrDate_end'), "%Y-%m-%d").date() if all_data.get('smrDate_end') else None

        # Format Gregorian dates
        greg_start = smrDate.strftime("%d %B %Y") if smrDate else "unknown"
        greg_end = smrDate_end.strftime("%d %B %Y") if smrDate_end else "unknown"

        # Convert to Ethiopian dates (if available)
        ethio_start = ethio_end = "unknown"
        # if smrDate:
        #     ethio_start_obj = EDC.to_ethiopian(smrDate.year, smrDate.month, smrDate.day)
        #     ethio_start = f"{ethio_start_obj.day} {self._ethiopian_month_name(ethio_start_obj.month)} {ethio_start_obj.year}"
        # else:
        #     ethio_start = "unknown"

        # if smrDate_end:
        #     ethio_end_obj = EDC.to_ethiopian(smrDate_end.year, smrDate_end.month, smrDate_end.day)
        #     ethio_end = f"{ethio_end_obj.day} {self._ethiopian_month_name(ethio_end_obj.month)} {ethio_end_obj.year}"
        # else:
        #     ethio_end = "unknown"
        
        # ethio_extra_obj = EDC.to_ethiopian(smrDate_end.year, smrDate_end.month, smrDate_end.day+self.days_for_customers)
        # ethio_extra = f"{ethio_extra_obj.day} {self._ethiopian_month_name(ethio_extra_obj.month)} {ethio_extra_obj.year}"
        smrDate_end_1 = (smrDate_end + timedelta(days=1))
        smrDate_end_extra = (smrDate_end + timedelta(self.days_for_customers)).strftime('%d %B %Y')
        # ethio_end_obj_1 = EDC.to_ethiopian(smrDate_end_1.year, smrDate_end_1.month, smrDate_end_1.day)
        # ethio_end_1 = f"{ethio_end_obj_1.day} {self._ethiopian_month_name(ethio_end_obj_1.month)} {ethio_end_obj_1.year}"


        markup = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Exit")]],
            one_time_keyboard=True,
            resize_keyboard=True
        )

        await message.answer(
            f"<b>👤 {customerName}</b> ({caNumber})\n"
            f"{group_line}"
            f"<b>🕐 Previous reading date:</b> {previous_reading_date}\n"
            f"<b>🔋 Previous KWH reading:</b> {previous_reading}\n\n"
            f"📌 <b>Submit your meter reading between:</b>\n"
            f"   📅 <i>{(smrDate_end_1.strftime('%d %B %Y')) if (self.selected_regions and taskBookId not in self.selected_regions ) else greg_start }</i> – <i>{smrDate_end_extra if (self.selected_regions and taskBookId not in self.selected_regions ) else greg_end}</i>\n"
            # f"   📅 Gregorian: <i>{(smrDate_end_1.strftime('%d %B %Y')) if (self.selected_regions and taskBookId not in self.selected_regions ) else greg_start }</i> – <i>{smrDate_end_extra if (self.selected_regions and taskBookId not in self.selected_regions ) else greg_end}</i>\n"
            # f"   📆 Ethiopian: ከ <i>{ethio_end_1 if (self.selected_regions and taskBookId not in self.selected_regions ) else ethio_start}</i>  እስከ  <i>{ethio_extra if (self.selected_regions and taskBookId not in self.selected_regions ) else ethio_end}</i>\n\n"
            "Enter your <b>KWH</b> reading. Please send only the digits.",
            reply_markup=markup,
            parse_mode="HTML"
        )

# Helper method to convert Ethiopian month number to Amharic/English nameም
    def _ethiopian_month_name(self, month_num: int) -> str:
        ethiopian_months_am = [
            "መስከረም", "ጥቅምት", "ህዳር", "ታህሳስ",
            "ጥር", "የካቲት", "መጋቢት", "ሚያዝያ",
            "ግንቦት", "ሰኔ", "ሐምሌ", "ነሐሴ", "ጳጉሜ"
        ]
        if 1 <= month_num <= 13:
            return ethiopian_months_am[month_num - 1]
        return f"ወር{month_num}"
    
    async def summary(self,message:Message,state:FSMContext):
        markup = ReplyKeyboardMarkup(keyboard =[[KeyboardButton(text="Exit")]],one_time_keyboard=True,resize_keyboard=True)
        all_data = await state.get_data()
        caNumber =  all_data.get('caNumber')
        mtype = all_data.get('meter_type')
        meter_type = lambda mtype: "Single Phase" if mtype=='0' else "Three Phase" if mtype == '1' else "Unkown"
        customer_name = all_data.get('customerName')
        print("am in summary")
        if mtype == "0":
            summary_text = (
                "Please check your information\n"
                f"👤 <b>Customer name:</b>\t{customer_name}\n"
                f"💳 <b>Account number:</b>\t{all_data.get("caNumber")}\n"
                f"⚡ <b>Meter type:</b>\t{meter_type(mtype)}\n"
                f"🔋 <b>KWH:</b>\t{all_data.get("kwh")}\n\n"
                f"Please read and be sure of the information before submiting. Once you hit send, you wont be able to edit anything."
            )
        # elif mtype == "1":
        #     summary_text = (
        #         "Please check your information\n"
        #         f"💳 account number:\t{all_data.get("caNumber")}\n"
        #         f"⚡ Meter type:\t{meter_type(mtype)}\n"
        #         f"🔋 KWH:\t{all_data.get("kwh")}\n"
        #         f"⚡ KVARH:\t{all_data.get("kvarh")}\n"
        #         f"⚡ KW:\t{all_data.get("kw")}\n"
        #     )

        markup_reply = ReplyKeyboardMarkup(keyboard =[[KeyboardButton(text ="Exit")]],one_time_keyboard=True,resize_keyboard=True)
        # await self.bill_calculation(message,state)
        await message.answer(summary_text,reply_markup=markup_reply)

        inline_markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Send",callback_data=self.gen('Send')),
                                               InlineKeyboardButton(text="❌ Cancel",callback_data=self.gen('Cancel'))]])

        await message.answer("Choose action:",reply_markup=inline_markup)
        

    async def send(self, call:CallbackQuery,state:FSMContext):
        await call.answer()

        
        # now = datetime.now()
        # now = await state.get_value("now")
        now  = call.message.date.astimezone(ZoneInfo("Africa/Nairobi"))
        read_date = now.strftime("%d/%m/%Y")   # e.g. '12/06/2025'
        read_time = now.strftime("%H:%M:%S")
        all_data = await state.get_data()
        meterType = all_data.get('meterType')
        caNumber = all_data.get('caNumber')
        kwh = all_data.get('kwh',"")
        kvarh = all_data.get('kvarh',"")
        kw = all_data.get('kw',"")
        messageID = f'{uuid.uuid1()}'

        json_data = {
        "messageId": messageID,
        "username": meter_type_username,
        "password": meter_reading_password,
        "dataList": [
                {
            "contractAccountNo": caNumber, #changing account number 100000002297
            "meterType":meterType,
            "valueKWH": kwh,
            "meterReversed":"N",
            # "valueKVARH": kvarh,
            # "valueKW": kw,
            "readDate": read_date,
            "readTime": read_time
                }
            ]
        }

        headers = {
        "User-Agent": "python-requests/2.32.3",
        "Accept-Encoding": "gzip, deflate",  # server may ignore this if not supported
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Content-Type": "application/json"
            }

        session, proxy = await get_shared_session()
        proxy = None
        try:
            async with session.post(
                meter_recieve_data_url,
                json=json_data,
                headers=headers,
                proxy=proxy,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                # content_type = response.headers.get('Content-Type', '')
                # print("Content-Type:", content_type)
                text = await response.text()
                data = json.loads(text) # data=> {"messageId":"",'state':"",'result':[{"contractAccountNo":"","errorMessage":"reading data already existed"}]}. if succcesful result =[]
                result = data.get('result')
                errorMessage = result[0].get('errorMessage') if result else None
                if response.status == 200:
                    if not result:
                        messageId = data.get('messageId')
                        await state.update_data(messageId = messageId)
                        logger.info(f"Meter reading sent successfully for CA {caNumber}, messageId={messageId}", extra=await self.extra(state, LogCategory.API_SUCCESS))
                        return 'success' # on success
                    elif result:
                        if str(errorMessage).strip().casefold() == "reading data already uploaded to SAP".casefold():
                            logger.info(f"Meter reading already uploaded to SAP for CA {caNumber}", extra=await self.extra(state, LogCategory.GENERAL))
                            return "AlreadyUploadedToSap"
                        logger.warning(f"Meter reading send error for CA {caNumber}: {errorMessage}", extra=await self.extra(state, LogCategory.API_FAIL))
                        return errorMessage
                else:
                    status_code = response.status if response.status else None
                    logger.error(f"Meter reading send HTTP error for CA {caNumber}: status={status_code}", extra=await self.extra(state, LogCategory.API_FAIL))
                    return status_code if status_code else "No status"
                # return text
        except Exception as e:
            logger.error(f"send meter reading network error for CA {caNumber}: {e}", extra=await self.extra(state, LogCategory.NETWORK_ERROR))
            await self.log_activity(call,state,activity_type=ActivityType.FailedSendingMeterReading,metadata={"error_at_sending_using_meter_recieve_data_url":str(e)})
            return "error"


    async def submit(self,call:CallbackQuery,state:FSMContext):
        tg_id = call.from_user.id
        all_data = await state.get_data()
        customer_name = all_data.get('customerName')
        caNumber  = all_data.get('caNumber')
        mtype = all_data.get('meter_type')
        readingDate = all_data.get("readTime")
        meter_type = lambda mtype: "Single Phase" if mtype=='0' else "Three Phase" if mtype == '1' else "Unkown"
        smrdate = all_data.get("smrDate")
        kwh_input = all_data.get("kwh")
        taskBookId = all_data.get("taskBookId")

        
        await call.answer()
        waiting_message = await call.message.answer("🔄 Processing... please wait !")
        result =await self.send(call,state) # sending using the meter api
        # if waiting_message: #(if waiting_message has not been deleted yet and exists)
        #     await waiting_message.delete()
        
        summary_text = (
                # "Please check your information\n"
                f"👤 <b>Customer name:</b>\t{customer_name}\n"
                f"💳 <b>Account number:</b>\t{caNumber}\n"
                f"⚡ <b>Meter type:</b>\t{meter_type(mtype)}\n"
                f"🔋 <b>KWH:</b>\t{all_data.get("valueKWH")}\n"
                f"🕦 <b>Reading date:</b>\t{readingDate}\n\n"
                # f"Please read and be sure of the information before submiting. Once you hit send, you wont be able to edit anything."
            )

        #on the case of success
        if  result == 'success':
            try:
                logger.info(f"Meter reading submitted successfully for CA {caNumber}, tg_id {tg_id}", extra=await self.extra(state, LogCategory.API_SUCCESS))
                keyboard = [[KeyboardButton(text = "Exit")]]
                markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
                await call.message.answer("✅Your Meter reading data is sent successfully",reply_markup=markup)
                await self.log_activity(call,state,activity_type=ActivityType.SuccessfulMeterReadingSubmission ,
                                        smrdate = smrdate,kwh_input=kwh_input,taskbookid = taskBookId)
 
            except Exception as e:
                logger.error(f"Exception at submit success logging for CA {caNumber}: {e}", extra=await self.extra(state, LogCategory.CODE_CRASH))
                await self.log_activity(call,state,activity_type=ActivityType.ERROR, metadata={"error at trying to log":str(e)})
                await call.message.answer("⚠️ Sorry Something went wrong while trying to update your status\n please try again later")
        elif result == 'AlreadyUploadedToSap':
            logger.info(f"Meter reading already uploaded to SAP for CA {caNumber}, tg_id {tg_id}", extra=await self.extra(state, LogCategory.GENERAL))
            keyboard = [[KeyboardButton(text = "Exit")]]
            markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
            await call.message.answer(f"✅ Your meter reading data is already uploaded to SAP.\n\n{summary_text}",reply_markup=markup)
            await self.log_activity(call,state,activity_type=ActivityType.AlreadyUploadedToSap)
            
        elif result == 'error':
            logger.error(f"Meter reading send returned error for CA {caNumber}, tg_id {tg_id}", extra=await self.extra(state, LogCategory.API_FAIL))
            await call.answer("Sorry... conenction took too long. please try again later.")
            await self.redirect.toMainMenu(call,state)
        else:
            logger.warning(f"Meter reading send returned unexpected result for CA {caNumber}: {result}, tg_id {tg_id}", extra=await self.extra(state, LogCategory.API_FAIL))
            await state.set_state(MeterReadForm.finish)
            keyboard = [[KeyboardButton(text = "Exit")]]
            markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
            await call.message.answer(f"⚠️ {result}",reply_markup=markup)
            
 


