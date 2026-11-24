import requests
from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup,ReplyKeyboardMarkup,ReplyKeyboardRemove,KeyboardButton
from dotenv import load_dotenv
from functools import partial
from aiogram import types
from aiogram.types import CallbackQuery,Message
from aiogram.fsm.state import State,StatesGroup
from aiogram.filters import  Command,StateFilter
from aiogram import F
from aiogram.filters import BaseFilter
from django.db import IntegrityError
from aiogram.fsm.context import FSMContext
from asgiref.sync import sync_to_async
from aiogram import Router
import os,sys,django
from django.db import transaction
from utils.verify import Verify
load_dotenv()
TOKEN = os.getenv('TOKEN')

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

class This_service(BaseFilter):
    """Filters triggers that are specifically in service"""
    async def __call__(self,update,state:FSMContext):
        return "Myinfo_form" in await state.get_state()

class CallBackFilter(BaseFilter):
   def __init__(self,target_data ='',target_group=''):
      self.target_data = target_data
      self.target_group = target_group
      super().__init__()
   async def __call__(self, call:CallbackQuery,state:FSMContext):
      current_service = This_service()
      # print("my_info_callfilter:\t",call.data)
      if not current_service:
         return False

      if call.data == self.target_data.casefold():
         return True
      elif FromGen.get_btnGroup(call.data) == self.target_group.casefold():
         return True


class Myinfo_form(StatesGroup):
  dispInfo  = State()
  editMode = State()




