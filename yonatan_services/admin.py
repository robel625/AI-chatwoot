from operator import call
from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup,ReplyKeyboardMarkup,ReplyKeyboardRemove,KeyboardButton, User
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
from utils.calander_component import CalendarModule 
from main_handler import MainHandler
from main_handler import Main_menu
import aiohttp
import json
from datetime import datetime,timedelta
from django.db import transaction
from utils.redirect import Redirect
import uuid
from zoneinfo import ZoneInfo
import re
import secrets



#________________________________________working_with_path____________________________________________
# making sure we are on the right path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '../')) #../..
# Add the project directory to the Python path
sys.path.append(project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "eeuBotProject.settings")
django.setup()
#________________________________________/path_______________________________________________________
from eeuBotApp.models import UserInfo, BotActivityLog, ActivityType, MeterReadingSubmission, Role, RoleType
from dotenv import load_dotenv
load_dotenv()
meter_type_URL = os.getenv("meter_type_URL")
meter_type_username =  os.getenv("meter_type_username")
meter_reading_password = os.getenv("meter_reading_password")
meter_recieve_data_url = os.getenv("meter_recieve_data_url")

class MultiTextStateFilter(BaseFilter):
    """allowed_states:List , text: List =[] (i.e text is optional)"""
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
        return gen[gen.index('>') + 1:]


class AdminStatesGroup(StatesGroup):
    # Authentication states
    login_password = State()
    # Main admin states
    main = State()
    summary = State()
    services = State()
    toggle_service = State()
    set_message = State()
    # Role management states
    roles = State()
    role_add_username = State()
    role_add_password = State()
    role_add_type = State()
    role_add_permissions = State()
    # Password change state
    change_password = State()


