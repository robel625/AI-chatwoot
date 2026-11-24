import sys
import io
import json
from datetime import datetime, timedelta
from pathlib import Path
from ethiopian_date import EthiopianDateConverter as EDC
import re
import asyncio

# Force UTF-8 encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ============================================================================
# EMBEDDED TARIFF DATA (from tarrif.json)
# Keys cleaned (trailing spaces removed) for reliable lookup
# ============================================================================
# ============================================================================
# MANUAL TEST VARIABLES - EDIT THESE FOR QUICK TESTING
# ============================================================================
TEST_CONFIG = {
    # Customer Info
    'customer_name': "John Doe",
    'ca_number': "100000385214",
    'category': "domestic",  # Options: "domestic" or "commercial"
    # Previous Reading
    'previous_kwh': 14000,
    'previous_reading_date': "25/12/2025",  # Format: DD/MM/YYYY
    # Current Reading
    'current_kwh': 14450,
    'current_reading_date': "24/01/2026"  # Format: DD/MM/YYYY
}

# ============================================================================
TARIFF_DATA = {
    "blocks": {
        "1": {
            "category": "0 - 50 kwh",
            "2017-1": 0.3537, "2017-2": 0.4344, "2017-3": 0.5150, "2017-4": 0.5957,
            "2018-1": 0.6764, "2018-2": 0.7571, "2018-3": 0.8377, "2018-4": 0.9184,
            "2019-1": 0.9991, "2019-2": 1.0798, "2019-3": 1.1604, "2019-4": 1.2411,
            "2020-1": 1.3218, "2020-2": 1.4025, "2020-3": 1.4831, "2020-4": 1.5638
        },
        "2": {
            "category": "51 - 100 kwh",
            "2017-1": 0.9478, "2017-2": 1.1285, "2017-3": 1.3093, "2017-4": 1.4901,
            "2018-1": 1.6708, "2018-2": 1.8516, "2018-3": 2.0324, "2018-4": 2.2131,
            "2019-1": 2.3939, "2019-2": 2.5746, "2019-3": 2.7554, "2019-4": 2.9362,
            "2020-1": 3.1169, "2020-2": 3.2977, "2020-3": 3.4785, "2020-4": 3.6592
        },
        "3": {
            "category": "101 - 200 kwh",
            "2017-1": 1.8864, "2017-2": 2.1478, "2017-3": 2.4092, "2017-4": 2.6706,
            "2018-1": 2.9320, "2018-2": 3.1934, "2018-3": 3.4549, "2018-4": 3.7163,
            "2019-1": 3.9777, "2019-2": 4.2391, "2019-3": 4.5005, "2019-4": 4.7619,
            "2020-1": 5.0233, "2020-2": 5.2847, "2020-3": 5.5461, "2020-4": 5.8075
        },
        "4": {
            "category": "201 - 300 kwh",
            "2017-1": 2.4597, "2017-2": 2.9193, "2017-3": 3.3790, "2017-4": 3.8387,
            "2018-1": 4.2983, "2018-2": 4.7580, "2018-3": 5.2177, "2018-4": 5.6773,
            "2019-1": 6.1370, "2019-2": 6.5967, "2019-3": 7.0563, "2019-4": 7.5160,
            "2020-1": 7.9756, "2020-2": 8.4353, "2020-3": 8.8950, "2020-4": 9.3546
        },
        "5": {
            "category": "301 - 400 kwh",
            "2017-1": 2.6580, "2017-2": 3.1159, "2017-3": 3.5739, "2017-4": 4.0318,
            "2018-1": 4.4898, "2018-2": 4.9477, "2018-3": 5.4057, "2018-4": 5.8636,
            "2019-1": 6.3216, "2019-2": 6.7796, "2019-3": 7.2375, "2019-4": 7.6955,
            "2020-1": 8.1534, "2020-2": 8.5897, "2020-3": 9.0260, "2020-4": 9.4624
        },
        "6": {
            "category": "401 - 500 kwh",
            "2017-1": 2.8474, "2017-2": 3.2898, "2017-3": 3.7321, "2017-4": 4.1745,
            "2018-1": 4.6169, "2018-2": 5.0593, "2018-3": 5.5017, "2018-4": 5.9441,
            "2019-1": 6.3864, "2019-2": 6.8288, "2019-3": 7.2712, "2019-4": 7.7136,
            "2020-1": 8.1560, "2020-2": 8.5983, "2020-3": 9.0407, "2020-4": 9.4831
        },
        "7": {
            "category": "Above 500 kwh",
            "2017-1": 2.9173, "2017-2": 3.3537, "2017-3": 3.7900, "2017-4": 4.2263,
            "2018-1": 4.6627, "2018-2": 5.0990, "2018-3": 5.5354, "2018-4": 5.9717,
            "2019-1": 6.4080, "2019-2": 6.8444, "2019-3": 7.2807, "2019-4": 7.7170,
            "2020-1": 8.1534, "2020-2": 8.6114, "2020-3": 9.0693, "2020-4": 9.5273
        }
    },
    "commercial": {
        "category": "Commercial (General)",
        "2017-1": 2.6057, "2017-2": 3.0874, "2017-3": 3.5691, "2017-4": 4.0507,
        "2018-1": 4.5324, "2018-2": 5.0141, "2018-3": 5.4958, "2018-4": 5.9775,
        "2019-1": 6.4592, "2019-2": 6.9409, "2019-3": 7.4225, "2019-4": 7.9042,
        "2020-1": 8.3859, "2020-2": 8.8676, "2020-3": 9.3493, "2020-4": 9.8310
    },
    "small_industry": {
        "category": "Small Industry (380v)",
        "2017-1": 1.7573, "2017-2": 2.0245, "2017-3": 2.2917, "2017-4": 2.5589,
        "2018-1": 2.8224, "2018-2": 3.0889, "2018-3": 3.3553, "2018-4": 3.6217,
        "2019-1": 3.8814, "2019-2": 4.1470, "2019-3": 4.4127, "2019-4": 4.6783,
        "2020-1": 4.9332, "2020-2": 5.1980, "2020-3": 5.4628, "2020-4": 5.7276
    },
    "medium_industry": {
        "category": "Medium Industry ( >=15kv)",
        "2017-1": 1.3863, "2017-2": 1.6077, "2017-3": 1.8291, "2017-4": 2.0506,
        "2018-1": 2.2714, "2018-2": 2.4927, "2018-3": 2.7140, "2018-4": 2.9353,
        "2019-1": 3.1554, "2019-2": 3.3765, "2019-3": 3.5977, "2019-4": 3.8189,
        "2020-1": 4.0380, "2020-2": 4.2590, "2020-3": 4.4800, "2020-4": 4.7010
    },
    "street_light": {
        "category": "Street Light",
        "2017-1": 2.5111, "2017-2": 2.8983, "2017-3": 3.2854, "2017-4": 3.6725,
        "2018-1": 4.0596, "2018-2": 4.4468, "2018-3": 4.8339, "2018-4": 5.2210,
        "2019-1": 5.6082, "2019-2": 5.9953, "2019-3": 6.3824, "2019-4": 6.7695,
        "2020-1": 7.1567, "2020-2": 7.5438, "2020-3": 7.9309, "2020-4": 8.3181
    }
}