class Update_RegInfo:
  service_name = "updateReg"

  def __init__(self):
    self.verify = Verify()
    self.router = Router()
    self.setup_handlers()
    self.service_name = Update_RegInfo.service_name



  def setup_handlers(self):
    @self.router.message(Command('myinfo'))
    async def pilot(message:types.Message, state:FSMContext):
      all_Data  = await state.get_data()
      last_interaction_time = all_Data.get("last_interaction_time")
      await state.clear() #clear previous history
      await state.update_data(last_interaction_time = last_interaction_time)
      await state.set_state(Myinfo_form.dispInfo)
      await self.display_info(message)

    @self.router.callback_query(CallBackFilter(target_data=self.gen('edit')))
    async def _(call:types.CallbackGame,state:FSMContext):
      # await state.set_state(Myinfo_form.editMode)
      await self.edit_handler(call)
    @self.router.callback_query(CallBackFilter(target_group ='Editing'))
    async def _(call:types.CallbackQuery,state:FSMContext):
      await state.set_state(Myinfo_form.editMode)
      # await state.set_state(Myinfo_form.EditInProg)
      await state.update_data(editing = call.data)
      await self.start_editing(call)

    @self.router.callback_query(CallBackFilter(target_data=self.gen('Cancel edit')))
    async def _(call:types.CallbackQuery,state:FSMContext):
      await call.answer()
      all_Data  = await state.get_data()
      last_interaction_time = all_Data.get("last_interaction_time")
      await state.clear() #clear previous history
      await state.update_data(last_interaction_time = last_interaction_time)
      await state.set_state(Myinfo_form.dispInfo)
      return await self.display_info(call)

    @self.router.callback_query(CallBackFilter(target_data=self.gen('Leave empty')))
    async def _(call:types.CallbackQuery,state:FSMContext):
      await call.answer()
      tgID = call.from_user.id
      query = await sync_to_async(UserInfo.objects.filter)(tgID =tgID)
      user = await sync_to_async( query.first)()
      all_data  = await state.get_data()
      last_interaction_time = all_data.get("last_interaction_time")
      editing = all_data.get("editing")

      # Add null check for editing
      if not editing:
          await state.clear()
          await state.update_data(last_interaction_time = last_interaction_time)
          await state.set_state(Myinfo_form.dispInfo)
          return await self.display_info(call)

      to_edit = FromGen.get_callData(editing).casefold()
      to_edit = "caNumber" if to_edit == "ca number" else to_edit

      if to_edit == "phone":
          await call.message.answer("You can't leave phone number empty")
          await state.clear()
          await state.update_data(last_interaction_time = last_interaction_time)
          await state.set_state(Myinfo_form.dispInfo)
          return await self.display_info(call)

      setattr(user,to_edit,"")
      await sync_to_async(user.save)()
      await call.message.answer("✅ updated successfully")
      await state.clear()
      await state.update_data(last_interaction_time = last_interaction_time)
      await state.set_state(Myinfo_form.dispInfo)
      return await self.display_info(call)


    @self.router.message(StateFilter(Myinfo_form.editMode))
    async def _(message:Message,state:FSMContext):
       await self.updating_info(message,state)


  def gen(self,callback:str,btn_group:str="btn")->str:
        """ for example gen("region","Addis Ababa")"""
        # This functon makes all call.data unique to it's respective service.
        """call_data = callback data(i.e call.data), and btn_group can be "region" or "csc" etc """
        return self.service_name.casefold().strip()+"$"+btn_group.casefold().strip()+">"+callback.casefold().strip()



  async def display_info(self, update: types.Update):
    tgID = update.from_user.id
    query = await sync_to_async(UserInfo.objects.filter)(tgID=tgID)
    is_registered = await sync_to_async(query.exists)()
    message = update if isinstance(update, types.Message) else update.message
    if is_registered:
        user = await sync_to_async(query.first)()

        summary_text = (
            "Here is you profile information :\n"
            f"👤 Name: {user.name}\n"
            f"📞 Phone: {user.phone}\n"
            f"📧 Email: {user.email}\n"
            f"🏠 Address: {user.address}\n"
        )

        message = update if isinstance(update, types.Message) else update.message
        replies = ("Exit")
        keyboard = [[KeyboardButton(text=replies)]]
        reply_markup = ReplyKeyboardMarkup(keyboard=keyboard, one_time_keyboard=True, resize_keyboard=True)
        await message.answer(summary_text, reply_markup=reply_markup)
        await message.answer("Ca numbers:")

        try:
            # Safely handle CA numbers
            ca_numbers = ""
            if user.caNumber:
                # Assuming caNumber is stored as a string representation of a list/set
                # First remove any surrounding brackets and quotes
                cleaned = user.caNumber.strip('[]{}\'\"')
                if cleaned:
                    # Split by comma and clean each number
                    numbers = [num.strip().strip('\'\"') for num in cleaned.split(',')]
                    for num in numbers:
                        if num:
                            ca_numbers += f"👉{num}\n"
                    if not ca_numbers:
                        ca_numbers = "No CA numbers Found"
                else:
                    ca_numbers = "No CA numbers Found"
            else:
                ca_numbers = "No CA numbers Found"

            await message.answer(f"{ca_numbers}")

        except Exception as e:
            print(f"Error processing CA numbers: {e}")
            await message.answer("Error displaying CA numbers")

        # for inline keyboard
        btns = ["Edit"]
        keyboard = [[InlineKeyboardButton(text=i, callback_data=self.gen(i)) for i in btns]]
        inline_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
        await message.answer("Choose action", reply_markup=inline_markup)

    else:
      await message.answer("⚠️ No registration information was found, please /start the bot and register first.")

  async def edit_handler(self,update):
    btns = ("Name","Phone","Email","Address","CA Number")
    icons = ("Edit      👤 ","Edit      📞","Edit      📧 ","Edit     🏠 ","Edit    📄")

    inline_Keyboard = [[InlineKeyboardButton(text =f"{icon}{btn}", callback_data=self.gen(btn,btn_group="Editing"))] for icon,btn in zip(icons,btns)]
    inline_markup = InlineKeyboardMarkup(inline_keyboard=inline_Keyboard)
    if isinstance(update,types.CallbackQuery):
      await update.answer()
      await update.message.answer("Choose field to edit:", reply_markup=inline_markup)
    else:
        await update.answer("Choose field to edit:", reply_markup=inline_markup)

  async def start_editing(self,call:CallbackQuery):
    """Generates Edit Buttons for editing"""

    data_to_edit = ["name","phone","email","address","ca number","bp number"]
    if FromGen.get_callData(call.data) in data_to_edit:
        reply = ["Exit"]
        inline_btns = []
        target = FromGen.get_callData(call.data).casefold()
        if target == 'phone':
          inline_btns = ["Cancel edit"]
        else:
            inline_btns = ["Leave empty","Cancel edit"]
        keyboard = [[KeyboardButton(text =i) for i in reply]]
        markup = ReplyKeyboardMarkup(keyboard=keyboard, one_time_keyboard=True, resize_keyboard=True)
        Inline_keyboard = [[InlineKeyboardButton(text =i, callback_data=self.gen(i)) for i in inline_btns] ]
        inline_markup = InlineKeyboardMarkup(inline_keyboard=Inline_keyboard)
        await call.answer()
        await call.message.answer("🆕", reply_markup=markup)

        await call.message.answer(f"Please enter your new <i><b>{target}</b></i>:", reply_markup=inline_markup,parse_mode='HTML')

  async def updating_info(self,message:types.Message,state:FSMContext):
    #incase of "cancel edit"
    if getattr(message,'text',None) == None:
      await message.answer(f"❗️Please Enter only texts")
      await state.update_data(edit =None)
      await state.set_state(Myinfo_form.dispInfo)
      return await self.display_info(message)

    if getattr(message,'text',None) is not None:
       if message.text.casefold().strip() == 'cancel edit':
          all_Data  = await state.get_data()
          last_interaction_time = all_Data.get("last_interaction_time")
          await state.clear() #clear previous history
          await state.update_data(last_interaction_time = last_interaction_time)
          await state.set_state(Myinfo_form.dispInfo)
          return await self.display_info(message)

    all_data  =  await state.get_data()
    editing = all_data.get('editing')
    tgID = message.from_user.id
    query = await sync_to_async(UserInfo.objects.filter)(tgID =tgID)
    user = await sync_to_async( query.first)()

    target = FromGen.get_callData(editing).casefold()

    if (target != 'phone') and  (message.text.casefold().strip() == 'leave empty'):
        if target == 'ca number':
           target = 'caNumber'
        setattr(user,target,'')
        await sync_to_async(user.save)()
        await message.answer(f"✅ {target} updated successfully")
        await state.update_data(edit =None)
        await state.set_state(Myinfo_form.dispInfo)
        await self.display_info(message)

    elif FromGen.get_callData(editing) == 'name':
        try:
            if await self.verify.name(message,buttons=["Exit"],inline_buttons=[self.gen("Leave empty"),self.gen("Cancel edit")]):
              user.name = message.text
              sync_to_async
              await sync_to_async(user.save)()
              # await sync_to_async(transaction.atomic)(lambda user: user.save())
              await message.answer("✅ name updated successfully")
              await state.update_data(edit =None)
              await state.set_state(Myinfo_form.dispInfo)
              await self.display_info(message)
        except Exception as e:
              print("error:\t",e)
              await message.answer("❌ sorry,something went wrong, please try again")
              await state.update_data(edit =None)
              await state.set_state(Myinfo_form.dispInfo)
              await self.display_info(message)

    elif FromGen.get_callData(editing) == 'phone':
        try:
          if await self.verify.phone_number(message,buttons=["Exit"],inline_buttons=[self.gen("Cancel edit")]):
                user.phone = "+251" + message.text[-9:] #message.text
                await sync_to_async(user.save)()
                await message.answer("✅ phone updated successfully")
                await state.set_state(Myinfo_form.dispInfo)
                await state.update_data(edit =None)
                await self.display_info(message)
        except IntegrityError:
            await message.answer("❌Failed... Sorry, this phone number is already registered, please try again")
            await state.update_data(edit =None)
            await state.set_state(Myinfo_form.dispInfo)
            await self.display_info(message)
        except Exception as e:
          print("error:\t",e)
          await message.answer("❗️ Sorry, something went wrong, please try again")
          await state.update_data(edit =None)
          await state.set_state(Myinfo_form.dispInfo)
          await self.display_info(message)

    elif FromGen.get_callData(editing) == 'email':
        try:
            if await self.verify.email(message,buttons = ["Exit"],inline_buttons=[self.gen("Leave empty"),self.gen("Cancel edit")]):
              user.email = message.text
              await sync_to_async(user.save)()
              await message.answer("✅email updated successfully")
              await state.set_state(Myinfo_form.dispInfo)
              await state.update_data(edit =None)
              await self.display_info(message)
        except IntegrityError:
            await message.answer("❌ Failed... Sorry, this email is already registered, please try again")
            await state.set_state(Myinfo_form.dispInfo)
            await state.update_data(edit =None)
            await self.display_info(message)
        except Exception as e:

            await message.answer("❗️ Sorry, something went wrong, please try again")
            await state.update_data(edit =None)
            await state.set_state(Myinfo_form.dispInfo)
            await self.display_info(message)
    elif FromGen.get_callData(editing) == 'address':
        try:
          if await self.verify.address(message,buttons=["Exit"],inline_buttons=[self.gen("Leave empty"),self.gen("Cancel edit")] ):
              user.address = message.text
              await sync_to_async(user.save)()
              # await sync_to_async(transaction.atomic)(lambda user: user.save())
              await message.answer("✅ address updated successfully")
              await state.update_data(edit =None)
              await state.set_state(Myinfo_form.dispInfo)
              await self.display_info(message)
        except:
          await message.answer("❗️ Sorry, something went wrong, please try again")
          await state.update_data(edit =None)
          await state.set_state(Myinfo_form.dispInfo)
          await self.display_info(message)
    elif FromGen.get_callData(editing) == 'ca number':
        try:
          if await self.verify.ca_bp_number(message,buttons=["Exit"],inline_buttons=[self.gen("Leave empty"),self.gen("Cancel edit")] ):
             ca_numbers = set(message.text.replace(" ","").strip().split(","))
             user.caNumber = ca_numbers
             await sync_to_async(user.save)()
             await message.answer("✅ CA Number updated successfully")
             await state.update_data(edit =None)
             await state.set_state(Myinfo_form.dispInfo)
             await self.display_info(message)
        except IntegrityError:
            await message.answer("❌ Failed... Sorry, this CA Number is already registered, please try again")
            await state.update_data(edit =None)
            await state.set_state(Myinfo_form.dispInfo)
            await self.display_info(message)
        except Exception as e:
            print(f"Error in my info while:\n{e}")
            await message.answer("❗️ Sorry, something went wrong, please try again")
            await state.update_data(edit =None)
            await state.set_state(Myinfo_form.dispInfo)
            await self.display_info(message)
    else:
        await message.answer("❗️Please, enter only texts")
        await state.update_data(edit =None)
        await state.set_state(Myinfo_form.dispInfo)
        await self.display_info(message)
