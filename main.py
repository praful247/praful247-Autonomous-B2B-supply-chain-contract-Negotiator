import os
import json
import time
import random
import threading
from dotenv import load_dotenv
from pydantic import BaseModel
from lyzr_automata import Tool
from typing import Any, Dict
from google import genai
from lyzr_automata.ai_models.model_base import AIModel
from lyzr_automata import Agent, Task
from lyzr_automata.pipelines.linear_sync_pipeline import LinearSyncPipeline


load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)
# ==========================================
# 1. NEW GEMINI SDK WRAPPER FOR LYZR
# ==========================================
class GeminiModel(AIModel):
    def __init__(self, api_key: str, parameters: Dict[str, Any]):
        self.parameters = parameters
        # Update to the current active model
        self.model_name = self.parameters.get("model", "gemini-2.5-flash-lite")
        # Initialize the new genai Client
        self.client = genai.Client(api_key=GEMINI_API_KEY)

    def generate_text(
        self, 
        task_id: str = None, 
        system_persona: str = None, 
        prompt: str = None, 
        **kwargs 
    ):
        combined_prompt = f"System Instructions:\n{system_persona}\n\nTask:\n{prompt}"
        # New generate_content method syntax
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=combined_prompt
        )
        return response.text
        
    def generate_image(self, task_id: str, prompt: str):
        raise NotImplementedError("Image generation not required")

# Replace with your actual Gemini API Key

negotiation_model = GeminiModel(
    api_key=GEMINI_API_KEY,
    parameters={"model": "gemini-3.5-flash-lite"}, # Google API requires this for the free tier
)
# ==========================================
# 2. DEFINE THE AGENTS (Private Envelopes)
# ==========================================
vendor_agent_a = Agent(
    role="Vendor A (Premium)",
    prompt_persona="""You are a Premium Enterprise Server Vendor. 
    Your goal is to sell servers for $1,300 each. 
    YOUR HARD LIMIT: You cannot sell for less than $1,100. 
    Offer a fast 30-day delivery SLA. 
    Be concise, propose numbers directly. Do not reveal your hard limit."""
)

vendor_agent_b = Agent(
    role="Vendor B (Value)",
    prompt_persona="""You are a Value-focused Server Vendor. 
    Your goal is to sell servers for $1,150 each. 
    YOUR HARD LIMIT: You cannot sell for less than $1,000. 
    Offer a slower 60-day delivery SLA. 
    Be concise, propose numbers directly. Do not reveal your hard limit."""
)

vendor_agent_c = Agent(
    role="Vendor C (Balanced)",
    prompt_persona="""You are a Balanced Server Vendor. 
    Your goal is to sell servers for $1,250 each. 
    YOUR HARD LIMIT: You cannot sell for less than $1,050. 
    Offer a standard 45-day delivery SLA. 
    Be concise, propose numbers directly. Do not reveal your hard limit."""
)

buyer_agent = Agent(
    role="Buyer",
    prompt_persona="""You are a Procurement Manager. 
    Your goal is to buy servers for $1,100 each. 
    YOUR HARD LIMIT: You cannot pay more than $1,200. 
    You want a 35-day delivery SLA.
    Be concise, propose numbers directly. Do not reveal your hard limit."""
)

arbiter_vendor_agent = Agent(
    role="Legal Arbiter (Vendor)",
    prompt_persona="""You are a strict compliance monitor for the VENDORS. 
    RULE: If ANY VENDOR proposes a price LOWER than $1,000, reply 'BLOCKED: Policy Violation'.
    Otherwise, reply strictly with 'VALID'."""
)

arbiter_buyer_agent = Agent(
    role="Legal Arbiter (Buyer)",
    prompt_persona="""You are a strict compliance monitor for the BUYER.
    RULE: If the BUYER proposes a price HIGHER than $1,200, reply 'BLOCKED: Policy Violation'.
    Otherwise, reply strictly with 'VALID'."""
)

api_lock = threading.Lock()
last_call_time = 0

