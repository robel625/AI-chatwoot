from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup,ReplyKeyboardMarkup,ReplyKeyboardRemove,KeyboardButton
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
from main_handler import MainHandler

#________________________________________working_with_path____________________________________________
# making sure we are on the right path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '../')) #../..
# Add the project directory to the Python path
sys.path.append(project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "eeuBotProject.settings")
django.setup()
#________________________________________/path_______________________________________________________

from eeuBotApp.models import UserInfo, UnregisteredUser

class FromGen:
    """This class is used to get the service name and button group from the call.data"""
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

class MultiTextStateFilter(BaseFilter):
    """allowed_states:List , text: List =[](not case sensitive... will be .casefold() in the filter)"""
    def __init__(self,allowed_states:list,text:list = []) -> bool:
        self.allowed_states = allowed_states
        self.text =text
    async def __call__(self,update,state):
        if self.text == ():
            pass
        elif isinstance(update,types.Message):
            message = update
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

class Continue_case(BaseFilter):
   async def __call__(self,message,state):
      text_match = (getattr(message,'text',None) is not None) and ( (getattr(message,'text','').casefold() == "continue"))
      if not text_match:
         return False
      return "RegForm" in await state.get_state()


class RegForm(StatesGroup):
  """Form state group"""
  name = State()
  phone = State()
  email = State()
  address = State()
  caNumber = State()
  bpNumber = State()
  summary = State()
  finish =  State()
  editMode = State()



#_________________________________________Registering ____________________________________________________
#_________________________________________________________________________________________________________