# ============================================================================
# EMBEDDED SERVICE CHARGE DATA (from service_charge.json)
# Keys cleaned (trailing spaces removed) for reliable lookup
# ============================================================================
SERVICE_CHARGE_DATA = {
    "domestic": {
        "<50": {
            "2017-1": 10.24, "2017-2": 10.47, "2017-3": 10.71, "2017-4": 10.95,
            "2018-1": 11.19, "2018-2": 11.42, "2018-3": 11.66, "2018-4": 11.9,
            "2019-1": 12.14, "2019-2": 12.37, "2019-3": 12.61, "2019-4": 12.85,
            "2020-1": 13.08, "2020-2": 13.32, "2020-3": 13.56, "2020-4": 13.8
        },
        ">50": {
            "2017-1": 42.95, "2017-2": 43.9, "2017-3": 44.8, "2017-4": 45.8,
            "2018-1": 46.75, "2018-2": 47.7, "2018-3": 48.65, "2018-4": 49.6,
            "2019-1": 50.55, "2019-2": 51.5, "2019-3": 52.45, "2019-4": 53.4,
            "2020-1": 54.35, "2020-2": 55.3, "2020-3": 56.25, "2020-4": 57.2
        }
    },
    "commercial": {
        "2017-1": 55.13, "2017-2": 56.38, "2017-3": 57.57, "2017-4": 58.75,
        "2018-1": 61.13, "2018-2": 61.32, "2018-3": 62.32, "2018-4": 63.51,
        "2019-1": 64.7, "2019-2": 65.89, "2019-3": 67.07, "2019-4": 68.26,
        "2020-1": 69.45, "2020-2": 70.64, "2020-3": 71.83, "2020-4": 73.02
    }
}