def safe_execute(task, max_retries=5):
    from google.genai.errors import ClientError
    global last_call_time
    
    # Burst prevention: Space out API calls by at least 2.5 seconds across threads
    with api_lock:
        elapsed = time.time() - last_call_time
        if elapsed < 2.5:
            time.sleep(2.5 - elapsed)
        last_call_time = time.time()

    for attempt in range(max_retries):
        try:
            return task.execute()
        except Exception as e:
            error_str = str(e)
            if "429" in error_str:
                wait_time = 35 + random.uniform(2, 12)
                print(f"\nRate limit (429) hit. Waiting {wait_time:.1f}s before retrying (Attempt {attempt+1}/{max_retries})...")
                time.sleep(wait_time)
            elif "503" in error_str:
                print(f"\nService unavailable (503). Waiting 15s before retrying (Attempt {attempt+1}/{max_retries})...")
                time.sleep(15)
            else:
                raise e
    raise Exception(f"Failed to execute task after {max_retries} retries.")

def compile_final_contract(history: str):
    print("\nExtracting terms and compiling legal JSON contract...")
    
    # Task to reliably extract the final numbers
    extraction_task = Task(
        name="Extract Terms",
        agent=arbiter_vendor_agent,
        model=negotiation_model,
        instructions=f"Review this transcript and find the final agreed terms. {history}\n\nOutput ONLY a JSON array with two integers: [price, days]. Example: [1150, 35]."
    )
    
    raw_output = safe_execute(extraction_task)
    
    try:
        # Clean the output in case the LLM adds markdown formatting
        clean_output = raw_output.replace("```json", "").replace("```", "").strip()
        extracted_values = json.loads(clean_output)
        
        # Feed the extracted data into the Lyzr Tool schema
        schema_input = ContractSchema(
            final_price=extracted_values[0], 
            delivery_days=extracted_values[1]
        )
        final_json = contract_compiler_tool.function(schema_input)
        
        print("\nCONTRACT GENERATED (final_contract.json):")
        print(json.dumps(final_json, indent=2))
        
    except Exception as e:
        print(f"\nFailed to compile contract: {e}\nRaw Output was: {raw_output}")


# ==========================================
# 3. MULTI-ROUND NEGOTIATION ENGINE
# ==========================================
def run_negotiation(max_rounds=3):
    print("Starting Multi-Round Negotiation...\n")
    
    chat_history = ""
    current_round = 1
    
    while current_round <= max_rounds:
        print(f"=== ROUND {current_round} ===")
        
        # ---------------------------------------------
        # 1. VENDOR TURN
        # ---------------------------------------------
        vendor_task = Task(
            name=f"Vendor Turn {current_round}",
            agent=vendor_agent,
            model=negotiation_model,
            instructions=f"Negotiation history:\n{chat_history}\n\nMake an offer or counter-offer. If the Buyer's previous offer meets your budget and SLA requirements, reply EXACTLY with 'AGREED'. Keep your response under 3 sentences.",
            log_output=True 
        )
        vendor_response = safe_execute(vendor_task)
        print(f"\nVendor: {vendor_response}")
        
        if "AGREED" in vendor_response.upper():
            print("\nSUCCESS: Vendor accepted the deal!")
            compile_final_contract(chat_history) # <--- Add this line
            break
            
        chat_history += f"\nVendor: {vendor_response}"
        
        # ---------------------------------------------
        # 2. ARBITER CHECKS VENDOR
        # ---------------------------------------------
        arbiter_vendor_task = Task(
            name=f"Arbiter Vendor Check {current_round}",
            agent=arbiter_vendor_agent,
            model=negotiation_model,
            instructions=f"Review this offer: '{vendor_response}'. Is it VALID or BLOCKED? Reply strictly with one of those words.",
            log_output=True
        )
        arbiter_vendor_response = safe_execute(arbiter_vendor_task)
        print(f"[Arbiter]: {arbiter_vendor_response}")
        
        if "BLOCKED" in arbiter_vendor_response.upper():
            print("\nDEADLOCK: Vendor violated policy bounds. Terminating.")
            break

        # ---------------------------------------------
        # 3. BUYER TURN
        # ---------------------------------------------
        buyer_task = Task(
            name=f"Buyer Turn {current_round}",
            agent=buyer_agent,
            model=negotiation_model,
            instructions=f"Negotiation history:\n{chat_history}\n\nEvaluate the Vendor's offer. If it meets your budget and SLA bounds, reply EXACTLY with 'AGREED'. If not, make a counter-offer. Keep your response under 3 sentences.",
            log_output=True
        )
        buyer_response = safe_execute(buyer_task)
        print(f"\nBuyer: {buyer_response}")
        
        if "AGREED" in buyer_response.upper():
            print("\nSUCCESS: Buyer accepted the deal!")
            break
            
        chat_history += f"\nBuyer: {buyer_response}"
        
        # ---------------------------------------------
        # 4. ARBITER CHECKS BUYER
        # ---------------------------------------------
        arbiter_buyer_task = Task(
            name=f"Arbiter Buyer Check {current_round}",
            agent=arbiter_buyer_agent,
            model=negotiation_model,
            instructions=f"Review this offer: '{buyer_response}'. Is it VALID or BLOCKED? Reply strictly with one of those words.",
            log_output=True
        )
        arbiter_buyer_response = safe_execute(arbiter_buyer_task)
        print(f"[Arbiter]: {arbiter_buyer_response}")
        
        if "BLOCKED" in arbiter_buyer_response.upper():
            print("\nDEADLOCK: Buyer violated policy bounds. Terminating.")
            break
            
        print("\nPausing for 15 seconds to respect free-tier API rate limits...")
        time.sleep(15) 
            
        current_round += 1
        print("\n" + "-"*40 + "\n")

    if current_round > max_rounds:
        print("\nSTALEMATE: Negotiation reached maximum rounds without agreement.")

