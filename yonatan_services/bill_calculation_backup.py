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
from datetime import datetime,timedelta,date
from django.db import transaction
from utils.redirect import Redirect
from zoneinfo import ZoneInfo
# from ethiopian_date import EthiopianDateConverter as EDC
from ethiopian_date_converter.ethiopian_date_convertor import to_ethiopian, EthDate, to_gregorian, get_et_month_name, get_day_no_ethiopian,get_day_of_week_name_et
import uuid
from pathlib import Path
import json

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
            text_match =FromGen.get_callData( call.data.casefold()) in  [i.casefold() for i in self.text]
            if not text_match:
                return False

        current_state = await state.get_state()
        return current_state in self.allowed_states

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

class BillCalcForm(StatesGroup):
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
        return self.service_name.casefold().strip() + "$" + btn_group.casefold().strip() + ">" + callback.casefold().strip()
    
    
    
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
            
            all_Data = await state.get_data()
            last_interaction_time = all_Data.get("last_interaction_time")
            await state.clear()
            await state.update_data(last_interaction_time = last_interaction_time)
            await state.set_state(BillCalcForm.catagory)
            await self.get_catagory(call,state)
        
        @self.router.callback_query(MultiTextStateFilter(allowed_states=[BillCalcForm.catagory]))
        async def _(call:CallbackQuery,state:FSMContext):
            await call.answer()
            catagory = FromGen.get_callData(call.data)
            await state.update_data(catagory = catagory)
            await state.set_state(BillCalcForm.caNumber)
            await self.get_ca_number(call,state)
        
        @self.router.message(MultiTextStateFilter(allowed_states=[BillCalcForm.caNumber]))
        async def _(message:CallbackQuery,state:FSMContext):
            if await self.verify.ca_bp_number(message,buttons=["Exit"],allow_multiCANumber=False):
                caNumber = message.text
                await state.update_data(caNumber = caNumber)
                keyboard = [[KeyboardButton(text = "Exit")]]
                markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
                
                response = await self.get_meter_type(message,state,ca = caNumber)
                print("The response:\t",response)
                all_data = await state.get_data()
                valueKWH = all_data.get('valueKWH')
                readTime = all_data.get('readTime')
                taskBookId = await state.get_value("taskBookId")
                customerName = all_data.get('customerName',"")
                smrDate = datetime.strptime(all_data.get('smrDate'),"%Y-%m-%d").date() if all_data.get('smrDate') else None
                smrDate_end = datetime.strptime(all_data.get('smrDate_end'),"%Y-%m-%d").date() if all_data.get('smrDate_end') else None
                
                if response == "invalid contractAccountNo":
                    # await message.answer(f"❗️Invalid Contract Account Number. Please enter a valid Contract Account Number(CA-Number)")
                    await message.answer(f"❗️Invalid Contract Account Number")
                    await self.get_ca_number(message,state)
                    
                elif response == 'error':
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
                elif response in ["NoMeterReadingForCurrentMonth","meterReadingExists"]:
                    print("am in nometer reading")
                    await state.set_state(BillCalcForm.kwh)
                    await self.kwh_get(message,state)
                # elif response == "meterReadingExists":
                #     await state.set_state(BillCalcForm.calculate)
                #     await self.bill_calculation(message,state)
                else:
                    print(f"{response}")
                    await message.answer(f"⚠️ We couldn't retrieve your energy meter data. Please try again later.")
                    await self.log_activity(call,state,activity_type=ActivityType.MeterTypeNotFound,metadata={"error":"response from the get_meter_type response isn't caught in =>  @self.router.message(MultiTextStateFilter(allowed_states=[BillCalcForm.caNumber]))"})
                    await self.get_ca_number(call,message)
            
        @self.router.callback_query(MultiTextStateFilter(allowed_states=[BillCalcForm.caNumber]))
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
                valueKWH = all_data.get('valueKWH')
                readTime = all_data.get('readTime')
                taskBookId = await state.get_value("taskBookId")
                customerName = all_data.get('customerName',"")
                smrDate_end = all_data.get('smrDate_end')
                    

                if response == "invalid contractAccountNo":
                    await message.answer(f"❗️Invalid Contract Account Number. Please enter a valid Contract Account Number(CA-Number)")
                    await self.get_ca_number(message,state)
                    return
                    
                elif response == 'error':
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
                    
                elif response in ["NoMeterReadingForCurrentMonth","meterReadingExists"]:
                    print("am in nometer reading")
                    await state.set_state(BillCalcForm.kwh)
                    await self.kwh_get(message,state)
                
                
                # elif response == "meterReadingExists":
                #     await state.set_state(BillCalcForm.calculate)
                #     await self.bill_calculation(call,state)
                
                
                else:
                    print(f"{response}")
                    await message.answer(f"⚠️ We couldn't retrieve your energy meter data. Please try again later.")
                    await self.log_activity(call,state,activity_type=ActivityType.MeterTypeNotFound,metadata={"error":"response from the get_meter_type isn't caught in =>  @self.router.callback_query(MultiTextStateFilter(allowed_states=[BillCalcForm.caNumber]) "})
                    await self.get_ca_number(call,message)

        @self.router.message(MultiTextStateFilter(allowed_states=[BillCalcForm.kwh]))   
        async def _(message:Message,state:FSMContext):
            print("recieved kwh message")
            now = datetime.now().date()
            all_data = await state.get_data()
            meter_type = all_data.get("meterType")
            valueKWH = all_data.get("valueKWH")
            lastTimeKWH = all_data.get("lastTimeKWH")
            readTime = all_data.get("readTime")
            lastTimeDate = all_data.get("lastTimeDate")
            
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
            if (not isfloat(kwh_input)) :  #if it is negative
                await message.answer("❗️Make sure to enter only digits. please try again ")
                await self.kwh_get(message,state)
                return
            elif ( float(kwh_input) <  0):
                await message.answer("❗️Make sure to enter only digits. please try again ")
                await self.kwh_get(message,state)
                return
                
            
            kwh_input = int(float(kwh_input))
            print(kwh_input)
            # ! Ths was added later to allow a person to re-submit his reading if he made a mistake and the previous reading was already submitted for the current month. This is done by updating the lastTimeKWH and valueKWH in the state so that the new reading can be compared with the previous reading.
            if readTime:
                lastTimeKWH = valueKWH
                valueKWH =  kwh_input
                lastTimeDate = readTime
                readTime = now
                              
            #check validity, then allow a person to resend and  update the middleware before it is sent to SAP so that he can re-correct his mistake.
        
            
            if (kwh_input is not None) and (isfloat(kwh_input)):
                # if message.text < lastTimeKWH:
                lastTimeKWH = lastTimeKWH if lastTimeKWH else 0
                if float(kwh_input) < float(lastTimeKWH):
                    
                    text = f'''❗️The meter reading you submitted <b>👉 {float(kwh_input)} KWH</b> is <b>less than</b> the previous reading <b>➡️ {lastTimeKWH} KWH</b> .\n\nPlease ensure you enter a <b>valid reading</b>. If your meter has <b>reversed</b> or if you believe this is an error, kindly visit the <b>Customer Service Center</b> for further assistance.
                    '''
                    await self.log_activity(message,state,activity_type=ActivityType.SmallerThanPreviousReading)
                    await message.answer(text = text,reply_markup=markup)
                    await self.kwh_get(message,state)
                    return
                await state.update_data(kwh = str(kwh_input))
                print("meter_type\t",meter_type)
                print("meter_type :\t",meter_type)
                if meter_type == '0':
                    print("meter_type\t",meter_type)
                    await state.set_state(BillCalcForm.calculate)
                    await state.update_data(valueKWH = str(kwh_input))
                    await state.update_data(lastTimeDate = lastTimeDate )
                    await state.update_data(readTime = str(now))
                    
                    await self.bill_calculation(message,state)
        
            else:
                await message.answer("❗️Make sure to enter only digits. please try again ")
                await self.kwh_get(message,state)
                return
        
        
    async def log_activity(self,update,state:FSMContext, activity_type: str, metadata :dict = None):
        tg_id = update.from_user.id
        ca_number = await state.get_value("caNumber")
        try:
            # await sync_to_async(BotActivityLog.objects.create)(
            await BotActivityLog.objects.acreate(
                session_id = str(uuid.uuid4()),
                tg_id=str(tg_id),
                username = str(update.from_user.username),
                ca_number=ca_number,
                activity_type=activity_type,
                metadata=metadata or {}
            )
        except Exception as e:
            print(f"Logging failed: {e}")
    
    async def get_catagory(self,update,state:FSMContext):
        message = update if isinstance(update,Message) else update.message
        catagories = ["Domestic","Commercial"]
        
        inline_Keyboards = [[InlineKeyboardButton(text = i, callback_data=self.gen(callback=i) )] for i in catagories]
        inline_markup = InlineKeyboardMarkup(inline_keyboard=inline_Keyboards)
        await message.answer("Chootse your meter catagory",reply_markup=inline_markup)

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

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    url=f"{meter_type_URL}",
                    json = json_data,
                    headers= headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:

                    text= await response.text() # in this case, it ddin't return json format but just plain/text format
                    result = json.loads(text)
                    print("result MeterType after aiohttp:\t",result)
                    if response.status == 200:
                        # if waiting_message:
                        #     await waiting_message.delete()
                        if result.get("message"):
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
                print(f"Error at getting meter type: \n{e}")
                await self.log_activity(update,state,activity_type=ActivityType.MeterTypeNotFound,metadata={"error":str(e)})
                return "error"
            
    async def kwh_get(self,update,state:FSMContext):
        print("in bill_calc kwh")
        customerName = await state.get_value("customerName")
        caNumber = await state.get_value('caNumber')
        message = update if isinstance(update,Message) else update.message
        
        readTime = await state.get_value('readTime')
        if readTime:
            previous_reading = await state.get_value('valueKWH')
            previous_reading_date = await state.get_value('readTime')
            markup = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Exit")]],one_time_keyboard=True,resize_keyboard=True)
            await message.answer(f"<b>👤 {customerName}</b>({caNumber})\n<b>🕐 Previous reading date:</b>  {previous_reading_date}\n<b>🔋 Previous KWH reading:</b>  {previous_reading}\n\nEnter your <b>KWH</b> reading. Please only write the digits ",reply_markup=markup)
            return
            
            
        
        
        previous_reading = await state.get_value('lastTimeKWH')
        previous_reading_date = await state.get_value('lastTimeDate')
        markup = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Exit")]],one_time_keyboard=True,resize_keyboard=True)
        await message.answer(f"<b>👤 {customerName}</b>({caNumber})\n<b>🕐 Previous reading date:</b>  {previous_reading_date}\n<b>🔋 Previous KWH reading:</b>  {previous_reading}\n\nEnter your <b>KWH</b> reading. Please only write the digits ",reply_markup=markup)
    
    
    async def get_ETdate_Quartile(self, gregorian_date):
        """Returns Ethiopian quarter in 'YYYY-Q' format with CORRECT inclusive boundaries"""
        et_date = to_ethiopian( date(gregorian_date.year, gregorian_date.month, gregorian_date.day))
        et_year = et_date.year
        et_month = et_date.month
        
        if 2 <= et_month <=4:
            return f"{et_year}-2"
        elif 5 <= et_month <= 7:
            return f"{et_year}-3"
        elif 8 <= et_month <= 10:
            return f"{et_year}-4"
        else:  # Months 11, 12, 13 (Pagume)
            return f"{et_year}-1"

 
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
                await message.answer("❌ Missing last reading date. Cannot calculate bill.")
                await self.redirect.toMainMenu(update, state)
                return
            lastReadingDate = datetime.strptime(lastReadingDate_str.strip(), "%Y-%m-%d").date()
            
            lastTimeKWH_str = all_data.get('lastTimeKWH', "0")
            lastTimeKWH = 0.0 if lastTimeKWH_str in [None, "", " "] else float(lastTimeKWH_str)
            
            if current_kwh < lastTimeKWH:
                await message.answer(f"⚠️ Current reading ({current_kwh:,.2f} KWH) is less than previous reading ({lastTimeKWH:,.2f} KWH).")
                await self.redirect.toMainMenu(update, state)
                return
            
            # =============== CORE CALCULATIONS ===============
            total_consumption = current_kwh - lastTimeKWH
            reading_interval = (readDate - lastReadingDate).days
            
            if reading_interval <= 0:
                await message.answer("❌ Invalid billing period (non-positive days).")
                await self.redirect.toMainMenu(update, state)
                return
            
            Qprevious = await self.get_ETdate_Quartile(lastReadingDate)
            Qcurrent = await self.get_ETdate_Quartile(readDate)
            is_same_quarter = (Qprevious == Qcurrent)
            is_standard_period = (26 <= reading_interval <= 34)
            
            # =============== NON-ADJACENT QUARTERS CHECK ===============
            prev_year, prev_q = map(int, Qprevious.split('-'))
            curr_year, curr_q = map(int, Qcurrent.split('-'))
            prev_index = prev_year * 4 + prev_q
            curr_index = curr_year * 4 + curr_q
            
            if curr_index - prev_index > 1:
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
            
            # =============== SAME QUARTER HANDLING (UNCHANGED) ===============
            if is_same_quarter:
                quarter_label = Qcurrent
                bill_explanation += f"✅ <b>Same Quarter Billing</b> ({quarter_label})\n"
                
                if is_standard_period:
                    normalized_consumption = total_consumption
                    bill_explanation += "   → Standard period (26-34 days). Using actual consumption for tariff calculation.\n\n"
                else:
                    normalized_consumption = (total_consumption / reading_interval) * 30
                    bill_explanation += (
                        f"   → Non-standard period ({reading_interval} days). Normalizing to 30-day equivalent:\n"
                        f"   → ({total_consumption:,.2f} ÷ {reading_interval}) × 30 = {normalized_consumption:,.2f} KWH\n\n"
                    )
                
                tariff = await self.get_tarrif(catagory=category, consumption=normalized_consumption, date=readDate)
                service_charge_full = await self.get_service_charge(catagory=category, consumption=total_consumption, date=readDate)
                energy_charge = total_consumption * tariff
                
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
            
            # =============== CROSS-QUARTER HANDLING (CRITICAL FIX PER YOUR SPEC) ===============
            else:
                bill_explanation += f"⚠️ <b>Cross-Quarter Billing</b>\n"
                bill_explanation += f"   → Previous: Quarter {Qprevious.split('-')[1]} | Current: Quarter {Qcurrent.split('-')[1]}\n"
                
                # Calculate quarter boundary
                curr_q_num = int(Qcurrent.split('-')[1])
                et_start_month = {1: 11, 2: 2, 3: 5, 4: 8}[curr_q_num]  # EEU fiscal year mapping
                et_start_year = int(Qcurrent.split('-')[0])
                
                try:
                    greg_start = to_gregorian(EthDate(1, et_start_month,et_start_year)).date()
                    quarter_start_greg = greg_start
                except Exception as e:
                    await message.answer("❌ Error calculating quarter boundary. Contact support.")
                    print(f"Quarter boundary error: {e}")
                    await self.redirect.toMainMenu(update, state)
                    return
                
                days_in_prev_q = (quarter_start_greg - lastReadingDate).days -1
                days_in_curr_q = (readDate - quarter_start_greg).days + 1
                
                if days_in_prev_q <= 0 or days_in_curr_q <= 0 or (days_in_prev_q + days_in_curr_q) != reading_interval:
                    await message.answer(
                        "⚠️ Complex billing period detected. "
                        "Automatic calculation isn't possible due to date alignment issues.\n\n"
                    )
                    await self.redirect.toMainMenu(update, state)
                    return
                
                bill_explanation += (
                    f"   → Days in Quarter {Qprevious.split('-')[1]}: {days_in_prev_q} days "
                    f"({lastReadingDate.strftime('%d/%m/%Y')} → {quarter_start_greg.strftime('%d/%m/%Y')})\n"
                    f"   → Days in Quarter {Qcurrent.split('-')[1]}: {days_in_curr_q} days "
                    f"({(quarter_start_greg + timedelta(days=1)).strftime('%d/%m/%Y')} → {readDate.strftime('%d/%m/%Y')})\n"
                )
                
                # Calculate actual consumption per segment for service charge tier
                cons_prev_q = (total_consumption * days_in_prev_q) / reading_interval
                cons_curr_q = (total_consumption * days_in_curr_q) / reading_interval
                
                if is_standard_period:
                    # ===== STANDARD CROSS-QUARTER (26-34 days) =====
                    bill_explanation += (
                        f"   → Standard period ({reading_interval} days). "
                        f"Using TOTAL consumption ({total_consumption:,.2f} KWH) to determine tariff blocks for BOTH quarters.\n\n"
                    )
                    
                    # Get tariffs using TOTAL consumption for BOTH quarters
                    tariff_prev = await self.get_tarrif(catagory=category, consumption=total_consumption, date=lastReadingDate)
                    tariff_curr = await self.get_tarrif(catagory=category, consumption=total_consumption, date=readDate)
                    
                    # ENERGY CHARGE FORMULA (PER YOUR SPEC - WITH CONSTANT 30):
                    # Energy = [(Total Consumption × Tariff) ÷ 30] × Segment Days
                    energy_prev = (total_consumption * tariff_prev * days_in_prev_q) / 30
                    energy_curr = (total_consumption * tariff_curr * days_in_curr_q) / 30
                    
                    # SERVICE CHARGE FORMULA (PER YOUR SPEC - WITH CONSTANT 30):
                    # Service = (Full Service Charge ÷ 30) × Segment Days
                    sc_prev_full = await self.get_service_charge(catagory=category, consumption=cons_prev_q, date=lastReadingDate)
                    sc_curr_full = await self.get_service_charge(catagory=category, consumption=cons_curr_q, date=readDate)
                    sc_prev = (sc_prev_full * days_in_prev_q) / 30
                    sc_curr = (sc_curr_full * days_in_curr_q) / 30
                    
                    energy_charge = energy_prev + energy_curr
                    service_charge_amount = sc_prev + sc_curr
                    
                    calculation_notes.append(
                        f"💡 <b>Quarter {Qprevious.split('-')[1]} Segment (Energy)</b>\n"
                        f"   [({total_consumption:,.2f} KWH × {tariff_prev:,.4f} Br/KWH) ÷ 30] × {days_in_prev_q} days\n"
                        f"   = <b>{energy_prev:,.2f} Br</b>"
                    )
                    calculation_notes.append(
                        f"💡 <b>Quarter {Qcurrent.split('-')[1]} Segment (Energy)</b>\n"
                        f"   [({total_consumption:,.2f} KWH × {tariff_curr:,.4f} Br/KWH) ÷ 30] × {days_in_curr_q} days\n"
                        f"   = <b>{energy_curr:,.2f} Br</b>"
                    )
                    calculation_notes.append(
                        f"💡 <b>Quarter {Qprevious.split('-')[1]} Segment (Service)</b>\n"
                        f"   Actual consumption: {cons_prev_q:,.2f} KWH\n"
                        f"   [({sc_prev_full:,.2f} Br ÷ 30) × {days_in_prev_q} days] = <b>{sc_prev:,.2f} Br</b>"
                    )
                    calculation_notes.append(
                        f"💡 <b>Quarter {Qcurrent.split('-')[1]} Segment (Service)</b>\n"
                        f"   Actual consumption: {cons_curr_q:,.2f} KWH\n"
                        f"   [({sc_curr_full:,.2f} Br ÷ 30) × {days_in_curr_q} days] = <b>{sc_curr:,.2f} Br</b>"
                    )
                
                else:
                    # ===== NON-STANDARD CROSS-QUARTER (OUTSIDE 26-34 days) =====
                    normalized_total = (total_consumption / reading_interval) * 30
                    bill_explanation += (
                        f"   → Non-standard period ({reading_interval} days). "
                        f"Normalizing TOTAL consumption to 30-day equivalent for tariff lookup in BOTH quarters.\n"
                        f"   → Normalized total: ({total_consumption:,.2f} ÷ {reading_interval}) × 30 = <b>{normalized_total:,.2f} KWH</b>\n\n"
                    )
                    
                    # Get tariffs using NORMALIZED TOTAL consumption for BOTH quarters
                    tariff_prev = await self.get_tarrif(catagory=category, consumption=normalized_total, date=lastReadingDate)
                    tariff_curr = await self.get_tarrif(catagory=category, consumption=normalized_total, date=readDate)
                    
                    # ENERGY CHARGE FORMULA (PER YOUR SPEC - WITH CONSTANT 30):
                    # Energy = [(Normalized Total × Tariff) ÷ 30] × Segment Days
                    energy_prev = (normalized_total * tariff_prev * days_in_prev_q) / 30
                    energy_curr = (normalized_total * tariff_curr * days_in_curr_q) / 30
                    
                    # SERVICE CHARGE FORMULA (UNCHANGED - WITH CONSTANT 30):
                    sc_prev_full = await self.get_service_charge(catagory=category, consumption=cons_prev_q, date=lastReadingDate)
                    sc_curr_full = await self.get_service_charge(catagory=category, consumption=cons_curr_q, date=readDate)
                    sc_prev = (sc_prev_full * days_in_prev_q) / 30
                    sc_curr = (sc_curr_full * days_in_curr_q) / 30
                    
                    energy_charge = energy_prev + energy_curr
                    service_charge_amount = sc_prev + sc_curr
                    
                    calculation_notes.append(
                        f"💡 <b>Quarter {Qprevious.split('-')[1]} Segment (Energy)</b>\n"
                        f"   Normalized total: {normalized_total:,.2f} KWH\n"
                        f"   [({normalized_total:,.2f} KWH × {tariff_prev:,.4f} Br/KWH) ÷ 30] × {days_in_prev_q} days\n"
                        f"   = <b>{energy_prev:,.2f} Br</b>"
                    )
                    calculation_notes.append(
                        f"💡 <b>Quarter {Qcurrent.split('-')[1]} Segment (Energy)</b>\n"
                        f"   Normalized total: {normalized_total:,.2f} KWH\n"
                        f"   [({normalized_total:,.2f} KWH × {tariff_curr:,.4f} Br/KWH) ÷ 30] × {days_in_curr_q} days\n"
                        f"   = <b>{energy_curr:,.2f} Br</b>"
                    )
                    calculation_notes.append(
                        f"💡 <b>Quarter {Qprevious.split('-')[1]} Segment (Service)</b>\n"
                        f"   Actual consumption: {cons_prev_q:,.2f} KWH\n"
                        f"   [({sc_prev_full:,.2f} Br ÷ 30) × {days_in_prev_q} days] = <b>{sc_prev:,.2f} Br</b>"
                    )
                    calculation_notes.append(
                        f"💡 <b>Quarter {Qcurrent.split('-')[1]} Segment (Service)</b>\n"
                        f"   Actual consumption: {cons_curr_q:,.2f} KWH\n"
                        f"   [({sc_curr_full:,.2f} Br ÷ 30) × {days_in_curr_q} days] = <b>{sc_curr:,.2f} Br</b>"
                    )
            
            # =============== FEES CALCULATION (WITH EXPLICIT FORMULAS) ===============
            regulatory_fee = (energy_charge + service_charge_amount) * 0.005
            vat = (energy_charge + service_charge_amount) * 0.15 if total_consumption > 200 else 0.0
            tv_levy = 10.0 if (is_standard_period and total_consumption > 50) else ((10.0 / 30) * reading_interval if total_consumption > 50 else 0.0)
            total_bill = energy_charge + service_charge_amount + regulatory_fee + vat + tv_levy
            
            # =============== BUILD FINAL EXPLANATION ===============
            bill_explanation += "\n".join(calculation_notes) + "\n\n"
            
            # Regulatory Fee with formula description
            bill_explanation += (
                f"💡 <b>Regulatory Fee (0.5%)</b>\n"
                f"   Formula: 0.5% × (Energy Charge + Service Charge)\n"
                f"   0.5% × ({energy_charge:,.2f} + {service_charge_amount:,.2f}) = <b>{regulatory_fee:,.2f} Br</b>\n\n"
            )
            
            # VAT with formula description
            bill_explanation += f"💡 <b>VAT (15%)</b>\n"
            if total_consumption > 200:
                bill_explanation += (
                    f"   Formula: 15% × (Energy Charge + Service Charge)\n"
                    f"   Applied (consumption > 200 KWH)\n"
                    f"   15% × ({energy_charge:,.2f} + {service_charge_amount:,.2f}) = <b>{vat:,.2f} Br</b>\n\n"
                )
            else:
                bill_explanation += "   ❌ Not applied (consumption ≤ 200 KWH)\n\n"
            
            # TV Levy with formula description
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
            
            # Final Summary
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
            
            # Contextual footer
            period_type = "Standard period (26–34 days)" if is_standard_period else f"Non-standard period ({reading_interval} days)"
            quarter_note = (
                "Same-quarter pricing" if is_same_quarter 
                else "Cross-quarter proration: Energy charge uses [ (Consumption × Tariff) ÷ 30 ] × Segment Days for BOTH quarters"
            )
            bill_explanation += (
                f"ℹ️ <b>Calculation Notes</b>\n"
                f"• {period_type}\n"
                f"• {quarter_note}\n" 
                # f"• Service charges will be the actual tarrif it is stanard billing days(i.e 26-34 days) otherwise use  [ (Full Charge ÷ 30) × Segment Days ]\n"
                # f"• The same applies for fees calculated on TOTAL consumption ({total_consumption:,.2f} KWH)\n"
                # f"• Constant divisor '30' represents standard billing cycle days\n"
                f"• Ethiopian calendar quarters used per EEU billing rules"
            )
            
            # =============== SEND RESULT ===============
            keyboard = [[KeyboardButton(text="Exit")]]
            markup = ReplyKeyboardMarkup(keyboard=keyboard, one_time_keyboard=True, resize_keyboard=True)
            await message.answer(bill_explanation, parse_mode="HTML", reply_markup=markup)
            
        except Exception as e:
            await message.answer("⚠️ Bill calculation failed. Please contact support with your CA number.")
            print(f"Bill calculation error: {e}")
            import traceback
            traceback.print_exc()
            await self.redirect.toMainMenu(update, state)
        
        
        