class Admin:
    service_name = 'admin'
    USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]{3,30}$')
    PASSWORD_PATTERN = re.compile(r'^\d{4}$')

    def __init__(self):
        self.router = Router()
        self.calendar_module = CalendarModule(self.service_name)
        self.router.include_router(self.calendar_module.router)
        self.services_status_path = os.path.join(project_root, 'services_status.json')
        self.calendar_module.set_date_callback(self._handle_calendar_date)
        self.setup_handlers()
        self._ensure_initial_admin()

    def _ensure_initial_admin(self):
        """
        Bootstrap the very first admin, but only from deployment-provided secrets.

        SECURITY (Case 3 fix): We no longer bake a fixed username/tg_id/PIN into the
        source code. A fresh deployment with no ADMIN_BOOTSTRAP_TG_ID env var simply
        has no admin until one is created via this one-time, secret-driven bootstrap.
        The generated/received password must be rotated on first login.
        """
        try:
            from django.db import connection
            if 'eeuBotApp_role' not in connection.introspection.table_names():
                print("Role table does not exist yet. Run migrations first.")
                return
            if Role.objects.filter(role=RoleType.ADMIN).exists():
                return  # Already bootstrapped

            bootstrap_tg_id = os.getenv('ADMIN_BOOTSTRAP_TG_ID')
            bootstrap_username = os.getenv('ADMIN_BOOTSTRAP_USERNAME')
            if not bootstrap_tg_id or not bootstrap_username:
                print(
                    "No admin exists yet and ADMIN_BOOTSTRAP_TG_ID / "
                    "ADMIN_BOOTSTRAP_USERNAME are not set. Skipping admin creation. "
                    "Set these env vars (and optionally ADMIN_BOOTSTRAP_PASSWORD) and "
                    "restart to bootstrap the first admin."
                )
                return

            bootstrap_password = os.getenv('ADMIN_BOOTSTRAP_PASSWORD')
            generated = False
            if not bootstrap_password or not self.PASSWORD_PATTERN.match(bootstrap_password):
                bootstrap_password = f"{secrets.randbelow(10000):04d}"
                generated = True

            admin_role = Role(
                username=bootstrap_username,
                tg_id=str(bootstrap_tg_id),
                role=RoleType.ADMIN,
                permissions={'can_toggle_services': True, 'can_manage_roles': True},
                is_active=True,
                must_change_password=True,
            )
            admin_role.set_password(bootstrap_password)
            admin_role.save()

            if generated:
                # Printed once, to the deployment console/log only — never stored in code or DB.
                print(
                    f"Initial admin '{bootstrap_username}' created with a generated one-time "
                    f"PIN: {bootstrap_password}. This PIN must be changed on first login."
                )
            else:
                print(
                    f"Initial admin '{bootstrap_username}' created from ADMIN_BOOTSTRAP_PASSWORD. "
                    f"This PIN must be changed on first login."
                )
        except Exception as e:
            print(f"Error ensuring initial admin: {e}")

    def gen(self, callback: str, btn_group: str = "btn") -> str:
        return self.service_name.casefold().strip() + "$" + btn_group.casefold().strip() + ">" + callback.casefold().strip()

    @staticmethod
    def validate_username(username: str) -> tuple[bool, str]:
        if not username:
            return False, "Username cannot be empty."
        if not Admin.USERNAME_PATTERN.match(username):
            return False, "Username must be 3-30 characters, only letters, numbers, and underscores allowed."
        return True, ""

    @staticmethod
    def validate_password(password: str) -> tuple[bool, str]:
        if not password:
            return False, "Password cannot be empty."
        if not Admin.PASSWORD_PATTERN.match(password):
            return False, "Password must be exactly 4 digits (0-9)."
        return True, ""

    async def _get_role_by_username(self, username: str) -> Role | None:
        try:
            return await sync_to_async(
                lambda: Role.objects.filter(username__iexact=username, is_active=True).first()
            )()
        except Exception as e:
            print(f"Error fetching role: {e}")
            return None

    async def _get_role_by_tgid(self, tg_id: str) -> Role | None:
        if not tg_id:
            return None
        try:
            return await sync_to_async(
                lambda: Role.objects.filter(tg_id=str(tg_id), is_active=True).first()
            )()
        except Exception as e:
            print(f"Error fetching role by tg_id: {e}")
            return None

    async def _get_role_for_login(self, tg_id: str, username: str | None) -> Role | None:
        """
        SECURITY (Case 1 fix): authenticate by the immutable Telegram user ID first.
        Usernames are mutable/reusable, so they are only used as a one-time "claim"
        mechanism for roles that were created by an admin and have never logged in yet
        (i.e. tg_id is still unset). Once a role has a bound tg_id, username is purely
        display metadata and can no longer be used to reach that role.
        """
        role = await self._get_role_by_tgid(str(tg_id))
        if role:
            return role
        if username:
            candidate = await self._get_role_by_username(username)
            if candidate and not candidate.tg_id:
                return candidate
        return None

    async def _get_authenticated_role(self, state: FSMContext) -> Role | None:
        data = await state.get_data()
        role_id = data.get('authenticated_role_id')
        if not role_id:
            return None
        try:
            return await sync_to_async(
                lambda: Role.objects.filter(id=role_id, is_active=True).first()
            )()
        except Exception:
            return None

    async def _is_authenticated(self, state: FSMContext) -> bool:
        role = await self._get_authenticated_role(state)
        return role is not None

    async def _can_toggle_services(self, state: FSMContext) -> bool:
        role = await self._get_authenticated_role(state)
        if not role:
            return False
        return role.can_toggle_services()

    async def _can_manage_roles(self, state: FSMContext) -> bool:
        role = await self._get_authenticated_role(state)
        if not role:
            return False
        return role.can_manage_roles()

    async def _log_activity(self, tg_id: str, username: str, activity_type: str, metadata: dict = None):
        try:
            await BotActivityLog.objects.acreate(
                session_id=str(uuid.uuid4()),
                tg_id=tg_id,
                username=username,
                ca_number=None,
                activity_type=activity_type,
                metadata=metadata or {}
            )
        except Exception as e:
            print(f"Logging {activity_type} failed: {e}")

    async def _load_services_status(self) -> dict:
        try:
            if not os.path.exists(self.services_status_path):
                data = {}
                with open(self.services_status_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return data
            with open(self.services_status_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading services_status.json: {e}")
            return {}

    async def _save_services_status(self, data: dict) -> None:
        try:
            with open(self.services_status_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving services_status.json: {e}")

    async def _get_today_bounds(self):
        now = datetime.now(ZoneInfo("Africa/Nairobi"))
        start = datetime(year=now.year, month=now.month, day=now.day, tzinfo=now.tzinfo)
        end = start + timedelta(days=1)
        return start, end

    async def _format_main_menu_text(self) -> str:
        start, end = await self._get_today_bounds()
        day_str = start.strftime("%A, %d %B %Y")
        try:
            successful_count = await sync_to_async(lambda: BotActivityLog.objects.filter(
                activity_type=ActivityType.SuccessfulMeterReadingSubmission,
                timestamp__gte=start,
                timestamp__lt=end,
            ).count())()
            abuse_count = await sync_to_async(lambda: BotActivityLog.objects.filter(
                activity_type=ActivityType.TooManyRequests,
                timestamp__gte=start,
                timestamp__lt=end,
            ).count())()
            active_users = await sync_to_async(lambda: BotActivityLog.objects.filter(
                timestamp__gte=start,
                timestamp__lt=end,
            ).values_list('tg_id', flat=True).distinct().count())()
        except Exception as e:
            print(f"Error fetching admin main menu stats: {e}")
            successful_count = 0
            abuse_count = 0
            active_users = 0

        services_status = await self._load_services_status()
        active_count = disabled_count = inactive_count = 0
        for info in services_status.values():
            status = str(info.get('status', 'active')).casefold()
            if status == 'active':
                active_count += 1
            elif status == 'disabled':
                disabled_count += 1
            elif status == 'inactive':
                inactive_count += 1

        text = (
            "🔐 *Admin Panel*\n"
            f"📅 {day_str}\n\n"
            f"📥 Meter Reading Submissions: *{successful_count}*\n"
            f"⚠️ Potential Abuse Cases: *{abuse_count}*\n"
            f"👥 Active Users (Today): *{active_users}*\n\n"
            f"All services status:\n"
            f"✅ Active {active_count}  ⚠️ Disabled {disabled_count}  ⛔️ Inactive {inactive_count}"
        )
        return text

    def _main_menu_keyboard(self) -> InlineKeyboardMarkup:
        kb = [
            [InlineKeyboardButton(text="📊 Last 7 Days Summary", callback_data=self.gen("7days", btn_group="nav"))],
            [InlineKeyboardButton(text="⚙️ Services", callback_data=self.gen("services", btn_group="nav"))],
            [InlineKeyboardButton(text="👥 Roles", callback_data=self.gen("roles", btn_group="nav"))],
            [InlineKeyboardButton(text="🛡️ Block Settings", callback_data=self.gen("block", btn_group="nav"))],
            [InlineKeyboardButton(text="📋 Logs", callback_data=self.gen("logs", btn_group="nav"))],
            [InlineKeyboardButton(text="🔑 Change Password", callback_data=self.gen("change_password", btn_group="nav"))],
            [InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="nav"))],
        ]
        return InlineKeyboardMarkup(inline_keyboard=kb)

    def _summary_keyboard(self) -> InlineKeyboardMarkup:
        kb = [
            [InlineKeyboardButton(text="🔄 Refresh", callback_data=self.gen("7days:refresh", btn_group="summary"))],
            [InlineKeyboardButton(text="📅 Custom Date Range", callback_data=self.gen("7days:custom", btn_group="summary"))],
            [InlineKeyboardButton(text="🏠 Home", callback_data=self.gen("home", btn_group="summary")),
             InlineKeyboardButton(text="🔙 Back", callback_data=self.gen("back", btn_group="summary")),
             InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="summary"))],
        ]
        return InlineKeyboardMarkup(inline_keyboard=kb)

    def _format_status_display(self, status: str, readonly: bool = False) -> str:
        if status == "active":
            return "Active ☑️" if readonly else "Active ✅"
        if status == "disabled":
            return "Disabled ⚠️"
        if status in ("inactive", "deleted"):
            return "Inactive ❌"
        return status.capitalize()

    def _services_keyboard(self, services_status: dict, readonly: bool = False) -> InlineKeyboardMarkup:
        rows = []
        for key, info in services_status.items():
            status = info.get('status', 'active')
            label = info.get('label') or key.replace('_', ' ').title()
            status_text = self._format_status_display(status, readonly=readonly)
            
            if readonly:
                # Use a "noop" callback that shows permission denied
                service_button = InlineKeyboardButton(
                    text=label,
                    callback_data=self.gen("services:noperm", btn_group="services")
                )
                status_button = InlineKeyboardButton(
                    text=status_text,
                    callback_data=self.gen("services:noperm", btn_group="services")
                )
            else:
                service_button = InlineKeyboardButton(
                    text=label,
                    callback_data=self.gen(f"toggle:{key}", btn_group="services")
                )
                status_button = InlineKeyboardButton(
                    text=status_text,
                    callback_data=self.gen(f"toggle:{key}", btn_group="services")
                )
            rows.append([service_button, status_button])
        rows.append([
            InlineKeyboardButton(text="🏠 Home", callback_data=self.gen("home", btn_group="services")),
            InlineKeyboardButton(text="🔙 Back", callback_data=self.gen("back", btn_group="services")),
            InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="services")),
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def _toggle_options_keyboard(self, service_key: str) -> InlineKeyboardMarkup:
        kb = [
            [InlineKeyboardButton(text="Set Active ✅", callback_data=self.gen(f"toggle:{service_key}:active", btn_group="toggle"))],
            [InlineKeyboardButton(text="Set Disabled ⚠️", callback_data=self.gen(f"toggle:{service_key}:disabled", btn_group="toggle"))],
            [InlineKeyboardButton(text="Set Inactive ❌", callback_data=self.gen(f"toggle:{service_key}:inactive", btn_group="toggle"))],
            [
                InlineKeyboardButton(text="🏠 Home", callback_data=self.gen("home", btn_group="toggle")),
                InlineKeyboardButton(text="🔙 Back", callback_data=self.gen("services", btn_group="nav")),
                InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="toggle")),
            ],
        ]
        return InlineKeyboardMarkup(inline_keyboard=kb)

    def _toggle_confirm_keyboard(self) -> InlineKeyboardMarkup:
        kb = [
            [InlineKeyboardButton(text="Save", callback_data=self.gen("toggle:save", btn_group="toggle"))],
            [InlineKeyboardButton(text="Cancel", callback_data=self.gen("toggle:cancel", btn_group="toggle"))],
            [InlineKeyboardButton(text="🏠 Home", callback_data=self.gen("home", btn_group="toggle")),
             InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="toggle"))],
        ]
        return InlineKeyboardMarkup(inline_keyboard=kb)

    def _roles_keyboard(self, roles: list, current_role: Role) -> InlineKeyboardMarkup:
        rows = []
        for role in roles:
            icon = "🔴" if role.role == RoleType.ADMIN else "🟢"
            role_label = "Admin" if role.role == RoleType.ADMIN else "Mod"
            can_remove = False
            # Only show remove button if user has manage_roles permission
            if current_role.can_manage_roles():
                if current_role.is_admin() and role.id != current_role.id:
                    can_remove = True
                elif current_role.is_moderator() and role.is_moderator() and role.id != current_role.id:
                    can_remove = True
            
            user_btn = InlineKeyboardButton(
                text=f"{icon} @{role.username} ({role_label})",
                callback_data=self.gen(f"role:view:{role.id}", btn_group="roles")
            )
            if can_remove:
                remove_btn = InlineKeyboardButton(
                    text="❌",
                    callback_data=self.gen(f"role:remove:{role.id}", btn_group="roles")
                )
                rows.append([user_btn, remove_btn])
            else:
                rows.append([user_btn])
        
        if current_role.can_manage_roles():
            rows.append([InlineKeyboardButton(text="➕ Add Role", callback_data=self.gen("role:add", btn_group="roles"))])
        
        rows.append([
            InlineKeyboardButton(text="🏠 Home", callback_data=self.gen("home", btn_group="roles")),
            InlineKeyboardButton(text="🔙 Back", callback_data=self.gen("back", btn_group="roles")),
            InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="roles")),
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def _role_type_keyboard(self, current_role: Role) -> InlineKeyboardMarkup:
        kb = []
        if current_role.is_admin():
            kb.append([InlineKeyboardButton(text="🔴 Admin", callback_data=self.gen("role:type:admin", btn_group="roles"))])
        kb.append([InlineKeyboardButton(text="🟢 Moderator", callback_data=self.gen("role:type:moderator", btn_group="roles"))])
        kb.append([
            InlineKeyboardButton(text="🏠 Home", callback_data=self.gen("home", btn_group="roles")),
            InlineKeyboardButton(text="🔙 Cancel", callback_data=self.gen("roles", btn_group="nav")),
            InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="roles")),
        ])
        return InlineKeyboardMarkup(inline_keyboard=kb)

    def _role_permissions_keyboard(self, permissions: dict) -> InlineKeyboardMarkup:
        toggle_services = permissions.get('can_toggle_services', False)
        manage_roles = permissions.get('can_manage_roles', False)
        
        kb = [
            [InlineKeyboardButton(
                text=f"{'✅' if toggle_services else '❌'} Service Enable/Disable",
                callback_data=self.gen("role:perm:toggle_services", btn_group="roles")
            )],
            [InlineKeyboardButton(
                text=f"{'✅' if manage_roles else '❌'} Manage Roles",
                callback_data=self.gen("role:perm:manage_roles", btn_group="roles")
            )],
            [InlineKeyboardButton(text="✅ Save Role", callback_data=self.gen("role:save", btn_group="roles"))],
            [InlineKeyboardButton(text="🏠 Home", callback_data=self.gen("home", btn_group="roles")),
             InlineKeyboardButton(text="🔙 Cancel", callback_data=self.gen("roles", btn_group="nav")),
             InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="roles"))],
        ]
        return InlineKeyboardMarkup(inline_keyboard=kb)

    def _edit_permissions_keyboard(self, target_role: Role) -> InlineKeyboardMarkup:
        """Keyboard for editing existing role permissions."""
        toggle_services = target_role.can_toggle_services()
        manage_roles = target_role.can_manage_roles()
        
        kb = [
            [InlineKeyboardButton(
                text=f"{'✅' if toggle_services else '❌'} Service Enable/Disable",
                callback_data=self.gen(f"role:toggleperm:{target_role.id}:toggle_services", btn_group="roles")
            )],
            [InlineKeyboardButton(
                text=f"{'✅' if manage_roles else '❌'} Manage Roles",
                callback_data=self.gen(f"role:toggleperm:{target_role.id}:manage_roles", btn_group="roles")
            )],
            [InlineKeyboardButton(text="🔙 Back to Role", callback_data=self.gen(f"role:view:{target_role.id}", btn_group="roles"))],
            [InlineKeyboardButton(text="🏠 Home", callback_data=self.gen("home", btn_group="roles")),
             InlineKeyboardButton(text="🔙 Roles", callback_data=self.gen("roles", btn_group="nav")),
             InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="roles"))],
        ]
        return InlineKeyboardMarkup(inline_keyboard=kb)

    def setup_handlers(self):
        @self.router.message(Command("admin"))
        async def admin_command(message: Message, state: FSMContext):
            await state.clear()
            
            # SECURITY (Case 1 fix): resolve the role by the immutable Telegram user ID
            # first; username is only used as a one-time claim path for roles that have
            # never logged in before (tg_id still unset).
            tg_id = str(message.from_user.id)
            tg_username = message.from_user.username

            role = await self._get_role_for_login(tg_id, tg_username)
            if not role:
                await self._log_activity(
                    str(message.from_user.id),
                    tg_username or '',
                    ActivityType.AdminLoginFailed,
                    {'attempted_username': tg_username, 'reason': 'unauthorized'}
                )
                await message.answer("❌ Unauthorized. You don't have admin access.")
                return

            if role.is_locked():
                await self._log_activity(
                    str(message.from_user.id),
                    role.username,
                    ActivityType.AdminLoginFailed,
                    {'attempted_username': tg_username, 'reason': 'locked_out'}
                )
                await message.answer("❌ This account is temporarily locked due to repeated failed attempts. Try again later.")
                return

            # Remember the role by ID (not username) for the password step.
            await state.update_data(login_role_id=role.id)
            await state.set_state(AdminStatesGroup.login_password)
            await message.answer(
                f"🔐 *Admin Login*\n\n"
                f"Welcome, *@{role.username}*\n\n"
                f"🔑 Enter your PIN:",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove()
            )

        @self.router.message(AdminStatesGroup.login_password)
        async def handle_login_password(message: Message, state: FSMContext):
            password = (message.text or '').strip()
            valid, error_msg = self.validate_password(password)
            if not valid:
                await message.answer(f"❌ {error_msg}\n\nPlease try again:")
                return

            data = await state.get_data()
            role_id = data.get('login_role_id')
            role = None
            if role_id:
                role = await sync_to_async(lambda: Role.objects.filter(id=role_id, is_active=True).first())()

            if not role:
                await message.answer("Session expired. Use /admin to login again.")
                return

            if role.is_locked():
                await message.answer("❌ This account is temporarily locked due to repeated failed attempts. Try again later.")
                return

            # SECURITY (Case 2 fix): verify against the hashed PIN, never compare plaintext.
            if not role.verify_password(password):
                role.register_failed_attempt()
                await sync_to_async(role.save)()
                await self._log_activity(
                    str(message.from_user.id),
                    message.from_user.username or '',
                    ActivityType.AdminLoginFailed,
                    {'attempted_username': role.username, 'reason': 'wrong_password'}
                )
                await message.answer("❌ Invalid password. Try again:")
                return

            role.reset_failed_attempts()

            # SECURITY (Case 1 fix): bind this role to the Telegram ID that just proved
            # ownership of the PIN. From now on this role can only be reached via tg_id.
            if not role.tg_id:
                role.tg_id = str(message.from_user.id)
            await sync_to_async(role.save)()

            await state.update_data(authenticated_role_id=role.id)
            await self._log_activity(
                str(message.from_user.id),
                role.username,
                ActivityType.AdminLogin,
                {'role': role.role, 'tg_username': message.from_user.username}
            )

            if role.must_change_password:
                await state.set_state(AdminStatesGroup.change_password)
                await message.answer(
                    "⚠️ This is a bootstrap/reset account. You must set a new PIN before continuing.\n\n"
                    "🔑 Enter a new 4-digit PIN:"
                )
                return

            await state.set_state(AdminStatesGroup.main)
            text = await self._format_main_menu_text()
            welcome = f"✅ Welcome, *@{role.username}* ({role.role.title()})!\n\n"
            await message.answer(welcome + text, reply_markup=self._main_menu_keyboard(), parse_mode="Markdown")

        service_name = self.service_name

        @self.router.callback_query(
            lambda call: isinstance(call.data, str)
            and ('$' in call.data)
            and (FromGen.get_service(call.data) == service_name)
            and (FromGen.get_btnGroup(call.data) != 'date')
        )
        async def admin_callbacks(call: CallbackQuery, state: FSMContext):
            if not await self._is_authenticated(state):
                await call.answer("Session expired. Use /admin to login.", show_alert=True)
                return

            raw = call.data
            try:
                cb = FromGen.get_callData(raw)
                btn_group = FromGen.get_btnGroup(raw)
            except Exception as e:
                print(f"Error parsing admin callback: {e}")
                await call.answer()
                return

            parts = cb.split(':')

            if cb == 'exit':
                await state.clear()
                await call.message.edit_text("👋 Logged out of admin panel.")
                await call.answer()
                return

            if cb == 'back' or cb == 'home':
                await state.set_state(AdminStatesGroup.main)
                text = await self._format_main_menu_text()
                await call.message.edit_text(text, reply_markup=self._main_menu_keyboard(), parse_mode="Markdown")
                await call.answer()
                return

            if cb in {'7days', '7days:refresh'}:
                await state.set_state(AdminStatesGroup.summary)
                await self._handle_7days_summary(call, state)
                return

            if cb == '7days:custom':
                await state.set_state(AdminStatesGroup.summary)
                await state.update_data(summary_mode='custom_range', summary_step='start', custom_start_date=None)
                year, month = self.calendar_module.get_today_gregorian_date()
                calendar_markup = self.calendar_module.create_gregorian_calendar(year, month)
                await call.message.edit_text(
                    "📅 Select *start date*:",
                    reply_markup=calendar_markup,
                    parse_mode="Markdown"
                )
                await call.answer()
                return

            if cb == 'services':
                can_toggle = await self._can_toggle_services(state)
                await state.set_state(AdminStatesGroup.services)
                await self._handle_services_menu(call, state, readonly=not can_toggle)
                return
            
            if cb == 'services:noperm':
                await call.answer("🚫 You don't have permission to toggle services.", show_alert=True)
                return

            if cb == 'roles':
                await self._handle_roles_menu(call, state)
                return

            if cb == 'block':
                await call.message.edit_text(
                    "Block settings: Coming soon",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🏠 Home", callback_data=self.gen("home", btn_group="nav")),
                             InlineKeyboardButton(text="🔙 Back", callback_data=self.gen("back", btn_group="nav")),
                             InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="nav"))],
                        ]
                    ),
                )
                await call.answer()
                return

            if cb == 'logs':
                await call.message.edit_text(
                    "Logs viewer: Coming soon",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🏠 Home", callback_data=self.gen("home", btn_group="nav")),
                             InlineKeyboardButton(text="🔙 Back", callback_data=self.gen("back", btn_group="nav")),
                             InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="nav"))],
                        ]
                    ),
                )
                await call.answer()
                return

            if cb == 'change_password':
                current_role = await self._get_authenticated_role(state)
                if not current_role:
                    await call.answer("Session expired", show_alert=True)
                    return
                await state.set_state(AdminStatesGroup.change_password)
                await call.message.edit_text(
                    f"🔑 *Change Password*\n\n"
                    f"Current user: *@{current_role.username}*\n\n"
                    f"Enter your new 4-digit PIN:",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🏠 Home", callback_data=self.gen("home", btn_group="nav")),
                             InlineKeyboardButton(text="🔙 Cancel", callback_data=self.gen("back", btn_group="nav")),
                             InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="nav"))],
                        ]
                    ),
                    parse_mode="Markdown"
                )
                await call.answer()
                return

            if parts[0] == 'toggle':
                await self._handle_toggle_callback(call, state, cb)
                return

            if parts[0] == 'role':
                await self._handle_role_callback(call, state, cb)
                return

            await call.answer()

        @self.router.message(AdminStatesGroup.set_message)
        async def set_toggle_message(message: Message, state: FSMContext):
            if not await self._is_authenticated(state):
                await message.answer("Session expired. Use /admin to login.")
                return
            text = message.text or ''
            if text.strip() == '-':
                text = ''
            await state.update_data(toggle_user_message=text)
            await message.answer(
                "Message captured. Use the buttons to Save or Cancel.",
                reply_markup=self._toggle_confirm_keyboard(),
            )

        @self.router.message(AdminStatesGroup.change_password)
        async def handle_change_password(message: Message, state: FSMContext):
            if not await self._is_authenticated(state):
                await message.answer("Session expired. Use /admin to login.")
                return
            
            new_password = (message.text or '').strip()
            valid, error_msg = self.validate_password(new_password)
            if not valid:
                await message.answer(
                    f"❌ {error_msg}\n\nPlease enter a valid 4-digit PIN:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🏠 Home", callback_data=self.gen("home", btn_group="nav")),
                         InlineKeyboardButton(text="🔙 Cancel", callback_data=self.gen("back", btn_group="nav")),
                         InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="nav"))],
                    ])
                )
                return
            
            current_role = await self._get_authenticated_role(state)
            if not current_role:
                await message.answer("Session expired. Use /admin to login.")
                return
            
            # Don't allow reusing the current password
            if current_role.verify_password(new_password):
                await message.answer(
                    "❌ New PIN cannot be the same as your current PIN. Please choose a different one:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🏠 Home", callback_data=self.gen("home", btn_group="nav")),
                         InlineKeyboardButton(text="🔙 Cancel", callback_data=self.gen("back", btn_group="nav")),
                         InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="nav"))],
                    ])
                )
                return
            
            # SECURITY (Case 2 fix): store only the hash, never the raw PIN.
            current_role.set_password(new_password)
            current_role.must_change_password = False
            await sync_to_async(current_role.save)()
            
            await self._log_activity(
                str(message.from_user.id),
                current_role.username,
                ActivityType.PermissionChanged,
                {'action': 'password_changed'}
            )
            
            await state.set_state(AdminStatesGroup.main)
            text = await self._format_main_menu_text()
            await message.answer(
                f"✅ Password changed successfully!\n\n{text}",
                reply_markup=self._main_menu_keyboard(),
                parse_mode="Markdown"
            )

        @self.router.message(AdminStatesGroup.role_add_username)
        async def handle_role_add_username(message: Message, state: FSMContext):
            if not await self._is_authenticated(state):
                await message.answer("Session expired. Use /admin to login.")
                return
            
            username = (message.text or '').strip()
            valid, error_msg = self.validate_username(username)
            if not valid:
                await message.answer(f"❌ {error_msg}\n\nPlease try again:")
                return
            
            existing = await self._get_role_by_username(username)
            if existing:
                await message.answer("❌ Username already exists. Please choose another:")
                return
            
            await state.update_data(new_role_username=username)
            await state.set_state(AdminStatesGroup.role_add_password)
            await message.answer(
                f"Username: *@{username}*\n\n🔑 Enter a 4-digit PIN for this user:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Home", callback_data=self.gen("home", btn_group="roles")),
                     InlineKeyboardButton(text="🔙 Cancel", callback_data=self.gen("roles", btn_group="nav")),
                     InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="roles"))],
                ]),
                parse_mode="Markdown"
            )

        @self.router.message(AdminStatesGroup.role_add_password)
        async def handle_role_add_password(message: Message, state: FSMContext):
            if not await self._is_authenticated(state):
                await message.answer("Session expired. Use /admin to login.")
                return
            
            password = (message.text or '').strip()
            valid, error_msg = self.validate_password(password)
            if not valid:
                await message.answer(f"❌ {error_msg}\n\nPlease try again:")
                return
            
            await state.update_data(new_role_password=password)
            
            current_role = await self._get_authenticated_role(state)
            if not current_role:
                await message.answer("Session expired. Use /admin to login.")
                return
            
            await state.set_state(AdminStatesGroup.role_add_type)
            data = await state.get_data()
            username = data.get('new_role_username')
            await message.answer(
                f"Username: *@{username}*\nPIN: ****\n\nSelect role type:",
                reply_markup=self._role_type_keyboard(current_role),
                parse_mode="Markdown"
            )

    async def _handle_7days_summary(self, call: CallbackQuery, state: FSMContext):
        now = datetime.now(ZoneInfo("Africa/Nairobi"))
        start = now - timedelta(days=7)
        end = now
        try:
            meter_exists = await sync_to_async(lambda: BotActivityLog.objects.filter(
                activity_type=ActivityType.MeterReadingExists,
                timestamp__gte=start,
                timestamp__lte=end,
            ).count())()
            deadline_closed = await sync_to_async(lambda: BotActivityLog.objects.filter(
                activity_type=ActivityType.DeadlineClosed,
                timestamp__gte=start,
                timestamp__lte=end,
            ).count())()
            wrong_region = await sync_to_async(lambda: BotActivityLog.objects.filter(
                activity_type=ActivityType.RegionNotAllowed,
                timestamp__gte=start,
                timestamp__lte=end,
            ).count())()
            submissions = await sync_to_async(lambda: BotActivityLog.objects.filter(
                activity_type=ActivityType.SuccessfulMeterReadingSubmission,
                timestamp__gte=start,
                timestamp__lte=end,
            ).count())()
            abuse = await sync_to_async(lambda: BotActivityLog.objects.filter(
                activity_type=ActivityType.TooManyRequests,
                timestamp__gte=start,
                timestamp__lte=end,
            ).count())()
        except Exception as e:
            print(f"Error fetching 7-day summary: {e}")
            meter_exists = deadline_closed = wrong_region = submissions = abuse = 0

        start_date = start.date()
        end_date = end.date()
        month_start = start_date.strftime("%b")
        month_end = end_date.strftime("%b")
        if month_start == month_end:
            date_range_str = f"{month_start} {start_date.day}–{end_date.day}, {end_date.year}"
        else:
            date_range_str = f"{month_start} {start_date.day} – {month_end} {end_date.day}, {end_date.year}"

        text = (
            f"🔔 *Weekly Alert Summary* ({date_range_str})\n\n"
            f"🟢 *Normal Activity*\n"
            f"• Meter Readings: {meter_exists}\n"
            f"• Submissions: {submissions}\n\n"
            f"🔴 *Needs Attention*\n"
            f"• Potential Abuse Cases: **{abuse}**\n\n"
            f"⚪ *Zero Activity*\n"
            f"• Closed Deadlines: {deadline_closed}\n"
            f"• Wrong Region: {wrong_region}"
        )

        await call.message.edit_text(text, reply_markup=self._summary_keyboard(), parse_mode="Markdown")
        await call.answer()

    async def _handle_calendar_date(self, call: CallbackQuery, state: FSMContext, selected_date: str):
        if not await self._is_authenticated(state):
            await call.answer("Session expired", show_alert=True)
            return

        data = await state.get_data()
        mode = data.get('summary_mode')
        if mode != 'custom_range':
            return

        step = data.get('summary_step', 'start')

        if step == 'start':
            await state.update_data(custom_start_date=selected_date, summary_step='end')
            try:
                start_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
                year, month = start_date.year, start_date.month
            except Exception:
                year, month = self.calendar_module.get_today_gregorian_date()

            calendar_markup = self.calendar_module.create_gregorian_calendar(year, month)
            await call.message.edit_text(
                f"📅 Start date: {selected_date}\n\nSelect *end date*:",
                reply_markup=calendar_markup,
                parse_mode="Markdown"
            )
            await call.answer()
            return

        if step == 'end':
            start_str = data.get('custom_start_date')
            if not start_str:
                await state.update_data(custom_start_date=selected_date, summary_step='end')
                await call.answer()
                return

            try:
                start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
                end_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
            except Exception as e:
                print(f"Error parsing custom range dates: {e}")
                await call.answer("Invalid date.", show_alert=True)
                return

            if end_date < start_date:
                await call.answer("End date cannot be before start date.", show_alert=True)
                return

            tz = ZoneInfo("Africa/Nairobi")
            start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=tz)
            end_dt = datetime(end_date.year, end_date.month, end_date.day, tzinfo=tz) + timedelta(days=1)

            try:
                meter_exists = await sync_to_async(lambda: BotActivityLog.objects.filter(
                    activity_type=ActivityType.MeterReadingExists,
                    timestamp__gte=start_dt,
                    timestamp__lt=end_dt,
                ).count())()
                deadline_closed = await sync_to_async(lambda: BotActivityLog.objects.filter(
                    activity_type=ActivityType.DeadlineClosed,
                    timestamp__gte=start_dt,
                    timestamp__lt=end_dt,
                ).count())()
                wrong_region = await sync_to_async(lambda: BotActivityLog.objects.filter(
                    activity_type=ActivityType.RegionNotAllowed,
                    timestamp__gte=start_dt,
                    timestamp__lt=end_dt,
                ).count())()
                submissions = await sync_to_async(lambda: BotActivityLog.objects.filter(
                    activity_type=ActivityType.SuccessfulMeterReadingSubmission,
                    timestamp__gte=start_dt,
                    timestamp__lt=end_dt,
                ).count())()
                abuse = await sync_to_async(lambda: BotActivityLog.objects.filter(
                    activity_type=ActivityType.TooManyRequests,
                    timestamp__gte=start_dt,
                    timestamp__lt=end_dt,
                ).count())()
            except Exception as e:
                print(f"Error fetching custom summary: {e}")
                meter_exists = deadline_closed = wrong_region = submissions = abuse = 0

            header_range = f"{start_date.isoformat()} to {end_date.isoformat()}"
            text = (
                f"*Custom Summary*\n"
                f"{header_range}\n\n"
                "| Metric | Count |\n"
                "| --- | --- |\n"
                f"| Meter Reading Exists | {meter_exists} |\n"
                f"| Deadline Closed | {deadline_closed} |\n"
                f"| Wrong Region | {wrong_region} |\n"
                f"| Meter Reading Submissions | {submissions} |\n"
                f"| Potential Abuse Cases | {abuse} |\n"
            )

            await state.update_data(summary_step=None)
            await call.message.edit_text(text, reply_markup=self._summary_keyboard(), parse_mode="Markdown")
            await call.answer()

    async def _handle_services_menu(self, call: CallbackQuery, state: FSMContext, readonly: bool = False):
        services_status = await self._load_services_status()
        lines = []
        for key, info in services_status.items():
            label = info.get('label') or key.replace('_', ' ').title()
            status = info.get('status', 'active')
            status_text = self._format_status_display(status, readonly=readonly)
            message = info.get('message', '')
            line = f"*{label}*: {status_text}"
            if message:
                line += f" — {message}"
            lines.append(line)
        
        header = "*Services*"
        if readonly:
            header += " _(view only)_"
        text = header + "\n\n" + "\n".join(lines)
        await call.message.edit_text(text, reply_markup=self._services_keyboard(services_status, readonly=readonly), parse_mode="Markdown")
        await call.answer()

    async def _handle_roles_menu(self, call: CallbackQuery, state: FSMContext):
        current_role = await self._get_authenticated_role(state)
        if not current_role:
            await call.answer("Session expired", show_alert=True)
            return
        
        await state.set_state(AdminStatesGroup.roles)
        roles = await sync_to_async(lambda: list(Role.objects.filter(is_active=True).order_by('-role', 'username')))()
        
        admin_count = sum(1 for r in roles if r.role == RoleType.ADMIN)
        mod_count = sum(1 for r in roles if r.role == RoleType.MODERATOR)
        
        text = (
            "👥 *Role Management*\n\n"
            f"🔴 Admins: {admin_count}\n"
            f"🟢 Moderators: {mod_count}\n\n"
            "Select a user to view details or remove:"
        )
        
        await call.message.edit_text(text, reply_markup=self._roles_keyboard(roles, current_role), parse_mode="Markdown")
        await call.answer()

    async def _handle_role_callback(self, call: CallbackQuery, state: FSMContext, cb: str):
        parts = cb.split(':')
        current_role = await self._get_authenticated_role(state)
        if not current_role:
            await call.answer("Session expired", show_alert=True)
            return

        # role:add
        if cb == 'role:add':
            if not current_role.can_manage_roles():
                await call.answer("You don't have permission to add roles.", show_alert=True)
                return
            await state.set_state(AdminStatesGroup.role_add_username)
            await call.message.edit_text(
                "➕ *Add New Role*\n\n"
                "Enter username for the new user:\n"
                "_(3-30 characters, letters, numbers, underscores only)_",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Home", callback_data=self.gen("home", btn_group="roles")),
                     InlineKeyboardButton(text="🔙 Cancel", callback_data=self.gen("roles", btn_group="nav")),
                     InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="roles"))],
                ]),
                parse_mode="Markdown"
            )
            await call.answer()
            return

        # role:type:admin or role:type:moderator
        if len(parts) == 3 and parts[1] == 'type':
            role_type = parts[2]
            if role_type == 'admin' and not current_role.is_admin():
                await call.answer("Only admins can create admin roles.", show_alert=True)
                return
            
            await state.update_data(new_role_type=role_type)
            
            # For moderators, show permissions screen
            if role_type == 'moderator':
                await state.set_state(AdminStatesGroup.role_add_permissions)
                await state.update_data(new_role_permissions={'can_toggle_services': False, 'can_manage_roles': False})
                data = await state.get_data()
                await call.message.edit_text(
                    f"Username: *@{data.get('new_role_username')}*\n"
                    f"Role: 🟢 Moderator\n\n"
                    "Set permissions:",
                    reply_markup=self._role_permissions_keyboard(data.get('new_role_permissions', {})),
                    parse_mode="Markdown"
                )
            else:
                # Admin gets all permissions, save directly
                await self._save_new_role(call, state, current_role)
            await call.answer()
            return

        # role:perm:toggle_services or role:perm:manage_roles
        if len(parts) == 3 and parts[1] == 'perm':
            perm_key = parts[2]
            data = await state.get_data()
            permissions = data.get('new_role_permissions', {})
            
            if perm_key == 'toggle_services':
                permissions['can_toggle_services'] = not permissions.get('can_toggle_services', False)
            elif perm_key == 'manage_roles':
                permissions['can_manage_roles'] = not permissions.get('can_manage_roles', False)
            
            await state.update_data(new_role_permissions=permissions)
            await call.message.edit_reply_markup(reply_markup=self._role_permissions_keyboard(permissions))
            await call.answer()
            return

        # role:save
        if cb == 'role:save':
            await self._save_new_role(call, state, current_role)
            await call.answer()
            return

        # role:remove:ID
        if len(parts) == 3 and parts[1] == 'remove':
            role_id = int(parts[2])
            target_role = await sync_to_async(lambda: Role.objects.filter(id=role_id).first())()
            
            if not target_role:
                await call.answer("Role not found.", show_alert=True)
                return
            
            # Cannot remove yourself
            if target_role.id == current_role.id:
                await call.answer("You cannot remove yourself.", show_alert=True)
                return
            
            # Permission checks based on role types
            if target_role.is_admin():
                # Only admins with manage_roles permission can remove admins
                if not current_role.is_admin():
                    await call.answer("Only admins can remove admin roles.", show_alert=True)
                    return
                if not current_role.can_manage_roles():
                    await call.answer("You don't have permission to remove roles.", show_alert=True)
                    return
                # Check if this is the last admin
                admin_count = await sync_to_async(lambda: Role.objects.filter(role=RoleType.ADMIN, is_active=True).count())()
                if admin_count <= 1:
                    await call.answer("Cannot remove the last admin. At least one admin must remain.", show_alert=True)
                    return
            else:
                # Moderators can only be removed by users with manage_roles permission
                if not current_role.can_manage_roles():
                    await call.answer("You don't have permission to remove roles.", show_alert=True)
                    return
                # Moderators can only remove other moderators, not admins
                if current_role.is_moderator() and target_role.is_admin():
                    await call.answer("Moderators cannot remove admins.", show_alert=True)
                    return
            
            # Deactivate the role
            target_role.is_active = False
            await sync_to_async(target_role.save)()
            
            await self._log_activity(
                str(call.from_user.id),
                current_role.username,
                ActivityType.RoleRemoved,
                {'removed_username': target_role.username, 'removed_role': target_role.role}
            )
            
            await call.answer(f"Role @{target_role.username} removed.", show_alert=True)
            await self._handle_roles_menu(call, state)
            return

        # role:view:ID
        if len(parts) == 3 and parts[1] == 'view':
            role_id = int(parts[2])
            target_role = await sync_to_async(lambda: Role.objects.filter(id=role_id).first())()
            
            if not target_role:
                await call.answer("Role not found.", show_alert=True)
                return
            
            icon = "🔴" if target_role.is_admin() else "🟢"
            role_label = "Admin" if target_role.is_admin() else "Moderator"
            
            text = (
                f"{icon} *@{target_role.username}*\n\n"
                f"Role: {role_label}\n"
                f"Telegram ID: {target_role.tg_id or 'Not linked'}\n"
                f"Created: {target_role.created.strftime('%Y-%m-%d')}\n\n"
                f"*Permissions:*\n"
                f"• Service Enable/Disable: {'✅' if target_role.can_toggle_services() else '❌'}\n"
                f"• Manage Roles: {'✅' if target_role.can_manage_roles() else '❌'}"
            )
            
            kb = []
            # Show edit permissions button only for admins with manage_roles permission
            if current_role.is_admin() and current_role.can_manage_roles():
                kb.append([InlineKeyboardButton(
                    text="⚙️ Change Permissions",
                    callback_data=self.gen(f"role:editperm:{target_role.id}", btn_group="roles")
                )])
            
            kb.append([
                InlineKeyboardButton(text="🏠 Home", callback_data=self.gen("home", btn_group="roles")),
                InlineKeyboardButton(text="🔙 Back", callback_data=self.gen("roles", btn_group="nav")),
                InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="roles")),
            ])
            
            await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
            await call.answer()
            return

        # role:editperm:ID - Edit existing role permissions
        if len(parts) == 3 and parts[1] == 'editperm':
            role_id = int(parts[2])
            target_role = await sync_to_async(lambda: Role.objects.filter(id=role_id).first())()
            
            if not target_role:
                await call.answer("Role not found.", show_alert=True)
                return
            
            # Only admins can edit permissions
            if not current_role.is_admin() or not current_role.can_manage_roles():
                await call.answer("Only admins can edit permissions.", show_alert=True)
                return
            
            await state.update_data(editing_role_id=role_id)
            
            await call.message.edit_text(
                f"⚙️ *Edit Permissions for @{target_role.username}*\n\n"
                f"Toggle permissions below:",
                reply_markup=self._edit_permissions_keyboard(target_role),
                parse_mode="Markdown"
            )
            await call.answer()
            return

        # role:toggleperm:ID:perm_key - Toggle a permission for existing role
        if len(parts) == 4 and parts[1] == 'toggleperm':
            role_id = int(parts[2])
            perm_key = parts[3]
            target_role = await sync_to_async(lambda: Role.objects.filter(id=role_id).first())()
            
            if not target_role:
                await call.answer("Role not found.", show_alert=True)
                return
            
            # Only admins can toggle permissions
            if not current_role.is_admin() or not current_role.can_manage_roles():
                await call.answer("Only admins can edit permissions.", show_alert=True)
                return
            
            permissions = target_role.permissions or {}
            
            # Toggle the permission (use current actual value from model method)
            if perm_key == 'toggle_services':
                permissions['can_toggle_services'] = not target_role.can_toggle_services()
            elif perm_key == 'manage_roles':
                permissions['can_manage_roles'] = not target_role.can_manage_roles()
            
            target_role.permissions = permissions
            await sync_to_async(target_role.save)()
            
            # Refresh the role from DB to get updated state
            target_role = await sync_to_async(lambda: Role.objects.filter(id=role_id).first())()
            
            await self._log_activity(
                str(call.from_user.id),
                current_role.username,
                ActivityType.PermissionChanged,
                {'target_username': target_role.username, 'new_permissions': permissions}
            )
            
            # Update the full message to show current permission state
            await call.message.edit_text(
                f"⚙️ *Edit Permissions for @{target_role.username}*\n\n"
                f"Toggle permissions below:\n\n"
                f"• Service Enable/Disable: {'✅' if target_role.can_toggle_services() else '❌'}\n"
                f"• Manage Roles: {'✅' if target_role.can_manage_roles() else '❌'}",
                reply_markup=self._edit_permissions_keyboard(target_role),
                parse_mode="Markdown"
            )
            await call.answer("Permission updated")
            return

    async def _save_new_role(self, call: CallbackQuery, state: FSMContext, current_role: Role):
        data = await state.get_data()
        username = data.get('new_role_username')
        password = data.get('new_role_password')
        role_type = data.get('new_role_type')
        permissions = data.get('new_role_permissions', {})
        
        if role_type == 'admin':
            permissions = {'can_toggle_services': True, 'can_manage_roles': True}
        
        try:
            # SECURITY (Case 2 fix): hash the PIN before persisting it; never store raw.
            def _create_role():
                role = Role(
                    username=username,
                    role=role_type,
                    permissions=permissions,
                    is_active=True,
                    must_change_password=True,
                )
                role.set_password(password)
                role.save()
                return role
            new_role = await sync_to_async(_create_role)()
            
            await self._log_activity(
                str(call.from_user.id),
                current_role.username,
                ActivityType.RoleCreated,
                {'new_username': username, 'new_role': role_type, 'permissions': permissions}
            )
            
            await call.message.edit_text(
                f"✅ Role created successfully!\n\n"
                f"Username: *@{username}*\n"
                f"Role: {'🔴 Admin' if role_type == 'admin' else '🟢 Moderator'}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Home", callback_data=self.gen("home", btn_group="roles")),
                     InlineKeyboardButton(text="🔙 Back", callback_data=self.gen("roles", btn_group="nav")),
                     InlineKeyboardButton(text="🔚 Exit", callback_data=self.gen("exit", btn_group="roles"))],
                ]),
                parse_mode="Markdown"
            )
            
            # Return to roles menu after a moment
            await state.set_state(AdminStatesGroup.roles)
            
        except IntegrityError:
            await call.message.edit_text("❌ Username already exists.")
        except Exception as e:
            print(f"Error creating role: {e}")
            await call.message.edit_text("❌ Error creating role.")

    async def _handle_toggle_callback(self, call: CallbackQuery, state: FSMContext, cb: str):
        # Check permission before any toggle action
        if not await self._can_toggle_services(state):
            await call.answer("You don't have permission to manage services.", show_alert=True)
            return
        
        parts = cb.split(':')

        if len(parts) == 2 and parts[1] in ('save', 'cancel'):
            data = await state.get_data()
            service_key = data.get('toggle_service_key')
            new_status = data.get('toggle_new_status')

            if parts[1] == 'cancel':
                await state.set_state(AdminStatesGroup.services)
                services_status = await self._load_services_status()
                await call.message.edit_text("Cancelled.", reply_markup=self._services_keyboard(services_status))
                await call.answer()
                return

            user_message = data.get('toggle_user_message', '')
            services_status = await self._load_services_status()
            if service_key not in services_status:
                services_status[service_key] = {'status': 'active', 'message': ''}
            services_status[service_key]['status'] = new_status
            services_status[service_key]['message'] = user_message
            await self._save_services_status(services_status)
            
            current_role = await self._get_authenticated_role(state)
            await self._log_activity(
                str(call.from_user.id),
                current_role.username if current_role else str(call.from_user.username),
                ActivityType.ServiceToggled,
                {'service': service_key, 'status': new_status, 'message': user_message}
            )

            await state.set_state(AdminStatesGroup.services)
            lines = []
            for key, info in services_status.items():
                label = info.get('label') or key.replace('_', ' ').title()
                status = info.get('status', 'active')
                status_text = self._format_status_display(status)
                message = info.get('message', '')
                line = f"*{label}*: {status_text}"
                if message:
                    line += f" — {message}"
                lines.append(line)
            text = "*Services*\n\n" + "\n".join(lines)
            await call.message.edit_text(text, reply_markup=self._services_keyboard(services_status), parse_mode="Markdown")
            await call.answer("Saved")
            return

        if len(parts) == 2 and parts[0] == 'toggle':
            service_key = parts[1]
            await state.update_data(toggle_service_key=service_key)
            services_status = await self._load_services_status()
            current = services_status.get(service_key, {}).get('status', 'active')
            label = services_status.get(service_key, {}).get('label') or service_key.replace('_', ' ').title()
            current_display = self._format_status_display(current)
            text = f"Toggle *{label}* (current: {current_display})"
            await call.message.edit_text(text, reply_markup=self._toggle_options_keyboard(service_key), parse_mode="Markdown")
            await state.set_state(AdminStatesGroup.toggle_service)
            await call.answer()
            return

        if len(parts) == 3 and parts[0] == 'toggle':
            service_key = parts[1]
            new_status = parts[2]
            if new_status == 'deleted':
                new_status = 'inactive'
            await state.update_data(toggle_service_key=service_key, toggle_new_status=new_status)
            
            if new_status == 'inactive':
                services_status = await self._load_services_status()
                if service_key in services_status:
                    services_status[service_key]['status'] = 'inactive'
                    services_status[service_key]['message'] = ''
                await self._save_services_status(services_status)
                
                current_role = await self._get_authenticated_role(state)
                await self._log_activity(
                    str(call.from_user.id),
                    current_role.username if current_role else str(call.from_user.username),
                    ActivityType.ServiceToggled,
                    {'service': service_key, 'status': 'inactive', 'message': ''}
                )

                await state.set_state(AdminStatesGroup.services)
                label = services_status.get(service_key, {}).get('label') or service_key.replace('_', ' ').title()
                status_text = self._format_status_display('inactive')
                await call.message.edit_text(f"Service *{label}* set to *{status_text}*.", reply_markup=self._services_keyboard(services_status), parse_mode="Markdown")
                await call.answer("Saved")
                return

            await state.set_state(AdminStatesGroup.set_message)
            await call.message.edit_text(
                f"Current: {self._format_status_display(new_status)}. Send a message to display to users (or '-' for none).",
                reply_markup=self._toggle_confirm_keyboard(),
                parse_mode="Markdown"
            )
            await call.answer()
            return