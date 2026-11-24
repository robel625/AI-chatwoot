"""
COMPLAINT SERVICE — CRS Public API Integration + OTP
"""
import os
import sys
import json
import uuid
import mimetypes
from pathlib import Path
from functools import partial
from typing import Any, Dict, List, Optional, Tuple
import html
import re
from dotenv import load_dotenv
import aiohttp
import asyncio
import logging
from aiogram import Router, types
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.filters import BaseFilter, StateFilter
from asgiref.sync import sync_to_async

# ─ Django setup ─────────────────────────────────────────────────────────────
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, "../"))
if project_root not in sys.path:
    sys.path.append(project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "eeuBotProject.settings")
import django
django.setup()

from eeuBotApp.models import UserInfo
from utils.calander_component import CalendarModule
from utils.verify import Verify
from utils.redirect import Redirect
from global_inputs import GlobalInputs
from path_collection import pathOf
from bot_logger import get_bot_logger, LogCategory
from shared_aiohttp import get_shared_session

# ── IMPORTS FROM CUSTOM FILTER ──
from utils.myCustomFilter import FromGen, MultiTextStateFilter, generate_btn

# 1. Create the partial filter baked with the service name
multiFilter = partial(MultiTextStateFilter, service_name="corrComp")

load_dotenv()

# ── SERVICE LOGGER ──────────────────────────────────────────────────────────
logger = get_bot_logger("corruption_service")

TOKEN = os.getenv("TOKEN")
PROXY_URL = os.getenv("PROXY_URL")

# ── CRS endpoints ────────────────────────────────────────────────────────────
CRS_BASE = os.getenv("CRS_BASE_URL", "http://crsnewbacktest.eeuethics.et")
CRS_COMPLAINT_URL = f"{CRS_BASE}{os.getenv('CRS_ENDPOINT_COMPLAINT', '/api/public/complaints/')}"
CRS_VERIFY_OTP_URL = f"{CRS_BASE}{os.getenv('CRS_ENDPOINT_VERIFY_OTP', '/api/public/verify-otp/')}"
CRS_CHECK_STATUS_URL = f"{CRS_BASE}{os.getenv('CRS_ENDPOINT_CHECK_STATUS', '/api/public/check-status/')}"
CRS_RESEND_OTP_URL = f"{CRS_BASE}{os.getenv('CRS_ENDPOINT_RESEND_OTP', '/api/public/resend-otp/')}"

# ── EXACT category values accepted by the CRS backend ────────────────────────
CRS_CATEGORY_CHOICES = [
    ("undue delaying of matters", "Undue Delaying of Matters"),
    ("Biribery, giving bribe, undue advantage", "Bribery, Giving Bribe, Undue Advantage"),
    ("acceptance of undue advantage", "Acceptance of Undue Advantage"),
    ("maladminstaration of EEU works", "Maladministration of EEU Works"),
    ("Illegal collection of money", "Illegal Collection of Money"),
    ("possession of unexplained money & property", "Possession of Unexplained Money and Property"),
    ("Breach of trust", "Breach of Trust"),
    ("using forgery document", "Using Forged Documents"),
    ("suppression of official or Organizational documents", "Suppression of Official or Organizational Documents"),
    ("Breach of official secrecy", "Breach of Official Secrecy"),
    ("Facilitating Act of Bribery", "Facilitating Acts of Bribery"),
    ("Abuse of power or responsibility", "Abuse of Power or Responsibility"),
    ("Distortion of priority", "Distortion of Priority"),
    ("Illegal electric line installation", "Illegal Electric Line Installation"),
    ("Discrimination", "Discrimination"),
    ("Involvement in situations that create a conflict of interest", "Involvement in Situations that Create a Conflict of Interest"),
    ("Others", "Others"),
]

# ── DISPLAY-ONLY office label fixes ──────────────────────────────────────────
# The office tree comes from the CRS backend and the original names are sent back
# verbatim. These overrides only beautify what the user sees on the buttons.
OFFICE_LABEL_OVERRIDES = {
    "somale": "Somali",
    "somaie": "Somali",
    "somali": "Somali",
}


def office_display_name(name: str) -> str:
    """Replace backend office spellings with the display version (label only)."""
    if not name:
        return name
    words = str(name).split(" ")
    return " ".join(OFFICE_LABEL_OVERRIDES.get(w.lower(), w) for w in words)


# ── WAF-bypass headers for the CRS backend ──
CRS_API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": CRS_BASE.rstrip("/"),
    "Referer": CRS_BASE.rstrip("/") + "/",
    "X-Security-Token": os.getenv("MAIL_API_TOKEN", "rgSecurtyetForm"),
}

# ── Upload API ──────────────────────────────────────────────────────────────
UPLOAD_API_URL = os.getenv("UPLOAD_API_URL", "https://media1.eeuethics.et/upload")
UPLOAD_API_HEADERS = (
    json.loads(os.getenv("UPLOAD_API_HEADERS"))
    if os.getenv("UPLOAD_API_HEADERS")
    else {
        "X-Security-Token": "rgwebuploadtonode",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://eeuethics.et",
        "Referer": "https://eeuethics.et/",
    }
)

# ── STATES ───────────────────────────────────────────────────────────────────
class CorrForm(StatesGroup):
    office_loc = State()      # UNIFIED STATE for geo_loc, region, and csc
    date = State()
    loc_incident = State()
    comp_type = State()
    report_detail = State()
    poi = State()
    poi_name = State()
    poi_position = State()
    poi_phone = State()
    attachments = State()
    user_phone = State()
    user_name = State()
    summary = State()
    otp = State()
    finished = State()

# ── LOCAL HELPERS & FILTERS ──────────────────────────────────────────────────
async def callback_control(call: types.CallbackQuery, state: FSMContext) -> bool:
    if not call or not call.data: return False
    if FromGen.get_service(call.data) != Corruption_complaint.service_name: return False
    data_order = {
        "region": "geo_loc", "csc": "region", "date": "csc",
        "cpt": "location", "submit": "attachments", "otp": "case_id",
    }
    all_data = await state.get_data()
    btn_group = FromGen.get_btnGroup(call.data)
    if btn_group in data_order:
        if all_data.get(data_order[btn_group]) is None:
            await call.answer("️ Please follow the appropriate process")
            return False
    return True

class Continue_case(BaseFilter):
    async def __call__(self, message: types.Message, state: FSMContext) -> bool:
        if not isinstance(message, types.Message): return False
        if message.content_type != "text" or not message.text: return False
        return message.text.casefold() == "continue" and "CorrForm" in (await state.get_state() or "")

class This_service(BaseFilter):
    async def __call__(self, update, state: FSMContext) -> bool:
        return "CorrForm" in (await state.get_state() or "")

