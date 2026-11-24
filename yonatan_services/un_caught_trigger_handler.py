from aiogram import Router
from aiogram import types
from aiogram.fsm.context import FSMContext
router = Router()

@router.callback_query(lambda call:True)
async def pilot(call:types.CallbackQuery):
  await call.answer()

@router.message(lambda message: True)
async def _(message:types.Message,state:FSMContext):
  pass

#for the message we sill just  need to know the current service and then just map it to the servie's...   status_mappper.