class Register:
  service_name = 'Regist01'
  def __init__(self,bot):
    self.router = Router()
    self.bot = bot
    self.service_name = Register.service_name
    self.verify = Verify()
    self.setupt_handlers()
    self.mainhandler = MainHandler()


  def setupt_handlers(self):

    @self.router.message(Continue_case())
    async def _(message,state):
        print(Continue_case())
        print("forwarding to status mapper")
        return await self.status_mapper(message,state)

    #starting registeration
    @self.router.callback_query(lambda call: call.data == "mainhandler$btn>register" )
    async def pilot(call,state):
      tgID = str(call.from_user.id) # user's telegram id
      queryset = await sync_to_async(UserInfo.objects.filter)(tgID = tgID)
      is_registered = await sync_to_async(queryset.exists)()
      if is_registered:
       await call.message.answer("You are already registered") # You are already registered
       return await self.mainhandler.list_services(call)
      else:
        await state.set_state(RegForm.name)
        await self.name_handler(call)

    @self.router.message(F(content_type ='text') and StateFilter( RegForm.name))
    async def _(message,state):
      print("in RegForm.name filter handler")
      if await self.verify.name(message,buttons=["Exit"],inline_buttons=[self.gen(callback="Skip")]):
      # if await self.process_name(message):
        await state.update_data(name = message.text.casefold())
        await state.set_state(RegForm.phone)
        await self.phone_handler(message)

    # @self.router.message(lambda message:message.text =="success", StateFilter(RegForm.phone) )
    @self.router.message(F(content_type ='text') and StateFilter(RegForm.phone))
    async def _(message,state):
      # if await self.process_phone_number(message):
      if await self.verify.phone_number(message,buttons=["Exit"]):
        await state.update_data(phone = "+251" + message.text[-9:])
        await state.set_state(RegForm.email)
        await self.email_handler(message)

    @self.router.message(F(content_type ='text') and StateFilter( RegForm.email ))
    async def _(message,state):
      if await self.verify.email(message,buttons=["Exit"],inline_buttons=[self.gen(callback= "Skip")]):
        await state.update_data(email = message.text.casefold())
        await state.set_state(RegForm.address)
        await self.address_handler(message)

    @self.router.message(F(content_type ='text') and StateFilter( RegForm.address) )
    async def _(message,state):
      if await self.verify.address(message,buttons=["Exit"],inline_buttons=[self.gen(callback="Skip")]):
        await state.update_data(address = message.text)
        await state.set_state(RegForm.caNumber)
        await self.caNumber_handler(message)

    @self.router.message(F(content_type ='text') and StateFilter(RegForm.caNumber ))
    async def _(message,state):
      # if await self.process_ca_bp_number(message):
      if await self.verify.ca_bp_number(message,buttons=["Exit"],inline_buttons=[self.gen(callback="Skip")]):
        await state.update_data(caNumber = message.text)
        await state.set_state(RegForm.summary)
        await self.summary_handler (message,state)

    #*this is for the "skip" button in the inline keyboard
    @self.router.callback_query( MultiTextStateFilter(allowed_states=[RegForm.name,RegForm.email,RegForm.address,RegForm.caNumber],text =[self.gen("skip")]))
    async def _(call,state):
      await call.answer()
      current_state = await state.get_state()
      if current_state == RegForm.name:
        print("in name")
        await state.update_data(name = "")
        await state.set_state(RegForm.phone)
        await self.phone_handler(call)
      elif current_state == RegForm.phone:
        await state.update_data(phone = "")
        await state.set_state(RegForm.email)
        await self.email_handler(call)
      elif current_state == RegForm.email:
        await state.update_data(email = "")
        await state.set_state(RegForm.address)
        await self.address_handler(call)
      elif current_state == RegForm.address:
        await state.update_data(address = "")
        await state.set_state(RegForm.caNumber)
        await self.caNumber_handler(call)
      elif current_state == RegForm.caNumber:
        await state.update_data(caNumber = "")
        await state.set_state(RegForm.summary)
        await self.summary_handler(call,state)

    @self.router.callback_query(MultiTextStateFilter(allowed_states=[RegForm.summary,RegForm.editMode],text =[self.gen("cancel edit")] ))
    async def _(call:types.CallbackQuery,state):
      await call.answer()
      await state.update_data(editing = None)
      await self.summary_handler (call,state)


    @self.router.callback_query(lambda call: call.data ==self.gen('send') and StateFilter(RegForm.summary))
    async def _(call, state):
        await call.answer()
        await state.update_data(tgID = str(call.from_user.id))
        all_data = await state.get_data()
        all_data['tgID'] = str(call.from_user.id)
        keys_to_send = ['tgID','name','phone','email','address','caNumber']
        data = {i:all_data[i] for i in keys_to_send if i in all_data}
        print("data before deletion:\t",data)
        keys_with_skip = []
        for key,value in data.items():
            if value.lower() == 'skip':
                keys_with_skip.append(key)
        for key in keys_with_skip:
            data[key] = None
        #add the username
        data['username'] = call.from_user.username
        user_creation = sync_to_async(UserInfo.objects.create)
        try:
            user = await user_creation(**data)
            print("creating status:\t",user)

            # Delete the UnregisteredUser record if it exists
            unregistered_user = await sync_to_async(UnregisteredUser.objects.filter)(tgID=data['tgID'])
            if await sync_to_async(unregistered_user.exists)():
                await sync_to_async(unregistered_user.delete)()

            await call.message.answer("🎆")
            await call.message.answer("Congratulations! You are now registered on our database")
            mainhandler = MainHandler()
            await mainhandler.list_services(call)
            await state.set_state(RegForm.finish)
        except IntegrityError:
            await call.message.answer(" You are already registered")
            await call.message.answer("please /start the bot and try again")
        except Exception as e:
            print(f"Error {e}")
            await call.message.answer(f"Sorry, something went wrong, please /start the bot and try again")
            await state.clear()
        print("final Data:\t",data)


    #generate inline butttons of all things to edit
    @self.router.callback_query(MultiTextStateFilter(allowed_states=[RegForm.summary,RegForm.editMode], text=[self.gen("edit"),self.gen("leave empty")]))
    async def _(call,state):
      print("in edit)")
      await call.answer()
      if FromGen.get_callData(call.data).casefold().strip() == "leave empty":
        data = await state.get_data()
        to_edit = FromGen.get_callData(data.get('editing')).casefold().strip()
        if to_edit == "phone":
          await call.message.answer("You can't leave the phone number field empty")
          await state.update_data(editing = None)
          return await self.summary_handler(call,state)
        await state.update_data({to_edit : ''})
        await state.update_data(editing = None)
        await call.message.answer(f"✅ You have left <b>{to_edit.capitalize()}</b> field empty",parse_mode='HTML')
        await state.set_state(RegForm.editMode)
        return await self.summary_handler(call,state)
      await state.set_state(RegForm.editMode)
      await self.edit_handler(call)

    #clarify what he is editing
    @self.router.callback_query(MultiTextStateFilter(allowed_states=[RegForm.editMode],text=[self.gen("Name"),self.gen("Phone"),self.gen("Email"),self.gen("Address"),self.gen("CA Number"),self.gen("BP Number")]) )
    async def _(call,state):
      await state.update_data(editing = call.data)
      await self.start_editing(call,state)

    @self.router.message(F(content_type='text') and StateFilter(RegForm.editMode))
    async def _(message,state):
      await self.updating_info(message,state)
      await self.summary_handler (message,state)





      # await call.message.answer("You are now in edit mode. To skip a field, reply with 'Skip'. To exit, reply with 'Exit'")


  def gen(self,callback:str,btn_group:str="btn")->str:
        """ for example gen("region","Addis Ababa")"""
        # This functon makes all call.data unique to it's respective service.
        """call_data = callback data(i.e call.data), and btn_group can be "region" or "csc" etc """
        return self.service_name.casefold().strip()+"$"+btn_group.casefold().strip()+">"+callback.casefold().strip()

  async def name_handler(self,call):
      print("in Name handler")
      replies =  ["Exit"]
      keyboard = [[KeyboardButton(text =i) for i in replies ]]
      markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
      inline_keyboard = [[InlineKeyboardButton(text = "Skip",callback_data= self.gen(callback='Skip'))]]
      inline_markup = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
      if isinstance(call,types.CallbackQuery):
        await call.answer()
        # await call.message.answer("✍️",reply_markup = markup)
        await call.message.answer(" Tell us your full name ", reply_markup = inline_markup)
      else:
        message = call
        # await message.answer("✍️",reply_markup = markup)
        await message.answer("Tell us your full name ✍️", reply_markup = markup )