class CallBackFilter(BaseFilter):
    def __init__(self, target: str): self.target = target
    async def __call__(self, call: types.CallbackQuery, state: FSMContext) -> bool:
        if not isinstance(call, types.CallbackQuery): return False
        if not await callback_control(call, state): return False
        data = FromGen.get_callData(call.data)
        all_data = await state.get_data()
        if self.target == "geo_loc":
            valid = [str(i) for i, _ in GlobalInputs.get_root_offices()]
            return str(data) in valid
        if self.target == "region":
            coord_id = all_data.get("coordination_id") or all_data.get("geo_loc")
            valid = [str(i) for i, _ in GlobalInputs.get_regions(coord_id)]
            return str(data) in valid
        if self.target == "csc":
            coord_id = all_data.get("coordination_id") or all_data.get("geo_loc")
            region_id = all_data.get("region_id") or all_data.get("region")
            valid = [str(i) for i, _ in GlobalInputs.get_cscs(coord_id, region_id)]
            return str(data) in valid
        if self.target == "comp_type":
            try: return 0 <= int(data) < len(CRS_CATEGORY_CHOICES)
            except (ValueError, TypeError): return False
        return False

# ══════════════════════════════════════════════════════════════════════════════
# SERVICE
# ══════════════════════════════════════════════════════════════════════════════
class Corruption_complaint:
    service_name = "corrComp"

    @staticmethod
    def _safe_err(data, status: int) -> str:
        if isinstance(data, dict):
            if "raw" in data:
                raw = str(data["raw"]).strip()
                if re.search(r"<(?:!DOCTYPE|html|head|meta|title|body)[\s>]", raw, re.IGNORECASE):
                    if status >= 500:
                        return "The complaint service is temporarily taking longer than usual to respond. Please try again in a moment."
                    elif status == 403:
                        return "The service is temporarily busy. Please wait a moment and try again."
                    elif status == 404:
                        return "The requested record could not be found."
                    return "The service is temporarily unavailable. Please try again in a moment."
                msg = raw
            elif data.get("error"):
                msg = str(data["error"])
            elif data.get("message"):
                msg = str(data["message"])
            elif data.get("detail"):
                msg = str(data["detail"])
            elif data.get("non_field_errors"):
                nfe = data["non_field_errors"]
                msg = ", ".join(str(x) for x in nfe) if isinstance(nfe, list) else str(nfe)
            else:
                field_errs = []
                for k, v in data.items():
                    if k == "raw": continue
                    if isinstance(v, list) and v:
                        field_errs.append(f"{k}: {', '.join(str(x) for x in v)}")
                    elif isinstance(v, str) and v:
                        field_errs.append(f"{k}: {v}")
                if field_errs:
                    msg = "; ".join(field_errs)
                else:
                    msg = json.dumps(data)[:300]
        else:
            msg = str(data)

        if re.search(r"<(?:!DOCTYPE|html|head|meta|title|body)[\s>]", msg, re.IGNORECASE):
            if status >= 500:
                return "The complaint service is temporarily taking longer than usual to respond. Please try again in a moment."
            elif status == 403:
                return "The service is temporarily busy. Please wait a moment and try again."
            elif status == 404:
                return "The requested record could not be found."
            return "The service is temporarily unavailable. Please try again in a moment."

        msg = re.sub(r"<[^>]+>", " ", msg)
        msg = re.sub(r"\s+", " ", msg).strip()
        if status >= 500 or not msg:
            return "The complaint service is temporarily taking longer than usual to respond. Please try again in a moment."
        return html.escape(msg[:300])

    def __init__(self, bot, token: str, eeu_office_tree: Optional[List] = None, proxy: Optional[str] = None):
        self.TOKEN = token
        self.bot = bot
        self.PROXY_URL = proxy
        self.eeu_office_tree = eeu_office_tree or []
        self.verify = Verify()
        self.redirect = Redirect()
        self.calendar_module = CalendarModule(self.service_name)
        self.calendar_module.set_date_callback(self.for_date)
        self.router = Router()
        self.router.include_router(self.calendar_module.router)
        self.service_status_path = Path(__file__).resolve().parent.parent / "services_status.json"
        self.setup_handlers()

    def gen(self, callback: str = "", btn_group: str = "btn") -> str:
        """Generate callback data with case-sensitive preservation for important data."""
        return generate_btn(self.service_name, callback, btn_group, case_sensitive=True)

    async def extra(self, state: FSMContext, event: str) -> dict:
        """Build the logger 'extra' dict from FSM state."""
        return {
            "catagory": event,
            "session_id": await state.get_value("session_id", "unknown"),
            "tg_id": await state.get_value("tg_id", "unknown"),
        }

    def build_buttons(self, items, key_type: str) -> InlineKeyboardMarkup:
        rows = []
        if key_type in ('geo_loc', 'region', 'csc'):
            for i in range(0, len(items), 2):
                first_id, first_name = items[i]
                row = [InlineKeyboardButton(text=office_display_name(str(first_name or first_id)), callback_data=self.gen(str(first_id), key_type))]
                if i + 1 < len(items):
                    second_id, second_name = items[i + 1]
                    row.append(InlineKeyboardButton(text=office_display_name(str(second_name or second_id)), callback_data=self.gen(str(second_id), key_type)))
                rows.append(row)
        else:
            for item_id, item_name in items:
                rows.append([InlineKeyboardButton(text=str(item_name or item_id), callback_data=self.gen(str(item_id), key_type))])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def _reply(self, update, text, reply_markup=None, parse_mode=None):
        message = update if isinstance(update, types.Message) else getattr(update, "message", None)
        if message: return await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
        chat_id = getattr(update, "from_user", None) and update.from_user.id
        if chat_id: return await self.bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)

    def _exit_keyboard(self) -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Exit")]], resize_keyboard=True)

    def _skip_inline(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Skip", callback_data=self.gen("skip"))]])

    # ═══════════════════════════════════════════════════════════════════════
    # HANDLERS
    # ═══════════════════════════════════════════════════════════════════════
    def setup_handlers(self):
        @self.router.message(Continue_case())
        async def continue_handler(msg: types.Message, state: FSMContext):
            await self.status_mapper(msg, state)

        @self.router.callback_query(lambda c: c.data and "report corruption" in c.data.lower())
        async def pilot(call: types.CallbackQuery, state: FSMContext):
            if not await self._service_enabled(call, state, "report corruption"): return
            await call.answer()
            
            session_id = str(uuid.uuid4())
            await state.update_data(session_id=session_id, tg_id=str(call.from_user.id))
            logger.info(f"User {call.from_user.id} entered the corruption reporting service", extra=await self.extra(state, LogCategory.SERVICE_ENTRY))

            if not GlobalInputs.is_ready():
                waiting_msg = await call.message.answer("⏳ <b>Please wait...</b>\n\nWe're preparing the corruption reporting service.", parse_mode="HTML")
                load_success = await GlobalInputs.wait_for_load(timeout=15.0)
                try: await waiting_msg.delete()
                except: pass
                if not load_success or not GlobalInputs.is_ready():
                    status = GlobalInputs.get_load_status()
                    error_msg = status.get("error_message", "Unknown error")
                    logger.error(f"Failed to load office tree: {error_msg}", extra=await self.extra(state, LogCategory.API_FAIL))
                    return await call.message.answer("❌ <b>Service Temporarily Unavailable</b>", parse_mode="HTML", reply_markup=self._exit_keyboard())
            
            tg_id = str(call.from_user.id)
            exists = await sync_to_async(UserInfo.objects.filter(tgID=tg_id).exists)()
            if not exists:
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Register", callback_data="mainhandler$btn>register")]])
                return await call.message.answer("Please register first to use this service.", reply_markup=kb)
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📨 Send a Complaint", callback_data=self.gen("new", "entry"))],
                [InlineKeyboardButton(text=" Check Status", callback_data=self.gen("status", "entry"))],
            ])
            await call.message.answer("🛡️ <b>Corruption Reporting Service</b>\nChoose an option:", reply_markup=kb, parse_mode="HTML")

        @self.router.callback_query(multiFilter([], ["new"], btn_group=["entry"]))
        async def entry_new_complaint(call: types.CallbackQuery, state: FSMContext):
            await call.answer()
            data = await state.get_data()
            session_id, tg_id = data.get("session_id"), data.get("tg_id")
            await state.clear()
            if session_id: await state.update_data(session_id=session_id, tg_id=tg_id)
            await state.set_state(CorrForm.office_loc)
            await self.geo_loc_handler(call)

        @self.router.callback_query(multiFilter([], ["status"], btn_group=["entry"]))
        async def entry_check_status(call: types.CallbackQuery, state: FSMContext):
            await call.answer()
            data = await state.get_data()
            if data.get("case_id") and data.get("phone_number"):
                return await self.handle_status_check(call.message, data["case_id"], data["phone_number"], state)
            
            session_id, tg_id = data.get("session_id"), data.get("tg_id")
            await state.clear()
            await state.set_state(CorrForm.finished)
            updates = {"awaiting_case_id": True, "awaiting_phone": False, "temp_case_id": None}
            if session_id: updates.update({"session_id": session_id, "tg_id": tg_id})
            await state.update_data(**updates)
            await call.message.answer("📋 Enter your Case ID (e.g. CRS-2026-0252):", reply_markup=self._exit_keyboard())

        # ── UNIFIED LOCATION HANDLERS (Using btn_group to distinguish) ──
        @self.router.callback_query(multiFilter([CorrForm.office_loc], btn_group=["geo_loc"]))
        async def geo_loc_selected(call: types.CallbackQuery, state: FSMContext):
            await call.answer()
            office_id = FromGen.get_callData(call.data)
            office_name = GlobalInputs.get_office_name_by_id(office_id) or office_id
            kind = GlobalInputs.get_office_kind(office_id)
            
            # Clear downstream data if user goes back
            await state.update_data(region=None, region_id=None, region_name=None, csc=None, csc_id=None, csc_name=None)
            
            if kind == "coordination":
                await state.update_data(geo_loc=office_id, coordination_id=office_id, coordination_name=office_name)
                await self.region_handler(call, state)
            else:
                await state.update_data(geo_loc=office_id, region=office_id, region_id=office_id, region_name=office_name)
                await self.csc_handler(call, state)

        @self.router.callback_query(multiFilter([CorrForm.office_loc], btn_group=["region"]))
        async def region_selected(call: types.CallbackQuery, state: FSMContext):
            await call.answer()
            region_id = FromGen.get_callData(call.data)
            region_name = GlobalInputs.get_office_name_by_id(region_id) or region_id
            
            # Clear downstream data if user goes back
            await state.update_data(csc=None, csc_id=None, csc_name=None)
            await state.update_data(region=region_id, region_id=region_id, region_name=region_name)
            
            await self.csc_handler(call, state)

        @self.router.callback_query(multiFilter([CorrForm.office_loc], btn_group=["csc"]))
        async def csc_selected(call: types.CallbackQuery, state: FSMContext):
            await call.answer()
            csc_id = FromGen.get_callData(call.data)
            csc_name = GlobalInputs.get_office_name_by_id(csc_id) or csc_id
            
            await state.update_data(csc=csc_id, csc_id=csc_id, csc_name=csc_name)
            
            # Once csc is chosen, move to the next state
            await state.set_state(CorrForm.date)
            await self.date_handler(call)

        @self.router.message(CorrForm.loc_incident)
        async def incident_location_handler(msg: types.Message, state: FSMContext):
            if await self.verify.address(msg, buttons=["Exit"]):
                await state.update_data(location=msg.text.lower())
                await state.set_state(CorrForm.comp_type)
                await self.complaint_type_handler(msg)

        @self.router.callback_query(CallBackFilter("comp_type"))
        async def complaint_type_selected(call: types.CallbackQuery, state: FSMContext):
            await call.answer()
            idx = FromGen.get_callData(call.data)
            try: value, label = CRS_CATEGORY_CHOICES[int(idx)]
            except (ValueError, IndexError): return await call.message.answer("❌ Invalid selection.")
            await state.update_data(catagory=value, catagory_display=label)
            await state.set_state(CorrForm.report_detail)
            await self.complaint_discription_handler(call)

        @self.router.message(CorrForm.report_detail)
        async def report_detail_handler(msg: types.Message, state: FSMContext):
            if await self.verify.report_corr(msg, buttons=["Exit"]):
                await state.update_data(report_detail=msg.text)
                await state.set_state(CorrForm.poi)
                await self.poi_handler(msg)

        @self.router.callback_query(multiFilter([CorrForm.poi], ["yes"]))
        async def poi_yes_handler(call: types.CallbackQuery, state: FSMContext):
            await call.answer()
            await state.set_state(CorrForm.poi_name)
            await self.poi_name_handler(call)

        @self.router.message(multiFilter([CorrForm.poi_name]))
        async def poi_name_msg_handler(msg: types.Message, state: FSMContext):
            if await self.verify.name(msg, buttons=["Exit"], inline_buttons=[self.gen("Skip")]):
                await state.update_data(suspicious_name=msg.text)
                await state.set_state(CorrForm.poi_position)
                await self.poi_position_handler(msg)

        @self.router.message(multiFilter([CorrForm.poi_position]))
        async def poi_position_msg_handler(msg: types.Message, state: FSMContext):
            if await self.verify.position(msg, buttons=["Exit"], inline_buttons=[self.gen("Skip")]):
                await state.update_data(suspicious_position=msg.text)
                await state.set_state(CorrForm.poi_phone)
                await self.poi_phone_handler(msg)

        @self.router.message(multiFilter([CorrForm.poi_phone]))
        async def poi_phone_msg_handler(msg: types.Message, state: FSMContext):
            if await self.verify.phone_number(msg, allow_skip=True, buttons=["Exit"], inline_buttons=[self.gen("Skip")]):
                await state.update_data(suspicious_phone=msg.text)
                await state.set_state(CorrForm.attachments)
                await self.attachment_handler(msg)

        @self.router.callback_query(multiFilter([CorrForm.attachments], ["continue to next", "cancel"]))
        async def attachment_control_handler(call: types.CallbackQuery, state: FSMContext):
            await call.answer()
            action = FromGen.get_callData(call.data).casefold()
            if action == "continue to next":
                await state.set_state(CorrForm.user_phone)
                return await self.user_phone_handler(call)
            if action == "cancel":
                await call.message.answer("Attachment cancelled.")
                await state.update_data(attachments=[])
                return await self.attachment_handler(call)

        @self.router.message(StateFilter(CorrForm.attachments))
        async def handling_upload(msg: types.Message, state: FSMContext):
            data = await state.get_data()
            text = (msg.text or msg.caption or "").strip()
            if text:
                text_cf = text.casefold()
                if text_cf == "skip":
                    await state.update_data(attachments=[])
                    await state.set_state(CorrForm.user_phone)
                    return await self.user_phone_handler(msg)
                if text_cf == "cancel":
                    await msg.answer("Attachment cancelled.")
                    await state.update_data(attachments=[])
                    return await self.attachment_handler(msg)
                if text_cf == "continue to next":
                    await state.set_state(CorrForm.user_phone)
                    return await self.user_phone_handler(msg)
                if data.get("attachments"):
                    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=i, callback_data=self.gen(i.casefold()))] for i in ("Continue to next", "Cancel")])
                    await msg.answer("⚠️", reply_markup=self._exit_keyboard())
                    return await msg.answer("Click <b>'Continue to next'</b> to proceed or <b>'Cancel'</b> to cancel attachments.", reply_markup=kb, parse_mode="HTML")
                return await self.status_mapper(msg, state)
            await self.for_attachments_handler(msg, state)

        @self.router.message(CorrForm.user_phone)
        async def user_phone_msg_handler(msg: types.Message, state: FSMContext):
            if await self.verify.phone_number(msg, buttons=["Exit"]):
                await state.update_data(phone_number=msg.text.strip())
                await state.set_state(CorrForm.user_name)
                await self.user_name_handler(msg)

        @self.router.message(CorrForm.user_name)
        async def user_name_msg_handler(msg: types.Message, state: FSMContext):
            if await self.verify.name(msg, buttons=["Exit"]):
                await state.update_data(full_name=msg.text.strip())
                await state.set_state(CorrForm.summary)
                await self.summary_handler(msg, state)

        @self.router.callback_query(multiFilter([CorrForm.summary], ["submit"], btn_group=["submit"]))
        async def submit_handler(call: types.CallbackQuery, state: FSMContext):
            await call.answer()
            await self._reply(call, "🔄 Submitting complaint... please wait.")
            case_id = await self.submit_to_crs(call, state)
            if not case_id:
                retry_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Try Submitting Again", callback_data=self.gen("submit", "submit"))],
                    [InlineKeyboardButton(text="🏠 Main Menu", callback_data=self.gen("main menu"))],
                ])
                await self._reply(call, "Your complaint information is safely saved. Tap below to try submitting again:", reply_markup=retry_kb)
                return
            data = await state.get_data()
            await state.update_data(case_id=case_id, otp_attempts=0)
            await state.set_state(CorrForm.otp)
            await self.otp_handler(call, phone_number=data.get("phone_number"))

        @self.router.message(CorrForm.otp)
        async def otp_input_handler(msg: types.Message, state: FSMContext):
            code = (msg.text or "").strip()
            if not (code.isdigit() and len(code) == 4):
                return await msg.answer("❌ Enter a valid 4-digit OTP (or press Exit).", reply_markup=self._exit_keyboard())
            await msg.answer("🔄 Verifying OTP...")
            result = await self.verify_otp(state, code)
            if result.get("verified"):
                await state.set_state(CorrForm.finished)
                case_id = (await state.get_data()).get("case_id")
                await msg.answer("✅ OTP verified! Complaint submitted.")
                await msg.answer(f"✔️ Your Case ID: <b>{case_id}</b>", reply_markup=self._exit_keyboard(), parse_mode="HTML")
                return await self.show_post_submit_options(msg, case_id)
            data = await state.get_data()
            attempts = data.get("otp_attempts", 0) + 1
            await state.update_data(otp_attempts=attempts)
            if attempts >= 3:
                await state.clear()
                return await msg.answer("❌ Maximum OTP attempts reached. Please /start and try again.", reply_markup=ReplyKeyboardRemove())
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Resend OTP", callback_data=self.gen("resend_otp", "otp"))]])
            await msg.answer(f" {result.get('error', 'Invalid OTP')} — attempt {attempts}/3.\nTry again or click Resend OTP.", reply_markup=kb)

        @self.router.callback_query(multiFilter([CorrForm.otp], ["resend_otp"], btn_group=["otp"]))
        async def resend_otp_handler(call: types.CallbackQuery, state: FSMContext):
            await call.answer("Resending OTP...")
            data = await state.get_data()
            case_id = data.get("case_id")
            if not case_id:
                await call.message.answer("❌ Session expired. Please /start again.", reply_markup=self._exit_keyboard())
                return
            res = await self.resend_otp(state, case_id, data.get("phone_number"))
            icon = "📱" if res.get("success") else "⚠️"
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Resend OTP", callback_data=self.gen("resend_otp", "otp"))]])
            await call.message.answer(f"{icon} {res.get('message', 'A new OTP has been sent.')}", reply_markup=kb)

        @self.router.callback_query(multiFilter([CorrForm.finished], ["main menu"]))
        async def to_mainmenu(call: types.CallbackQuery, state: FSMContext):
            await call.answer()
            await self.redirect.toMainMenu(call,state)
        @self.router.message(StateFilter(CorrForm.finished))
        async def status_input_handler(msg: types.Message, state: FSMContext):
            data = await state.get_data()
            if data.get("awaiting_case_id"):
                await state.update_data(temp_case_id=(msg.text or "").strip(), awaiting_case_id=False, awaiting_phone=True)
                return await msg.answer("📞 Enter the phone number associated with this complaint:", reply_markup=self._exit_keyboard())
            if data.get("awaiting_phone"):
                if not await self.verify.phone_number(msg, buttons=["Exit"]): return
                phone_text = (msg.text or "").strip()
                case_id = data.get("temp_case_id", "")
                await state.update_data(case_id=case_id, phone_number=phone_text)
                await self.handle_status_check(msg, case_id, phone_text, state)
                return
            await self.status_mapper(msg, state)

        @self.router.callback_query(multiFilter([], ["status"], btn_group=["post"]))
        async def post_submit_check_status(call: types.CallbackQuery, state: FSMContext):
            await call.answer()
            data = await state.get_data()
            case_id = data.get("case_id") or data.get("temp_case_id")
            phone = data.get("phone_number")
            if case_id and phone:
                return await self.handle_status_check(call.message, case_id, phone, state)
            await state.set_state(CorrForm.finished)
            await state.update_data(awaiting_case_id=True, awaiting_phone=False, temp_case_id=None)
            await call.message.answer("📋 Enter your Case ID (e.g. CRS-2026-0252):", reply_markup=self._exit_keyboard())

        @self.router.callback_query(multiFilter(
            [CorrForm.office_loc, CorrForm.date, CorrForm.comp_type, CorrForm.poi, CorrForm.poi_name, CorrForm.poi_position, CorrForm.poi_phone, CorrForm.attachments],
            ["skip"]
        ))
        async def skip_handler(call: types.CallbackQuery, state: FSMContext):
            await call.answer()
            st = await state.get_state()
            if st == CorrForm.office_loc.state:
                is_region =  await state.get_value("region") is not None
                if not is_region:
                    return
                await state.update_data(csc="skip",csc_id=None)
                await state.set_state(CorrForm.date)
                return await self.date_handler(call)
            if st == CorrForm.date.state:
                await state.update_data(incident_happend_Date="skip")
                await state.set_state(CorrForm.loc_incident)
                return await self.location_ofIncident(call)
            if st == CorrForm.comp_type.state:
                await state.update_data(catagory="skip")
                await state.set_state(CorrForm.report_detail)
                return await self.complaint_discription_handler(call)
            if st == CorrForm.poi.state:
                await state.update_data(suspicious_name="skip", suspicious_position="skip", suspicious_phone="skip")
                await state.set_state(CorrForm.attachments)
                return await self.attachment_handler(call)
            if st == CorrForm.poi_name.state:
                await state.update_data(suspicious_name="skip")
                await state.set_state(CorrForm.poi_position)
                return await self.poi_position_handler(call)
            if st == CorrForm.poi_position.state:
                await state.update_data(suspicious_position="skip")
                await state.set_state(CorrForm.poi_phone)
                return await self.poi_phone_handler(call)
            if st == CorrForm.poi_phone.state:
                await state.update_data(suspicious_phone="skip")
                await state.set_state(CorrForm.attachments)
                return await self.attachment_handler(call)
            if st == CorrForm.attachments.state:
                await state.update_data(attachments=[])
                await state.set_state(CorrForm.user_phone)
                return await self.user_phone_handler(call)

        @self.router.message(This_service())
        async def fallback_mapper(msg: types.Message, state: FSMContext):
            await self.status_mapper(msg, state)

    # ═══════════════════════════════════════════════════════════════════════
    # UI METHODS
    # ═══════════════════════════════════════════════════════════════════════
    async def geo_loc_handler(self, update):
        await GlobalInputs.load_eeu_office_tree()
        offices = GlobalInputs.get_root_offices()
        if not offices: return await self._reply(update, "❌ Could not load coordination offices/regions.")
        await self._reply(update, "Select the <b>EEU Coordination Office / Region</b>:", reply_markup=self._exit_keyboard(), parse_mode="HTML")
        await self._reply(update, "🏢 Where did the incident happen?", reply_markup=self.build_buttons(offices, "geo_loc"))

    async def region_handler(self, update, state: FSMContext):
        # Keeps state as office_loc so user can still go back to geo_loc
        data = await state.get_data()
        coord_id = data.get("coordination_id") or data.get("geo_loc")
        regions = GlobalInputs.get_regions(coord_id)
        if not regions:
            direct = GlobalInputs.get_cscs(coord_id, None)
            if direct:
                name = GlobalInputs.get_office_name_by_id(coord_id) or coord_id
                await state.update_data(region=coord_id, region_id=coord_id, region_name=name)
                await state.set_state(CorrForm.office_loc) # Keep unified state
                return await self.csc_handler(update, state)
            await state.update_data(region="skip", csc="skip")
            await state.set_state(CorrForm.date)
            return await self.date_handler(update)
        await self._reply(update, "🏢 Choose the <b>EEU Region</b>:", reply_markup=self._exit_keyboard(), parse_mode="HTML")
        await self._reply(update, "Select the region:", reply_markup=self.build_buttons(regions, "region"))

    async def csc_handler(self, update, state: FSMContext):
        # Keeps state as office_loc so user can still go back to region
        data = await state.get_data()
        coord_id = data.get("coordination_id") or data.get("geo_loc")
        region_id = data.get("region_id") or data.get("region")
        cscs = GlobalInputs.get_cscs(coord_id, region_id)
        if not cscs:
            await state.update_data(csc="skip", csc_id=None, csc_name=None)
            await state.set_state(CorrForm.date) # Only move to date if no CSCs exist
            return await self.date_handler(update)
        await self._reply(update, "🏢 Choose the <b>CSC</b>:", reply_markup=self._exit_keyboard(), parse_mode="HTML")
        await self._reply(update, "Select customer service center:", reply_markup=self.build_buttons(cscs, "csc"))
        await self._reply(update, "⏭️ Or skip", reply_markup=self._skip_inline())

    async def date_handler(self, update):
        await self._reply(update, "📅", reply_markup=self._exit_keyboard())
        await self._reply(update, "Select incident date:", reply_markup=self.calendar_module.create_gregorian_calendar(*self.calendar_module.get_today_gregorian_date()))
        await self._reply(update, "⏭️ Or skip", reply_markup=self._skip_inline())

    async def for_date(self, call: types.CallbackQuery, state: FSMContext, date: str):
        if not await callback_control(call, state): return
        await call.message.answer(f"📆 Selected: {date}")
        await call.answer()
        await state.update_data(incident_happend_Date=date)
        await state.set_state(CorrForm.loc_incident)
        await self.location_ofIncident(call)

    async def location_ofIncident(self, update): await self._reply(update, "📍 Specify the incident location:", reply_markup=self._exit_keyboard())
    async def complaint_type_handler(self, update):
        items = [(str(i), label) for i, (_value, label) in enumerate(CRS_CATEGORY_CHOICES)]
        await self._reply(update, "📄 Corruption type?", reply_markup=self._exit_keyboard())
        await self._reply(update, "Select:", reply_markup=self.build_buttons(items, "cpt"))
        await self._reply(update, "️ Or skip", reply_markup=self._skip_inline())
    async def complaint_discription_handler(self, update): await self._reply(update, "📋 Briefly explain your case:", reply_markup=self._exit_keyboard())
    async def poi_handler(self, update):
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Yes", callback_data=self.gen("yes")), InlineKeyboardButton(text="Skip", callback_data=self.gen("skip"))]])
        await self._reply(update, "Is there a specific person linked to this corruption?", reply_markup=kb)
    async def poi_name_handler(self, update):
        await self._reply(update, "PERSON'S NAME", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Exit")]], resize_keyboard=True, one_time_keyboard=True))
        await self._reply(update, "Enter the name:", reply_markup=self._skip_inline())
    async def poi_position_handler(self, update):
        await self._reply(update, "POSITION / ROLE", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Exit")]], resize_keyboard=True, one_time_keyboard=True))
        await self._reply(update, "Enter their position:", reply_markup=self._skip_inline())
    async def poi_phone_handler(self, update):
        await self._reply(update, "SUSPICIOUS PERSON'S PHONE NUMBER", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Exit")]], resize_keyboard=True, one_time_keyboard=True))
        await self._reply(update, "Enter their phone:", reply_markup=self._skip_inline())
    async def attachment_handler(self, update):
        await self._reply(update, "ATTACHMENTS — up to 2 files, one at a time, less than 19MB each.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Exit")]], resize_keyboard=True, one_time_keyboard=True))
        await self._reply(update, "Send your evidence:", reply_markup=self._skip_inline())

    async def for_attachments_handler(self, msg: types.Message, state: FSMContext):
        data = await state.get_data()
        valid, file_id, file_name = await self.verify.attachments(msg, state)
        if not valid: return
        max_files = 2
        current = len(data.get("attachments", [])) + 1
        if current > max_files:
            await state.update_data(attachments=[])
            await msg.answer(f"❌ Max {max_files} attachments exceeded. Start over.")
            return await self.attachment_handler(msg)
        info = await self.bot.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{self.TOKEN}/{info.file_path}"
        clean_name = (file_name or "attachment").replace(" ", "_")
        attachments = data.get("attachments", [])
        attachments.append({"file_path": url, "file_name": clean_name})
        await state.update_data(attachments=attachments)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=i, callback_data=self.gen(i.casefold()))] for i in ("Continue to next", "Cancel")])
        text = f"✔️ Attachment {len(attachments)}/{max_files} received: {clean_name}\n\n📎 You can add <b>one more file</b> (optional)." if len(attachments) < max_files else f"✔️ Attachment {len(attachments)}/{max_files} received: {clean_name}\n\n📎 Maximum attachments reached."
        await msg.answer(text, reply_markup=kb, parse_mode="HTML")

    async def user_phone_handler(self, update):
        phone = None
        try:
            user_id = update.from_user.id if isinstance(update, types.Message) else (update.from_user.id if getattr(update, "from_user", None) else (getattr(update, "message", None).from_user.id if getattr(update, "message", None) else None))
            if user_id:
                user = await sync_to_async(UserInfo.objects.filter(tgID=str(user_id)).first)()
                if user and getattr(user, "phone", None): phone = str(user.phone).strip()
        except Exception as e: print(f"[user_phone] lookup error: {e}")
        if phone:
            kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=phone)], [KeyboardButton(text="Exit")]], resize_keyboard=True, one_time_keyboard=True)
            await self._reply(update, f"📞 Tell us your Phone number.\nTap {phone} below to use your registered number, or type a different one.", reply_markup=kb)
        else:
            await self._reply(update, "📞 Tell us your Phone number.", reply_markup=self._exit_keyboard())

    async def user_name_handler(self, update):
        registered_name = None
        try:
            user_id = update.from_user.id if isinstance(update, types.Message) else (update.from_user.id if getattr(update, "from_user", None) else (getattr(update, "message", None).from_user.id if getattr(update, "message", None) else None))
            if user_id:
                user = await sync_to_async(UserInfo.objects.filter(tgID=str(user_id)).first)()
                if user and getattr(user, "name", None): registered_name = str(user.name).strip()
        except Exception as e: print(f"[user_name] lookup error: {e}")
        rows = [[KeyboardButton(text=registered_name)]] if registered_name else []
        rows.append([KeyboardButton(text="Exit")])
        kb = ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)
        if registered_name:
            await self._reply(update, f" Tell us your <b>Full Name</b>.\nTap {registered_name} below to use the name you registered with, or type your name.", reply_markup=kb, parse_mode="HTML")
        else:
            await self._reply(update, "👤 Tell us your <b>Full Name</b>:", reply_markup=kb, parse_mode="HTML")

    async def summary_handler(self, update, state: FSMContext):
        user_id = str(update.from_user.id)
        query = await sync_to_async(UserInfo.objects.filter)(tgID=user_id)
        if not await sync_to_async(query.exists)():
            await state.clear()
            return await self._reply(update, "You are not registered. Please /start and register.")
        user = await sync_to_async(query.first)()
        d = await state.get_data()
        await state.update_data(full_name=(d.get("full_name") or "").strip() or user.name, email=user.email, address=user.address)
        d = await state.get_data()
        office = "skip"
        if d.get("csc") and d["csc"] != "skip": office = d.get("csc_name") or d["csc"]
        elif d.get("region") and d["region"] != "skip": office = d.get("region_name") or d["region"]
        elif d.get("geo_loc") and d["geo_loc"] != "skip": office = d.get("coordination_name") or d["geo_loc"]
        await state.update_data(eeu_office=office)
        d = await state.get_data()
        def clean(k):
            v = d.get(k)
            return "" if v in (None, "", "skip") else str(v)
        detail = clean("report_detail")
        if len(detail) > 50: detail = detail[:50] + "..."
        text = (
            "Here is the information you provided:\n\n"
            f"👤 Full Name: {clean('full_name')}\n📞 Your phone number: {clean('phone_number')}\n✉️ Email: {clean('email')}\n Address: {clean('address')}\n Location: {clean('location')}\n EEU Office: {clean('eeu_office')}\n📅 Date: {clean('incident_happend_Date')}\n📝 Category: {clean('catagory_display') or clean('catagory')}\n📝 Detail: {detail}\n🤵 Suspect: {clean('suspicious_name')}\n👔 Position: {clean('suspicious_position')}\n📱 Suspicious person's phone number: {clean('suspicious_phone')}"
        )
        await self._reply(update, text, reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Exit")]], one_time_keyboard=True, resize_keyboard=True))
        await self._reply(update, "Choose action:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Submit", callback_data=self.gen("submit", "submit"))]]))

    # ═══════════════════════════════════════════════════════════════════════
    # CRS API
    # ═══════════════════════════════════════════════════════════════════════
    async def submit_to_crs(self, call: types.CallbackQuery, state: FSMContext):
        tg_id = str(call.from_user.id)
        if not await sync_to_async(UserInfo.objects.filter(tgID=tg_id).exists)():
            await state.clear()
            await call.message.answer("Not registered. Please /start.")
            return None
        d = await state.get_data()
        attachments = d.get("attachments", [])
        uploaded = []
        if attachments:
            for att in attachments:
                res = await self.upload_file(state, att["file_path"], att["file_name"])
                location = self._extract_upload_location(res)
                if location: uploaded.append({"filePath": location, "filename": att["file_name"]})
                else:
                    logger.warning(f"Could not find a file URL in upload response: {res}", extra=await self.extra(state, LogCategory.API_FAIL))
                    await call.message.answer(f" Failed to upload {att['file_name']}.")
                    return None
        def cv(k):
            v = d.get(k)
            return None if v in (None, "", "skip") else v
        payload = {k: cv(k) for k in ["full_name", "phone_number", "email", "address", "location", "eeu_office", "incident_happend_Date", "catagory", "report_detail", "suspicious_name", "suspicious_position", "suspicious_phone"]}
        payload.update({"source": "Telegram", "coordination": cv("coordination_id"), "region": cv("region_id"), "csc": cv("csc_id"), "attachments": uploaded})
        payload = {k: v for k, v in payload.items() if v not in (None, "", [])}
        
        session, proxy = await get_shared_session()
        req_timeout = aiohttp.ClientTimeout(total=20, sock_connect=6)
        max_attempts = 5
        delays = [1.5, 2.0, 3.0, 4.0]
        last_err = "The complaint service is temporarily taking longer than usual to respond. Please try again in a few moments."

        for attempt in range(1, max_attempts + 1):
            try:
                async with session.post(CRS_COMPLAINT_URL, json=payload, headers=CRS_API_HEADERS, proxy=proxy, timeout=req_timeout) as resp:
                    try: data = await resp.json(content_type=None)
                    except Exception: data = {"raw": await resp.text()}

                    if resp.status in (200, 201):
                        case_id = data.get("case_id") or data.get("caseId") or (data.get("data") or {}).get("case_id")
                        logger.info(f"Complaint submitted successfully on attempt {attempt}/{max_attempts} — case_id: {case_id}", extra=await self.extra(state, LogCategory.API_SUCCESS))
                        return case_id

                    # 500, 502, 503, 504 -> server glitch, retry
                    if resp.status in (500, 502, 503, 504):
                        logger.warning(f"CRS server glitch HTTP {resp.status} on attempt {attempt}/{max_attempts}", extra=await self.extra(state, LogCategory.API_FAIL))
                        last_err = self._safe_err(data, resp.status)
                        if attempt < max_attempts:
                            await asyncio.sleep(delays[attempt - 1])
                            continue
                        break

                    # 429 rate limit
                    if resp.status == 429:
                        logger.warning(f"CRS rate limit HTTP 429 on attempt {attempt}/{max_attempts}", extra=await self.extra(state, LogCategory.API_FAIL))
                        last_err = "The system is currently handling many requests. Please try again in a moment."
                        if attempt < max_attempts:
                            await asyncio.sleep(delays[attempt - 1] + 1.0)
                            continue
                        break

                    # 400 or other client error -> do not retry
                    last_err = self._safe_err(data, resp.status)
                    logger.warning(f"CRS rejected complaint submission — HTTP {resp.status}: {last_err}", extra=await self.extra(state, LogCategory.API_FAIL))
                    break
            except Exception as e:
                logger.warning(f"submit_to_crs attempt {attempt}/{max_attempts} network exception: {e}", extra=await self.extra(state, LogCategory.NETWORK_ERROR))
                last_err = "We are having trouble connecting to the complaint server. Please try again in a moment."
                if attempt < max_attempts:
                    await asyncio.sleep(delays[attempt - 1])
                    continue
                break

        await call.message.answer(f"⚠️ {last_err}")
        return None

    async def verify_otp(self, state: FSMContext, otp_code: str):
        case_id = (await state.get_data()).get("case_id")
        if not case_id: return {"verified": False, "error": "No case ID found. Please /start again."}
        session, proxy = await get_shared_session()
        req_timeout = aiohttp.ClientTimeout(total=15, sock_connect=5)
        max_attempts = 5
        delays = [1.0, 1.5, 2.5, 3.5]
        last_err = "The complaint service is temporarily taking longer than usual to respond. Please try again in a moment."

        for attempt in range(1, max_attempts + 1):
            try:
                async with session.post(CRS_VERIFY_OTP_URL, json={"case_id": case_id, "otp_code": otp_code}, headers=CRS_API_HEADERS, proxy=proxy, timeout=req_timeout) as r:
                    try: data = await r.json(content_type=None)
                    except Exception: data = {"raw": await r.text()}

                    if r.status == 200:
                        return {"verified": data.get("verified", True), "message": data.get("message")}

                    if r.status in (500, 502, 503, 504):
                        logger.warning(f"verify_otp server glitch HTTP {r.status} on attempt {attempt}/{max_attempts}", extra=await self.extra(state, LogCategory.API_FAIL))
                        last_err = self._safe_err(data, r.status)
                        if attempt < max_attempts:
                            await asyncio.sleep(delays[attempt - 1])
                            continue
                        break

                    # 400 Bad Request (incorrect OTP, expired, etc.) -> return immediately
                    return {"verified": False, "error": self._safe_err(data, r.status)}
            except Exception as e:
                logger.warning(f"verify_otp attempt {attempt}/{max_attempts} error: {e}", extra=await self.extra(state, LogCategory.NETWORK_ERROR))
                last_err = "Connection was interrupted. Please try again in a moment."
                if attempt < max_attempts:
                    await asyncio.sleep(delays[attempt - 1])
                    continue
                break

        return {"verified": False, "error": last_err}

    async def show_post_submit_options(self, message: types.Message, case_id: str):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Check Status", callback_data=self.gen("status", "post"))],
            [InlineKeyboardButton(text="🏠 Main Menu", callback_data=self.gen("main menu"))],
        ])
        await message.answer("What next?", reply_markup=kb)

    async def resend_otp(self, state: FSMContext, case_id: str, phone_number=None):
        payload = {"case_id": case_id}
        if phone_number: payload["phone_number"] = phone_number
        session, proxy = await get_shared_session()
        req_timeout = aiohttp.ClientTimeout(total=15, sock_connect=5)
        max_attempts = 5
        delays = [1.0, 1.5, 2.5, 3.5]
        last_err = "The complaint service is temporarily taking longer than usual to respond. Please try again in a moment."

        for attempt in range(1, max_attempts + 1):
            try:
                async with session.put(CRS_VERIFY_OTP_URL, json=payload, headers=CRS_API_HEADERS, proxy=proxy, timeout=req_timeout) as r:
                    try: data = await r.json(content_type=None)
                    except Exception: data = {"raw": await r.text()}

                    if r.status in (200, 201, 202):
                        return {"success": True, "message": data.get("message", "A new OTP has been sent to your phone.")}

                    if r.status in (500, 502, 503, 504):
                        logger.warning(f"resend_otp server glitch HTTP {r.status} on attempt {attempt}/{max_attempts}", extra=await self.extra(state, LogCategory.API_FAIL))
                        last_err = self._safe_err(data, r.status)
                        if attempt < max_attempts:
                            await asyncio.sleep(delays[attempt - 1])
                            continue
                        break

                    # 400 e.g. Maximum attempts exceeded
                    return {"success": False, "message": self._safe_err(data, r.status)}
            except Exception as e:
                logger.warning(f"resend_otp attempt {attempt}/{max_attempts} error: {e}", extra=await self.extra(state, LogCategory.NETWORK_ERROR))
                last_err = "Connection was interrupted. Please try again in a moment."
                if attempt < max_attempts:
                    await asyncio.sleep(delays[attempt - 1])
                    continue
                break

        return {"success": False, "message": last_err}

    async def otp_handler(self, update, phone_number: Optional[str] = None):
        inline_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Resend OTP", callback_data=self.gen("resend_otp", "otp"))]])
        phone_text = f" to <b>{phone_number}</b>" if phone_number else ""
        text = f"📱 <b>OTP Verification Required</b>\n\n✅ Your complaint was submitted and a 4-digit code has been sent{phone_text}.\nEnter the code below to verify."
        await self._reply(update, " Press <b>Exit</b> anytime to cancel.", reply_markup=self._exit_keyboard(), parse_mode="HTML")
        await self._reply(update, text, reply_markup=inline_kb, parse_mode="HTML")

    async def check_complaint_status(self, state: FSMContext, case_id: str, phone_number: str):
        session, proxy = await get_shared_session()
        req_timeout = aiohttp.ClientTimeout(total=15, sock_connect=5)
        max_attempts = 5
        delays = [1.0, 1.5, 2.5, 3.5]
        last_err = "The complaint service is temporarily taking longer than usual to respond. Please try again in a moment."
        last_status = 0

        for attempt in range(1, max_attempts + 1):
            try:
                async with session.post(CRS_CHECK_STATUS_URL, json={"case_id": case_id, "phone_number": phone_number}, headers=CRS_API_HEADERS, proxy=proxy, timeout=req_timeout) as r:
                    try: data = await r.json(content_type=None)
                    except Exception: data = {"raw": await r.text()}

                    if r.status == 200:
                        return data.get("complaint", data)

                    last_status = r.status
                    last_err = self._safe_err(data, r.status)

                    if r.status in (500, 502, 503, 504):
                        logger.warning(f"check_complaint_status server glitch HTTP {r.status} on attempt {attempt}/{max_attempts}", extra=await self.extra(state, LogCategory.API_FAIL))
                        if attempt < max_attempts:
                            await asyncio.sleep(delays[attempt - 1])
                            continue
                        break

                    # 400 (case not found / phone mismatch) -> return immediately
                    return {"error": last_err, "status": r.status}
            except Exception as e:
                logger.warning(f"check_complaint_status attempt {attempt}/{max_attempts} error: {e}", extra=await self.extra(state, LogCategory.NETWORK_ERROR))
                last_err = "Connection was interrupted. Please try again in a moment."
                last_status = 0
                if attempt < max_attempts:
                    await asyncio.sleep(delays[attempt - 1])
                    continue
                break

        return {"error": last_err, "status": last_status}

    async def handle_status_check(self, msg, case_id, phone, state: FSMContext):
        await msg.answer("🔍 Checking status...")
        res = await self.check_complaint_status(state, case_id, phone)
        if "error" in res:
            http_status = res.get("status", 0)
            err_msg = res.get("error", "Failed to check status.")
            logger.warning(f"Status check failed for case {case_id} (HTTP {http_status}): {err_msg}", extra=await self.extra(state, LogCategory.API_FAIL))
            
            # If case is truly not found or phone number mismatched (HTTP 400 or 404)
            if http_status in (400, 404):
                await state.set_state(CorrForm.finished)
                await state.update_data(awaiting_case_id=True, awaiting_phone=False, temp_case_id=None)
                await msg.answer(f"❌ {err_msg}\n📋 Enter your Case ID (e.g. CRS-2026-0252):", reply_markup=self._exit_keyboard())
                return
            
            # For temporary server or network glitches (500, 502, 503, 504, 403, connection drops)
            # Retain case_id and phone in state and provide Retry + Main Menu buttons
            retry_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Retry Check Status", callback_data=self.gen("status", "post"))],
                [InlineKeyboardButton(text="🏠 Main Menu", callback_data=self.gen("main menu"))],
            ])
            await msg.answer(f"⚠️ {err_msg}\nPlease try again in a moment.", reply_markup=retry_kb)
            return

        la = res.get("last_action", {}) or {}
        text = f"📋 <b>Case ID:</b> {case_id}\n📊 <b>Status:</b> {res.get('status_display', res.get('status', 'N/A'))}\n🔥 <b>Priority:</b> {res.get('priority_display', 'N/A')}\n📅 <b>Created:</b> {res.get('created_at', 'N/A')}\n📝 <b>Update:</b> {la.get('remark', 'No remarks yet')}"
        await msg.answer(text, parse_mode="HTML", reply_markup=self._exit_keyboard())
        await state.update_data(awaiting_case_id=False, awaiting_phone=False, temp_case_id=None)

    @staticmethod
    def _extract_upload_location(res) -> Optional[str]:
        if not isinstance(res, dict): return None
        for key in ("url", "location", "file_url", "fileUrl", "path", "filePath"):
            if res.get(key): return res[key]
        data = res.get("data")
        if isinstance(data, dict):
            for key in ("url", "location", "file_url", "fileUrl", "path", "filePath"):
                if data.get(key): return data[key]
        return None

    async def upload_file(self, state: FSMContext, file_path: str, file_name: str):
        if not file_path or not file_name: return {"message": "Invalid attachment.", "status": 400}
        session, proxy = await get_shared_session()
        long_timeout = aiohttp.ClientTimeout(total=300)
        try:
            async with session.get(file_path, proxy=proxy, timeout=long_timeout) as fr:
                if fr.status != 200:
                    logger.warning(f"Telegram download failed — HTTP {fr.status}: {file_path}", extra=await self.extra(state, LogCategory.API_FAIL))
                    return None
                content = await fr.read()
                logger.info(f"Downloaded {len(content)} bytes from Telegram: {file_name}", extra=await self.extra(state, LogCategory.API_SUCCESS))
        except Exception as e:
            logger.error(f"upload_file — download the attachment: {e}", extra=await self.extra(state, LogCategory.NETWORK_ERROR))
            return {"message": "Download failed", "error": str(e), "status": 500}
        
        ext = os.path.splitext(file_name)[1].lower()
        safe_filename = f"upload{ext}"
        content_type, _ = mimetypes.guess_type(file_name)
        if not content_type: content_type = "application/octet-stream"
        try:
            form = aiohttp.FormData()
            form.add_field("file", content, filename=safe_filename, content_type=content_type)
            async with session.post(UPLOAD_API_URL, headers=UPLOAD_API_HEADERS, data=form, proxy=proxy, timeout=long_timeout) as r:
                if r.status in (200, 201):
                    try: return await r.json(content_type=None)
                    except Exception: return {"status": r.status, "text": await r.text()}
                response_text = await r.text()
                logger.warning(f"Media-host upload failed — HTTP {r.status}: {response_text[:200]}", extra=await self.extra(state, LogCategory.API_FAIL))
                return {"message": "Upload failed", "error": response_text, "status": r.status}
        except Exception as e:
            logger.error(f"upload_file — re-upload: {e}", extra=await self.extra(state, LogCategory.NETWORK_ERROR))
            return {"message": "Upload failed", "error": str(e), "status": 500}

    async def status_mapper(self, update, state: FSMContext):
        current = await state.get_state()
        mapper = {
            CorrForm.office_loc.state: partial(self.geo_loc_handler, update), # Fallback if state is somehow lost
            CorrForm.date.state: partial(self.date_handler, update),
            CorrForm.loc_incident.state: partial(self.location_ofIncident, update),
            CorrForm.comp_type.state: partial(self.complaint_type_handler, update),
            CorrForm.report_detail.state: partial(self.complaint_discription_handler, update),
            CorrForm.poi.state: partial(self.poi_handler, update),
            CorrForm.poi_name.state: partial(self.poi_name_handler, update),
            CorrForm.poi_position.state: partial(self.poi_position_handler, update),
            CorrForm.poi_phone.state: partial(self.poi_phone_handler, update),
            CorrForm.attachments.state: partial(self.attachment_handler, update),
            CorrForm.user_phone.state: partial(self.user_phone_handler, update),
            CorrForm.user_name.state: partial(self.user_name_handler, update),
            CorrForm.summary.state: partial(self.summary_handler, update, state),
            CorrForm.otp.state: partial(self.otp_handler, update),
        }
        handler = mapper.get(current)
        if handler: return await handler()

    async def _service_enabled(self, call: types.CallbackQuery, state: FSMContext, service_key: str) -> bool:
        try:
            if not self.service_status_path.exists(): return True
            with open(self.service_status_path, "r", encoding="utf-8") as f: services = json.load(f)
            svc = services.get(service_key, {})
            if svc.get("status") == "inactive":
                await call.answer()
                return False
            if svc.get("status") == "disabled":
                if svc.get("message"): await call.answer(svc["message"], show_alert=True)
                else: await call.answer()
                return False
        except Exception as e:
            logger.error(f"Service status check failed: {e}", extra=await self.extra(state, LogCategory.CODE_CRASH))
            return True
        return True
    
    















          
          
          
          
          
          
          
          
          
          
          
          
          
          
          
             