class BillCalculator:
    def __init__(self):
        # No base_path needed anymore as data is embedded
        pass

    async def get_ETdate_Quartile(self, gregorian_date):
        """Returns Ethiopian quarter in 'YYYY-Q' format with EEU fiscal year (Q1 starts in Hamle/month 11)"""
        et_date = EDC.to_ethiopian(gregorian_date.year, gregorian_date.month, gregorian_date.day)
        et_year = et_date.year
        et_month = et_date.month
        print(et_date)
        
        if (11 <= et_month <= 13 ) or( et_month == 1):
            return f"{et_year}-1"
        elif 2 <= et_month <= 4:
            return f"{et_year}-2"
        elif 5 <= et_month <= 7:
            return f"{et_year}-3"
        elif 8 <= et_month <= 10:
            return f"{et_year}-4"
        # else:
        #     return f"{et_year}-1"

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

    def _get_json_value(self, data, *keys, default=None):
        current = data
        for key in keys:
            if key in current:
                current = current[key]
            elif key + ' ' in current:
                current = current[key + ' ']
            elif key.rstrip() in current:
                current = current[key.rstrip()]
            else:
                return default
        return current

    async def get_tarrif(self, catagory=None, consumption=None, date=None):
        # Use embedded TARIFF_DATA instead of reading from file
        tariff_data = TARIFF_DATA
        
        lookup_date = date if date else datetime.now().date()
        date_Q = await self.get_ETdate_Quartile(lookup_date)
        
        if catagory.casefold() == "domestic":
            block = await self.get_block(consumption)
            tariff = self._get_json_value(tariff_data, 'blocks', block, date_Q, default=None)
            if tariff is None:
                raise KeyError(f"Tariff not found for block '{block}' and quarter '{date_Q}'.")
            return tariff
        elif catagory.casefold() == "commercial":
            tariff = self._get_json_value(tariff_data, 'commercial', date_Q, default=None)
            if tariff is None:
                raise KeyError(f"Commercial tariff not found for quarter '{date_Q}'")
            return tariff
        else:
            raise ValueError(f"Unsupported category: {catagory}")

    async def get_service_charge(self, catagory=None, consumption=None, date=None):
        # Use embedded SERVICE_CHARGE_DATA instead of reading from file
        sc_data = SERVICE_CHARGE_DATA
        
        lookup_date = date if date else datetime.now().date()
        date_Q = await self.get_ETdate_Quartile(lookup_date)
        
        if catagory.casefold() == "domestic":
            key = ">50" if consumption > 50 else "<50"
            service_charge = self._get_json_value(sc_data, 'domestic', key, date_Q, default=None)
            if service_charge is None:
                raise KeyError(f"Service charge not found for domestic '{key}' and quarter '{date_Q}'.")
            return service_charge
        elif catagory.casefold() == "commercial":
            service_charge = self._get_json_value(sc_data, 'commercial', date_Q, default=None)
            if service_charge is None:
                raise KeyError(f"Commercial service charge not found for quarter '{date_Q}'")
            return service_charge
        else:
            raise ValueError(f"Unsupported category: {catagory}")

    async def calculate_bill(self, customer_name, ca_number, category, 
                           lastTimeKWH, current_kwh, lastReadingDate, readDate):
        # =============== VALIDATION ===============
        if current_kwh < lastTimeKWH:
            return f"⚠️ Current reading ({current_kwh:,.2f} KWH) is less than previous reading ({lastTimeKWH:,.2f} KWH)."
        
        total_consumption = current_kwh - lastTimeKWH
        reading_interval = (readDate - lastReadingDate).days
        
        if reading_interval <= 0:
            return "❌ Invalid billing period (non-positive days)."
        
        # =============== QUARTER DETERMINATION ===============
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
            return (
                "⚠️ Billing Period Spans Non-Adjacent Quarters\n\n"
                "Your reading period crosses multiple tariff quarters with significant rate changes. "
                "Automatic calculation isn't possible due to complex proration requirements.\n\n"
                "📞 Please contact EEU Customer Service at 6262 or visit your nearest service center "
                "for accurate bill calculation and assistance."
            )
        
        # =============== BILLING LOGIC ===============
        bill_explanation = (
            f"👤 Customer: {customer_name}\n"
            f"🆔 CA Number: {ca_number}\n\n"
            f"🧾 Electricity Bill Calculation Breakdown\n\n"
            f"📅 Billing Period: {lastReadingDate.strftime('%d/%m/%Y')} → {readDate.strftime('%d/%m/%Y')} "
            f"({reading_interval} days)\n\n"
            f"⚡ Previous Reading: {lastTimeKWH:,.2f} KWH ({lastReadingDate.strftime('%d/%m/%Y')})\n"
            f"🔋 Current Reading: {current_kwh:,.2f} KWH ({readDate.strftime('%d/%m/%Y')})\n"
            f"📈 Total Consumption: {total_consumption:,.2f} KWH\n\n"
        )
        
        energy_charge = 0.0
        service_charge_amount = 0.0
        calculation_notes = []
        
        # =============== SAME QUARTER HANDLING ===============
        if is_same_quarter:
            quarter_label = Qcurrent
            bill_explanation += f"✅ Same Quarter Billing ({quarter_label})\n"
            
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
                service_note = f"Full monthly charge = {service_charge_amount:,.2f} Br"
            else:
                service_charge_amount = (service_charge_full / 30) * reading_interval
                service_note = f"({service_charge_full:,.2f} ÷ 30) × {reading_interval} days = {service_charge_amount:,.2f} Br"
            
            calculation_notes.append(
                f"💡 Energy Charge\n"
                f"   {total_consumption:,.2f} KWH × {tariff:,.4f} Br/KWH = {energy_charge:,.2f} Br"
            )
            calculation_notes.append(
                f"💡 Service Charge\n"
                f"   {service_note}"
            )
        
        # =============== CROSS-QUARTER HANDLING ===============
        else:
            bill_explanation += f"⚠️ Cross-Quarter Billing\n"
            bill_explanation += f"   → Previous: Quarter {Qprevious.split('-')[1]} | Current: Quarter {Qcurrent.split('-')[1]}\n"
            
            curr_q_num = int(Qcurrent.split('-')[1])
            et_start_month = {1: 11, 2: 2, 3: 5, 4: 8}[curr_q_num]
            et_start_year = int(Qcurrent.split('-')[0])
             
            try:
                greg_start = EDC.to_gregorian(et_start_year, et_start_month, 1)
                quarter_start_greg = greg_start
            except Exception as e:
                return f"❌ Error calculating quarter boundary: {str(e)}"
            
            days_in_prev_q = (quarter_start_greg - lastReadingDate).days -1
            days_in_curr_q = (readDate - quarter_start_greg).days +1
            
            if days_in_prev_q <= 0 or days_in_curr_q <= 0 or (days_in_prev_q + days_in_curr_q) != reading_interval:
                return (
                    "⚠️ Complex billing period detected. "
                    "Automatic calculation isn't possible due to date alignment issues.\n\n"
                    # "📞 Please contact EEU Customer Service at 6262 for assistance."
                )
            
            bill_explanation += (
                f"   → Days in Quarter {Qprevious.split('-')[1]}: {days_in_prev_q} days "
                f"({lastReadingDate.strftime('%d/%m/%Y')} → {quarter_start_greg.strftime('%d/%m/%Y')})\n"
                f"   → Days in Quarter {Qcurrent.split('-')[1]}: {days_in_curr_q} days "
                f"({(quarter_start_greg + timedelta(days=1)).strftime('%d/%m/%Y')} → {readDate.strftime('%d/%m/%Y')})\n"
            )
            
            cons_prev_q = (total_consumption * days_in_prev_q) / reading_interval
            cons_curr_q = (total_consumption * days_in_curr_q) / reading_interval
             
            if is_standard_period:
                bill_explanation += (
                    f"   → Standard period ({reading_interval} days). "
                    f"Using TOTAL consumption ({total_consumption:,.2f} KWH) to determine tariff blocks for BOTH quarters.\n\n"
                )
                
                tariff_prev = await self.get_tarrif(catagory=category, consumption=total_consumption, date=lastReadingDate)
                tariff_curr = await self.get_tarrif(catagory=category, consumption=total_consumption, date=readDate)
                
                energy_prev = (total_consumption * tariff_prev * days_in_prev_q) / 30
                energy_curr = (total_consumption * tariff_curr * days_in_curr_q) / 30
                
                sc_prev_full = await self.get_service_charge(catagory=category, consumption=cons_prev_q, date=lastReadingDate)
                sc_curr_full = await self.get_service_charge(catagory=category, consumption=cons_curr_q, date=readDate)
                sc_prev = (sc_prev_full * days_in_prev_q) / 30
                sc_curr = (sc_curr_full * days_in_curr_q) / 30
                
                energy_charge = energy_prev + energy_curr
                service_charge_amount = sc_prev + sc_curr
                
                calculation_notes.append(
                    f"💡 Quarter {Qprevious.split('-')[1]} Segment (Energy)\n"
                    f"   Formula: [(Total Consumption × Tariff) ÷ 30] × Segment Days\n"
                    f"   [({total_consumption:,.2f} KWH × {tariff_prev:,.4f} Br/KWH) ÷ 30] × {days_in_prev_q} days\n"
                    f"   = {energy_prev:,.2f} Br"
                )
                calculation_notes.append(
                    f"💡 Quarter {Qcurrent.split('-')[1]} Segment (Energy)\n"
                    f"   Formula: [(Total Consumption × Tariff) ÷ 30] × Segment Days\n"
                    f"   [({total_consumption:,.2f} KWH × {tariff_curr:,.4f} Br/KWH) ÷ 30] × {days_in_curr_q} days\n"
                    f"   = {energy_curr:,.2f} Br"
                )
                calculation_notes.append(
                    f"💡 Quarter {Qprevious.split('-')[1]} Segment (Service)\n"
                    f"   Formula: (Full Service Charge ÷ 30) × Segment Days\n"
                    f"   ({sc_prev_full:,.2f} Br ÷ 30) × {days_in_prev_q} days = {sc_prev:,.2f} Br"
                )
                calculation_notes.append(
                    f"💡 Quarter {Qcurrent.split('-')[1]} Segment (Service)\n"
                    f"   Formula: (Full Service Charge ÷ 30) × Segment Days\n"
                    f"   ({sc_curr_full:,.2f} Br ÷ 30) × {days_in_curr_q} days = {sc_curr:,.2f} Br"
                )
            
            else:
                normalized_total = (total_consumption / reading_interval) * 30
                bill_explanation += (
                    f"   → Non-standard period ({reading_interval} days). "
                    f"Normalizing TOTAL consumption to 30-day equivalent for tariff lookup in BOTH quarters.\n"
                    f"   → Normalized total: ({total_consumption:,.2f} ÷ {reading_interval}) × 30 = {normalized_total:,.2f} KWH\n\n"
                )
                
                tariff_prev = await self.get_tarrif(catagory=category, consumption=normalized_total, date=lastReadingDate)
                tariff_curr = await self.get_tarrif(catagory=category, consumption=normalized_total, date=readDate)
                
                energy_prev = (normalized_total * tariff_prev * days_in_prev_q) / 30
                energy_curr = (normalized_total * tariff_curr * days_in_curr_q) / 30
                
                sc_prev_full = await self.get_service_charge(catagory=category, consumption=cons_prev_q, date=lastReadingDate)
                sc_curr_full = await self.get_service_charge(catagory=category, consumption=cons_curr_q, date=readDate)
                sc_prev = (sc_prev_full * days_in_prev_q) / 30
                sc_curr = (sc_curr_full * days_in_curr_q) / 30
                
                energy_charge = energy_prev + energy_curr
                service_charge_amount = sc_prev + sc_curr
                
                calculation_notes.append(
                    f"💡 Quarter {Qprevious.split('-')[1]} Segment (Energy)\n"
                    f"   Formula: [(Normalized Total × Tariff) ÷ 30] × Segment Days\n"
                    f"   Normalized total: {normalized_total:,.2f} KWH\n"
                    f"   [({normalized_total:,.2f} KWH × {tariff_prev:,.4f} Br/KWH) ÷ 30] × {days_in_prev_q} days\n"
                    f"   = {energy_prev:,.2f} Br"
                )
                calculation_notes.append(
                    f"💡 Quarter {Qcurrent.split('-')[1]} Segment (Energy)\n"
                    f"   Formula: [(Normalized Total × Tariff) ÷ 30] × Segment Days\n"
                    f"   Normalized total: {normalized_total:,.2f} KWH\n"
                    f"   [({normalized_total:,.2f} KWH × {tariff_curr:,.4f} Br/KWH) ÷ 30] × {days_in_curr_q} days\n"
                    f"   = {energy_curr:,.2f} Br"
                )
                calculation_notes.append(
                    f"💡 Quarter {Qprevious.split('-')[1]} Segment (Service)\n"
                    f"   Formula: (Full Service Charge ÷ 30) × Segment Days\n"
                    f"   ({sc_prev_full:,.2f} Br ÷ 30) × {days_in_prev_q} days = {sc_prev:,.2f} Br"
                )
                calculation_notes.append(
                    f"💡 Quarter {Qcurrent.split('-')[1]} Segment (Service)\n"
                    f"   Formula: (Full Service Charge ÷ 30) × Segment Days\n"
                    f"   ({sc_curr_full:,.2f} Br ÷ 30) × {days_in_curr_q} days = {sc_curr:,.2f} Br"
                )
        
        # =============== FEES CALCULATION (WITH EXPLICIT TOTAL LABELS) ===============
        regulatory_fee = (energy_charge + service_charge_amount) * 0.005
        vat = (energy_charge + service_charge_amount) * 0.15 if total_consumption > 200 else 0.0
        tv_levy = 10.0 if (is_standard_period and total_consumption > 50) else ((10.0 / 30) * reading_interval if total_consumption > 50 else 0.0)
        total_bill = energy_charge + service_charge_amount + regulatory_fee + vat + tv_levy
        
        bill_explanation += "\n".join(calculation_notes) + "\n\n"
        
        # Show TOTAL Energy and Service Charges BEFORE fee calculations
        bill_explanation += (
            f"📊 <b>TOTAL Charges Summary</b>\n"
            f"   TOTAL Energy Charge = {energy_charge:,.2f} Br\n"
            f"   TOTAL Service Charge = {service_charge_amount:,.2f} Br\n\n"
        )
        
        # Regulatory Fee with EXPLICIT TOTAL labels
        bill_explanation += (
            f"💡 Regulatory Fee (0.5%)\n"
            f"   Formula: 0.5% × (TOTAL Energy Charge + TOTAL Service Charge)\n"
            f"   0.5% × ({energy_charge:,.2f} + {service_charge_amount:,.2f}) = {regulatory_fee:,.2f} Br\n\n"
        )
        
        # VAT with EXPLICIT TOTAL labels
        bill_explanation += f"💡 VAT (15%)\n"
        if total_consumption > 200:
            bill_explanation += (
                f"   Formula: 15% × (TOTAL Energy Charge + TOTAL Service Charge)\n"
                f"   Applied (consumption > 200 KWH)\n"
                f"   15% × ({energy_charge:,.2f} + {service_charge_amount:,.2f}) = {vat:,.2f} Br\n\n"
            )
        else:
            bill_explanation += "   ❌ Not applied (consumption ≤ 200 KWH)\n\n"
        
        # TV Levy
        bill_explanation += f"💡 TV Levy\n"
        if total_consumption > 50:
            if is_standard_period:
                bill_explanation += (
                    f"   Formula: Fixed 10.00 Br (standard period)\n"
                    f"   Applied (consumption > 50 KWH) = {tv_levy:,.2f} Br\n\n"
                )
            else:
                bill_explanation += (
                    f"   Formula: (10.00 Br ÷ 30) × {reading_interval} days\n"
                    f"   Applied (consumption > 50 KWH) = {tv_levy:,.2f} Br\n\n"
                )
        else:
            bill_explanation += "   ❌ Not applied (consumption ≤ 50 KWH)\n\n"
        
        # Final Summary with EXPLICIT TOTAL labels
        bill_explanation += (
            f"✅ Total Estimated Bill\n"
            f"   {energy_charge:,.2f} Br (TOTAL Energy Charge)\n"
            f" + {service_charge_amount:,.2f} Br (TOTAL Service Charge)\n"
            f" + {regulatory_fee:,.2f} Br (Regulatory Fee)\n"
            f" + {vat:,.2f} Br (VAT)\n"
            f" + {tv_levy:,.2f} Br (TV Levy)\n"
            f"{'─' * 35}\n"
            f" = {total_bill:,.2f} Br\n\n"
        )
        
        period_type = "Standard period (26–34 days)" if is_standard_period else f"Non-standard period ({reading_interval} days)"
        quarter_note = (
            "Same-quarter pricing" if is_same_quarter 
            else "Cross-quarter proration: Energy charge uses [(Consumption × Tariff) ÷ 30] × Segment Days for BOTH quarters"
        )
        bill_explanation += (
            f"ℹ️ Calculation Notes\n"
            f"• {period_type}\n"
            f"• {quarter_note}\n"
            f"• Service charges use (Full Charge ÷ 30) × Segment Days\n"
            f"• Constant divisor '30' represents standard billing cycle days\n"
            f"• Fees calculated on TOTAL consumption ({total_consumption:,.2f} KWH)\n"
            f"• Ethiopian calendar quarters used per EEU billing rules"
        )
        
        return bill_explanation