# The next 3 methods are for handling phone number ( making sure they are valid phone numbers)
  async def phone_handler(self,update):
      text1 =  "Tell us you phone number."
      text2 = "Please enter your correct phone number as +2519xx xx xx xx, 09xx xx xx xx, +2517xx xx xx xx, 07xx xx xx xx xx. Make sure you right only in digits(numbers) "
      keyboard = [[KeyboardButton(text = "Exit")]]
      markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
      if isinstance(update,types.Message):
        message = update
        # await message.answer("📞")
        await message.answer(text1,reply_markup = ReplyKeyboardRemove())
        await message.answer(text2,reply_markup = markup)
      else:
        # await update.message.answer("📞")
        await update.message.answer(text1,reply_markup = ReplyKeyboardRemove())
        await update.message.answer(text2,reply_markup = markup)


  async def email_handler(self,update):
      replies = ["Exit"]
      keyboard = [[KeyboardButton(text =i) for i in replies ]]
      markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
      inline_keyboard = [[InlineKeyboardButton(text = "Skip",callback_data= self.gen(callback='Skip'))]]
      inline_markup = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
      if isinstance(update,types.Message):
        message = update
        # await message.answer("📧",reply_markup= markup)
        await message.answer("Tell us your email", reply_markup = inline_markup )
      else:
        # await update.message.answer("📧",reply_markup= markup)
        await update.message.answer("Tell us your email", reply_markup = inline_markup )

  async def address_handler(self,update):
      replies = ["Exit"]
      keyboard = [[KeyboardButton(text =i) for i in replies ]]
      markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
      inline_keyboard = [[InlineKeyboardButton(text = "Skip",callback_data= self.gen(callback='Skip'))]]
      inline_markup = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
      if isinstance(update,types.Message):
        message = update
        # await message.answer("🗺",reply_markup = markup )
        await message.answer("Tell us your Address ", reply_markup = inline_markup )
      else:
        # await update.message.answer("🗺",reply_markup = markup )
        await update.message.answer("Tell us your Address ", reply_markup = inline_markup )