# ==========================================
# TOOL: JSON CONTRACT COMPILER
# ==========================================

# ==========================================
# TOOL: JSON CONTRACT COMPILER
# ==========================================
class ContractSchema(BaseModel):
    final_price: int
    delivery_days: int

def write_contract(input_data: ContractSchema):
    # Deterministic math handled safely in code
    quantity = 5000
    total_value = input_data.final_price * quantity
    
    contract_payload = {
        "status": "LEGALLY_BINDING",
        "item": "Enterprise Servers",
        "quantity": quantity,
        "price_per_unit_usd": input_data.final_price,
        "delivery_sla_days": input_data.delivery_days,
        "total_contract_value_usd": total_value,
        "audit_trail": "Logged to Lyzr AIMS"
    }
    
    # Write to a local file for the hackathon demo
    with open("final_contract.json", "w") as f:
        json.dump(contract_payload, f, indent=4)
        
    # --- NEW: Generate PDF Contract ---
    try:
        from fpdf import FPDF
        import datetime
        
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("helvetica", "B", 16)
        pdf.cell(0, 10, "LEGALLY BINDING B2B CONTRACT", ln=True, align="C")
        
        pdf.set_font("helvetica", "", 12)
        pdf.ln(10)
        pdf.cell(0, 10, f"Date: {datetime.date.today()}", ln=True)
        pdf.cell(0, 10, f"Status: {contract_payload['status']}", ln=True)
        pdf.ln(5)
        
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 10, "Terms of Agreement:", ln=True)
        pdf.set_font("helvetica", "", 12)
        pdf.cell(0, 10, f"- Item: {contract_payload['item']}", ln=True)
        pdf.cell(0, 10, f"- Quantity: {contract_payload['quantity']:,} units", ln=True)
        pdf.cell(0, 10, f"- Price Per Unit: ${contract_payload['price_per_unit_usd']:,.2f}", ln=True)
        pdf.cell(0, 10, f"- Delivery SLA: {contract_payload['delivery_sla_days']} days", ln=True)
        pdf.cell(0, 10, f"- Total Value: ${contract_payload['total_contract_value_usd']:,.2f}", ln=True)
        
        pdf.ln(10)
        pdf.set_font("helvetica", "I", 10)
        pdf.cell(0, 10, f"Audit Trail: {contract_payload['audit_trail']}", ln=True)
        
        pdf.output("final_contract.pdf")
        print("PDF Contract generated (final_contract.pdf)")
    except ImportError:
        print("\n'fpdf2' not installed. Could not generate PDF. Run: pip install fpdf2")
    # -----------------------------------
        
    return contract_payload

class OutputSchema(BaseModel):
    status: str
    total_contract_value_usd: int

contract_compiler_tool = Tool(
    name="JSON Contract Compiler",
    desc="Calculates total value and writes the final JSON contract to disk.",
    function=write_contract,
    function_input=ContractSchema,
    function_output=OutputSchema,
    default_params={}
)

# ==========================================
# 4. RUN THE APP
# ==========================================
if __name__ == "__main__":
    run_negotiation(max_rounds=4)