# ============================================================================
# EXECUTION
# ============================================================================
async def main():
    calculator = BillCalculator()
    cfg = TEST_CONFIG
    customer_name = cfg['customer_name']
    ca_number = cfg['ca_number']
    category = cfg['category']
    previous_kwh = cfg['previous_kwh']
    current_kwh = cfg['current_kwh']

    try:
        lastReadingDate = datetime.strptime(cfg['previous_reading_date'], "%d/%m/%Y").date()
        readDate = datetime.strptime(cfg['current_reading_date'], "%d/%m/%Y").date()
    except ValueError as e:
        print(f"❌ Date format error: {e}")
        print("Please ensure dates are in DD/MM/YYYY format (e.g., 26/12/2025)")
        return

    print("=" * 60)
    print(" " * 15 + "EEU BILL CALCULATION TESTER")
    print("=" * 60)
    print()
    print(f"👤 Customer: {customer_name}")
    print(f"🆔 CA Number: {ca_number}")
    print(f"🏷️ Category: {category}")
    print(f"⚡ Previous KWH: {previous_kwh:,.0f}")
    print(f"🔋 Current KWH: {current_kwh:,.0f}")
    print(f"📅 Previous Date: {cfg['previous_reading_date']}")
    print(f"📅 Current Date: {cfg['current_reading_date']}")
    print()
    print("=" * 60)
    print(" " * 20 + "CALCULATING...")
    print("=" * 60)
    print()

    try:
        result = await calculator.calculate_bill(
            customer_name=customer_name,
            ca_number=ca_number,
            category=category,
            lastTimeKWH=previous_kwh,
            current_kwh=current_kwh,
            lastReadingDate=lastReadingDate,
            readDate=readDate
        )
        
        clean_result = re.sub(r'<[^>]+>', '', result)
        print(clean_result)
        
    except Exception as e:
        print(f"\n❌ CALCULATION ERROR: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())