# checking for CAnumber and BPnumber
  async def caNumber_handler(self,update):
      replies = ("Skip", "Exit")
      keyboard = [[KeyboardButton(text =i) for i in replies ]]
      markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
      inline_keyboard = [[InlineKeyboardButton(text = "Skip",callback_data= self.gen(callback='Skip'))]]
      inline_markup = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
      if isinstance(update,types.Message):
        message = update
        # await message.answer("📄",reply_markup = markup)
        await message.answer("Tell us your CA-Number(Contract Account Number).\n For multiple CA numbers, list them with a comma like this: 100000xxxxxxx,100000xxxxxxx.", reply_markup = inline_markup )
      else:
        # await update.message.answer("📄",reply_markup = markup)
        await update.message.answer("Tell us your CA-Number(Contract Account Number).\n For multiple CA numbers, list them with a comma like this: 100000xxxxxxx,100000xxxxxxx.", reply_markup = inline_markup )

  async def summary_handler(self, update, state):
      data = await state.get_data()
      print(data)
      keys_with_skip =[]
      for key,value in data.items():
        if value is None:
           continue
        if value.casefold() == 'skip':
          keys_with_skip.append(key)
      for key in keys_with_skip:
        data[key] = ''
      # Create a summary of the user's information
      summary_text = (
          "Here is the information you provided:\n"
          f"👤 Name: {data.get('name', 'Not provided')}\n"
          f"📞 Phone: {data.get('phone', 'Not provided')}\n"
          f"📧 Email: {data.get('email', 'Not provided')}\n"
          f"🏠 Address: {data.get('address', 'Not provided')}\n"
          f"📄 CA Number: {data.get('caNumber', 'Not provided')}\n"
          # f"🔢 BP Number: {data.get('bpNumber', 'Not provided')}\n"
        )

    #for replies
      keyboard = [[KeyboardButton(text = "Exit") ]]
      markup = ReplyKeyboardMarkup( keyboard=keyboard, one_time_keyboard=True,resize_keyboard=True )
      if isinstance(update,types.Message):
        message = update
        # await message.answer("📝")
        await message.answer(summary_text, reply_markup = markup)
      else:
        call = update
        # await call.message.answer("📝")
        await call.message.answer(summary_text, reply_markup = markup)

    # for inline keyboard
      btns = ["Send","Edit"]
      keyboard =[[InlineKeyboardButton(text =i, callback_data=self.gen(i.casefold().strip())) for i in btns]]
      markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
      if isinstance(update,types.Message):
        await message.answer("Choose action:", reply_markup=markup)
      else:
        await update.message.answer("Choose action:", reply_markup=markup)


  async def edit_handler(self,update):
    btns = ("Name", "Phone","Email","Address","CA Number","Cancel edit")
    icons = ("Edit  👤 ","Edit  📞","Edit  📧 ","Edit  🏠 ","Edit  📄 ","❌ ")

    inline_Keyboard = [[InlineKeyboardButton(text =f"{icon}{btn}", callback_data=self.gen(btn))] for icon,btn in zip(icons,btns)]
    inline_markup = InlineKeyboardMarkup(inline_keyboard=inline_Keyboard)
    if isinstance(update,types.CallbackQuery):
      await update.answer()
      # await update.message.answer("✏️")
      await update.message.answer("Choose field to edit:", reply_markup=inline_markup)
    else:
        await update.answer("Choose field to edit:", reply_markup=inline_markup)


  async def start_editing(self,call:types.CallbackQuery,state:FSMContext):
    """Generates Edit Buttons for editing"""
    all_data =  await state.get_data()
    editing = all_data.get('editing')
    data_to_edit = ["name","phone","email","address","ca number","bp number"]
    if FromGen.get_callData(call.data).casefold().strip() in data_to_edit:
        reply = ['Exit']
        keyboard = [[KeyboardButton(text =i) for i in reply]]
        markup = ReplyKeyboardMarkup(keyboard=keyboard, one_time_keyboard=True, resize_keyboard=True)

        inline_keyboard = ["Leave empty","Cancel edit"]
        inline_keyboard = [[InlineKeyboardButton(text = i,callback_data= self.gen(callback=i.casefold().strip())) for i in inline_keyboard] ]
        inline_markup = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
        await call.answer()

        if FromGen.get_callData(editing).casefold() == 'phone': #* since Leave empty is not needed for phone
          inline_keyboard = ["Cancel edit"]
          inline_keyboard = [[InlineKeyboardButton(text = i,callback_data= self.gen(callback=i.casefold().strip())) for i in inline_keyboard] ]
          inline_markup = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
          # await call.message.answer("✍️",reply_markup=markup)
          await call.message.answer(f"Please enter your new <b>{FromGen.get_callData(call.data).capitalize()}</b>:", reply_markup=inline_markup,parse_mode='HTML')
        else:
          # await call.message.answer("✍️",reply_markup=markup)
          await call.message.answer(f"Please enter your new <b>{FromGen.get_callData(call.data).capitalize()}</b>", reply_markup=inline_markup,parse_mode='HTML')



  async def updating_info(self,message:types.Message,state):
    all_data = await state.get_data()
    if not all_data.get('editing'): #* if the user is not editing anything
      return
    to_edit = FromGen.get_callData(all_data.get('editing')).casefold().strip()
    print("to_edit:\t",to_edit)
    if to_edit == 'Name'.casefold():
      #  if await self.process_name(message):
        if await self.verify.name(message):
          print("am in edit name")
          await state.update_data(name = message.text)
          await message.answer("✅ <b> Name</b> updated successfully",parse_mode='HTML')
          await state.update_data(editing =None)
          return True
        else:
          await message.answer(f"❌ Updating <b>{to_edit.capitalize()}</b> was not successful",parse_mode='HTML')
          await state.update_data(editing =None)
          return False
    elif to_edit == "Phone".casefold():
        if await self.verify.phone_number(message):
        # if await self.process_phone_number(message):
            await state.update_data(phone = "+251" + message.text[-9:])
            await message.answer("✅ <b>Phone</b> number updated successfully",parse_mode='HTML')
            await state.update_data(editing =None)
            return True
        else:
          await message.answer(f"❌ Updating <b>{to_edit.capitalize()}</b> was not successful",parse_mode='HTML')
          await state.update_data(editing =None)
          return False

    elif to_edit == "Email".casefold():
        if await self.verify.email(message):
          await state.update_data(email = message.text)
          await message.answer("✅ <b>Email </b>updated successfully",parse_mode='HTML')
          await state.update_data(editing =None)
          return True
        else:
          await message.answer(f"❌ Updating <b>{to_edit.capitalize()}</b> was not successful",parse_mode='HTML')
          await state.update_data(editing =None)
          return False

    elif to_edit == "Address".casefold():
        #here we are using "Process name" because the address field takes the same value.
        if await self.verify.address(message):
        # if await self.process_name(message):
          await state.update_data(address = message.text)
          await message.answer("✅ <b>Address</b>updated successfully",parse_mode='HTML')
          await state.update_data(editing =None)
        else:
          await message.answer(f"❌ Updating <b>{to_edit.capitalize()}</b> was not successful",parse_mode='HTML')
          await state.update_data(editing =None)
          return False


    elif to_edit == "CA Number".casefold():
       if await self.verify.ca_bp_number(message):
      #  if await self.process_ca_bp_number(message):
        await state.update_data(caNumber = message.text)
        await message.answer("✅ <b>CA Number</b> updated successfully",parse_mode='HTML')
        await state.update_data(editing =None)
        return True
       else:
          await message.answer(f"❌ Updating <b>{to_edit.capitalize()}</b> was not successful",parse_mode='HTML')
          await state.update_data(editing =None)
          return False
    else:
       return False


# we need this when we're asked if we wan't to restart or continue(eg. after replying "Exit" or "/start")
  async def status_mapper(self,update,state):
    #  all_data = await state.get_data()
    #  load = all_data.get('load')
     current_state = await state.get_state()

     mapper = {
        RegForm.name : partial(self.name_handler,update),
        RegForm.phone : partial(self.phone_handler,update),
        RegForm.email : partial(self.email_handler,update),
        RegForm.address : partial(self.address_handler,update),
        RegForm.caNumber : partial(self.caNumber_handler,update),
        # RegForm.bpNumber : partial(self.bpNumber_handler,update),
        RegForm.summary : partial(self.summary_handler,update,state),
        RegForm.editMode : partial(self.edit_handler,update),

     }

     if current_state in mapper:
        return await mapper[current_state]()









#Note remember how to pass multipple argumentts with partial() for thr summary



#  we need to take the user's phone by asking permission ? rather than letimn him fill it.
# we need to make /admin access for blocking from the telegram.
# django session
# make sure to add /myinfo in bot father( for echanging user's registarion info) /check
