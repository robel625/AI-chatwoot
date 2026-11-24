import sys
import io
import json
from datetime import datetime, timedelta, date
from pathlib import Path
from ethiopian_date_converter.ethiopian_date_convertor import to_ethiopian, EthDate, to_gregorian
import re
import asyncio

# Force UTF-8 encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

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
    'previous_reading_date': "20/06/2026",  # Format: DD/MM/YYYY  #6,7
    # 'previous_reading_date': "20/9/2026",  # Format: DD/MM/YYYY  #6,7
    
    # Current Reading
    'current_kwh': 14031,
    'current_reading_date': "14/09/2026"  # Format: DD/MM/YYYY
}
# ============================================================================

class BillCalculator:
    def __init__(self):
        self.base_path = Path(__file__).parent.parent / "EEU_datas"

    async def get_ETdate_Quartile(self, gregorian_date):
        """
        Returns Ethiopian quarter in 'YYYY-Q' format.
        Q1 spans Hamle (11), Nehase (12), Pagume (13) of Year N, and Meskerem (1) of Year N+1.
        The tariff label uses the year of the Meskerem that ends the quarter.
        (e.g., Hamle 2018 -> "2019-1")
        """
        et_date = to_ethiopian(date(gregorian_date.year, gregorian_date.month, gregorian_date.day))
        et_year = et_date.year
        et_month = et_date.month
        
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
        path = self.base_path / "tarrif.json"
        if not path.exists():
            raise FileNotFoundError(f"Tariff file not found at: {path}")
            
        with open(path, 'r', encoding='utf-8') as f:
            tariff_data = json.load(f)
            
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
        path = self.base_path / "service_charge.json"
        if not path.exists():
            raise FileNotFoundError(f"Service charge file not found at: {path}")
            
        with open(path, 'r', encoding='utf-8') as f:
            sc_data = json.load(f)
            
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
        print(f"{lastReadingDate},type {type(lastReadingDate)}")
        if current_kwh < lastTimeKWH:
            return f"⚠️ Current reading ({current_kwh:,.2f} KWH) is less than previous reading ({lastTimeKWH:,.2f} KWH)."
            
        total_consumption = current_kwh - lastTimeKWH
        reading_interval = (readDate - lastReadingDate).days
        
        if reading_interval <= 0:
            return "❌ Invalid billing period (non-positive days)."
            
        # =============== QUARTER DETERMINATION ===============
        Qprevious = await self.get_ETdate_Quartile(lastReadingDate) # returns somehting like "2019-1" string
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
            bill_explanation += f"   → Previous: Quarter {Qprevious.split('-')[1]} ({Qprevious.split('-')[0]}) | Current: Quarter {Qcurrent.split('-')[1]} ({Qcurrent.split('-')[0]})\n"
            
            curr_q_num = int(Qcurrent.split('-')[1]) # This will be 1, 2, 3, or 4
            # EEU fiscal year mapping for quarter start months
            et_start_month = {1: 11, 2: 2, 3: 5, 4: 8}[curr_q_num] # if you are in Q1, the quarter starts in Hamle (11), Q2 starts in Yekatit (2), etc.
            et_start_year = int(Qcurrent.split('-')[0]) # This is the Ethiopian year of the Meskerem that ends the quarter (e.g., 2019 for Q1)
            
            # CRITICAL FIX: For Quarter 1, the fiscal year label (e.g., 2019) 
            # corresponds to the Ethiopian year of Meskerem, but the quarter 
            # actually starts in Hamle of the PREVIOUS Ethiopian year (e.g., 2018).
            if curr_q_num == 1 :
                et_start_year -= 1
            
            try:
                # Calculate the exact Gregorian start date of the current quarter
                greg_start = to_gregorian(EthDate(1, et_start_month, et_start_year)).date()
                quarter_start_greg = greg_start
            except Exception as e:
                return f"❌ Error calculating quarter boundary: {str(e)}"
                
            days_in_prev_q = (quarter_start_greg - lastReadingDate).days
            days_in_curr_q = (readDate - quarter_start_greg).days
            
            if days_in_prev_q <= 0 or days_in_curr_q <= 0 or (days_in_prev_q + days_in_curr_q) != reading_interval:
                return (
                    "⚠️ Complex billing period detected. "
                    "Automatic calculation isn't possible due to date alignment issues.\n\n"
                    "📞 Please contact EEU Customer Service at 6262 for assistance."
                )
                
            bill_explanation += (
                f"   → Days in Previous Quarter: {days_in_prev_q} days "
                f"({lastReadingDate.strftime('%d/%m/%Y')} → {(quarter_start_greg - timedelta(days=1)).strftime('%d/%m/%Y')})\n"
                f"   → Days in Current Quarter: {days_in_curr_q} days "
                f"({quarter_start_greg.strftime('%d/%m/%Y')} → {readDate.strftime('%d/%m/%Y')})\n"
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
                    f"💡 Previous Quarter Segment (Energy)\n"
                    f"   Formula: [(Total Consumption × Tariff) ÷ 30] × Segment Days\n"
                    f"   [({total_consumption:,.2f} KWH × {tariff_prev:,.4f} Br/KWH) ÷ 30] × {days_in_prev_q} days\n"
                    f"   = {energy_prev:,.2f} Br"
                )
                calculation_notes.append(
                    f"💡 Current Quarter Segment (Energy)\n"
                    f"   Formula: [(Total Consumption × Tariff) ÷ 30] × Segment Days\n"
                    f"   [({total_consumption:,.2f} KWH × {tariff_curr:,.4f} Br/KWH) ÷ 30] × {days_in_curr_q} days\n"
                    f"   = {energy_curr:,.2f} Br"
                )
                calculation_notes.append(
                    f"💡 Previous Quarter Segment (Service)\n"
                    f"   Formula: (Full Service Charge ÷ 30) × Segment Days\n"
                    f"   ({sc_prev_full:,.2f} Br ÷ 30) × {days_in_prev_q} days = {sc_prev:,.2f} Br"
                )
                calculation_notes.append(
                    f"💡 Current Quarter Segment (Service)\n"
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
                    f"💡 Previous Quarter Segment (Energy)\n"
                    f"   Formula: [(Normalized Total × Tariff) ÷ 30] × Segment Days\n"
                    f"   Normalized total: {normalized_total:,.2f} KWH\n"
                    f"   [({normalized_total:,.2f} KWH × {tariff_prev:,.4f} Br/KWH) ÷ 30] × {days_in_prev_q} days\n"
                    f"   = {energy_prev:,.2f} Br"
                )
                calculation_notes.append(
                    f"💡 Current Quarter Segment (Energy)\n"
                    f"   Formula: [(Normalized Total × Tariff) ÷ 30] × Segment Days\n"
                    f"   Normalized total: {normalized_total:,.2f} KWH\n"
                    f"   [({normalized_total:,.2f} KWH × {tariff_curr:,.4f} Br/KWH) ÷ 30] × {days_in_curr_q} days\n"
                    f"   = {energy_curr:,.2f} Br"
                )
                calculation_notes.append(
                    f"💡 Previous Quarter Segment (Service)\n"
                    f"   Formula: (Full Service Charge ÷ 30) × Segment Days\n"
                    f"   ({sc_prev_full:,.2f} Br ÷ 30) × {days_in_prev_q} days = {sc_prev:,.2f} Br"
                )
                calculation_notes.append(
                    f"💡 Current Quarter Segment (Service)\n"
                    f"   Formula: (Full Service Charge ÷ 30) × Segment Days\n"
                    f"   ({sc_curr_full:,.2f} Br ÷ 30) × {days_in_curr_q} days = {sc_curr:,.2f} Br"
                )
                
        # =============== FEES CALCULATION (WITH EXPLICIT TOTAL LABELS) ===============
        regulatory_fee = (energy_charge + service_charge_amount) * 0.005
        vat = (energy_charge + service_charge_amount) * 0.15 if total_consumption > 200 else 0.0
        tv_levy = 10.0 if (is_standard_period and total_consumption > 50) else ((10.0 / 30) * reading_interval if total_consumption > 50 else 0.0)
        
        total_bill = energy_charge + service_charge_amount + regulatory_fee + vat + tv_levy
        
        bill_explanation += "\n".join(calculation_notes) + "\n\n"
        
        bill_explanation += (
            f"📊 <b>TOTAL Charges Summary</b>\n"
            f"   TOTAL Energy Charge = {energy_charge:,.2f} Br\n"
            f"   TOTAL Service Charge = {service_charge_amount:,.2f} Br\n\n"
        )
        
        bill_explanation += (
            f"💡 Regulatory Fee (0.5%)\n"
            f"   Formula: 0.5% × (TOTAL Energy Charge + TOTAL Service Charge)\n"
            f"   0.5% × ({energy_charge:,.2f} + {service_charge_amount:,.2f}) = {regulatory_fee:,.2f} Br\n\n"
        )
        
        bill_explanation += f"💡 VAT (15%)\n"
        if total_consumption > 200:
            bill_explanation += (
                f"   Formula: 15% × (TOTAL Energy Charge + TOTAL Service Charge)\n"
                f"   Applied (consumption > 200 KWH)\n"
                f"   15% × ({energy_charge:,.2f} + {service_charge_amount:,.2f}) = {vat:,.2f} Br\n\n"
            )
        else:
            bill_explanation += "   ❌ Not applied (consumption ≤ 200 KWH)\n\n"
            
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
            f"• Ethiopian calendar fiscal quarters used per EEU billing rules"
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