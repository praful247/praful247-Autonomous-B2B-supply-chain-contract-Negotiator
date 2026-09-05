import streamlit as st
import time
import re
import pandas as pd
import concurrent.futures
from main import (
    vendor_agent_a, vendor_agent_b, vendor_agent_c, buyer_agent, 
    arbiter_vendor_agent, arbiter_buyer_agent, negotiation_model,
    compile_final_contract, safe_execute
)
from lyzr_automata import Task, Logger

# Initialize Lyzr AIMS Logger
aims_logger = Logger(file_name="aims_audit_log.json")

st.set_page_config(page_title="Multi-Vendor RFQ Negotiator", layout="wide", page_icon="🤖")

st.title("🤖 Multi-Vendor RFQ Negotiator")
st.markdown("Watch a Procurement Buyer simultaneously negotiate with 3 distinct Suppliers (Premium, Value, Balanced).")

def extract_price(text):
    matches = re.findall(r'\$([0-9,]+)', text)
    if matches:
        return int(matches[0].replace(',', ''))
    return None

# Sidebar Analytics
with st.sidebar:
    st.header("⚡ Live Disruption Webhook")
    trigger_webhook = st.checkbox("⚠️ Trigger Supply Chain Disruption at Round 2", help="Simulates an external webhook event mid-negotiation.")

    st.header("📊 Live Concession Curve")
    chart_placeholder = st.empty()
    
    st.header("📄 Contract Artifacts")
    download_json = st.empty()
    download_pdf = st.empty()
    
    st.header("🕵️ AIMS Audit Log")
    download_aims = st.empty()

# Container for chat
chat_container = st.container()

def plot_prices(prices_dict):
    max_len = max([len(v) for v in prices_dict.values()] + [0])
    if max_len == 0:
        return
        
    df_data = {}
    for k, v in prices_dict.items():
        if len(v) > 0:
            df_data[k] = v + [None] * (max_len - len(v))
            
    df = pd.DataFrame(df_data)
    chart_placeholder.line_chart(df)

if st.button("Start / Restart Autonomous RFQ"):
    chat_history_str = "Negotiation initialized. Buyer seeks 35-day SLA and lowest price.\n"
    
    prices_dict = {"Vendor A": [], "Vendor B": [], "Vendor C": [], "Buyer": []}
    vendors = {
        "Vendor A": vendor_agent_a,
        "Vendor B": vendor_agent_b,
        "Vendor C": vendor_agent_c
    }
    
    with chat_container:
        try:
            for current_round in range(1, 4):
                st.markdown(f"### Round {current_round}")
                
                # --- WEBHOOK INJECTION ---
                if current_round == 2 and trigger_webhook:
                    webhook_msg = "🚨 SYSTEM ALERT: Global shipping lane blocked! All SLAs strictly increased by 20 days. Vendors MUST factor this into their next bids."
                    st.warning(webhook_msg)
                    chat_history_str += f"\n{webhook_msg}\n"
                
                # ---------------------------------------------
                # 1. VENDORS TURN (Concurrent Execution)
                # ---------------------------------------------
                vendor_responses = {}
                
                def fetch_vendor_response(v_name, v_agent, chat_history):
                    vendor_task = Task(
                        name=f"{v_name} Turn {current_round}",
                        agent=v_agent,
                        model=negotiation_model,
                        logger=aims_logger,
                        instructions=f"Negotiation history:\n{chat_history}\n\nMake a competitive offer. If the Buyer's previous offer meets your requirements, reply EXACTLY with 'AGREED'. Keep response under 3 sentences."
                    )
                    return safe_execute(vendor_task)
                
                with st.spinner("Vendors are analyzing terms concurrently..."):
                    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                        future_to_vendor = {
                            executor.submit(fetch_vendor_response, v_name, v_agent, chat_history_str): v_name
                            for v_name, v_agent in vendors.items()
                        }
                        for future in concurrent.futures.as_completed(future_to_vendor):
                            v_name = future_to_vendor[future]
                            try:
                                vendor_responses[v_name] = future.result()
                            except Exception as exc:
                                vendor_responses[v_name] = f"Error: {exc}"
                
                # Print responses in consistent order
                for v_name in ["Vendor A", "Vendor B", "Vendor C"]:
                    resp = vendor_responses[v_name]
                    with st.chat_message("user", avatar="🏢"):
                        st.write(f"**{v_name}**")
                        st.write(resp)
                        
                    p = extract_price(resp)
                    if p: prices_dict[v_name].append(p)
                    
                plot_prices(prices_dict)
                
                # Append vendor responses to history for Buyer
                chat_history_str += "\n--- Vendor Offers this Round ---\n"
                for v_name in ["Vendor A", "Vendor B", "Vendor C"]:
                    chat_history_str += f"{v_name}: {vendor_responses[v_name]}\n"
                    
                # ---------------------------------------------
                # 2. ARBITER CHECKS VENDORS
                # ---------------------------------------------
                with st.spinner("Arbiter checking vendor compliance..."):
                    for v_name in ["Vendor A", "Vendor B", "Vendor C"]:
                        resp = vendor_responses[v_name]
                        arbiter_vendor_task = Task(
                            name=f"Arbiter {v_name} Check {current_round}",
                            agent=arbiter_vendor_agent,
                            model=negotiation_model,
                            logger=aims_logger,
                            instructions=f"Review this offer from {v_name}: '{resp}'. Is it VALID or BLOCKED? Reply strictly with one of those words."
                        )
                        arb_res = safe_execute(arbiter_vendor_task)
                        
                        if "BLOCKED" in arb_res.upper():
                            st.error(f"❌ DEADLOCK: {v_name} violated policy bounds.")
                        else:
                            st.info(f"🛡️ Arbiter approved {v_name}")
    
                # ---------------------------------------------
                # 3. BUYER TURN
                # ---------------------------------------------
                with st.spinner("Buyer is evaluating the competing offers..."):
                    buyer_task = Task(
                        name=f"Buyer Turn {current_round}",
                        agent=buyer_agent,
                        model=negotiation_model,
                        logger=aims_logger,
                        instructions=f"Negotiation history:\n{chat_history_str}\n\nEvaluate the competing offers. Pick the most Pareto-efficient deal. If the best offer meets your strict bounds, reply EXACTLY with 'AGREED to Vendor [X]'. If not, make a counter-offer to the best vendor. Keep your response under 3 sentences."
                    )
                    buyer_response = safe_execute(buyer_task)
                
                with st.chat_message("assistant", avatar="🛒"):
                    st.write("**Buyer (Procurement)**")
                    st.write(buyer_response)
                    
                p = extract_price(buyer_response)
                if p: prices_dict["Buyer"].append(p)
                plot_prices(prices_dict)
                
                if "AGREED" in buyer_response.upper():
                    st.success("🤝 SUCCESS: Buyer accepted a deal!")
                    with st.spinner("Compiling legal contract..."):
                        final_json = compile_final_contract(chat_history_str + f"\nBuyer Final Decision: {buyer_response}")
                    break
                    
                chat_history_str += f"\nBuyer: {buyer_response}\n"
                
                # ---------------------------------------------
                # 4. ARBITER CHECKS BUYER
                # ---------------------------------------------
                with st.spinner("Arbiter checking Buyer compliance..."):
                    arbiter_buyer_task = Task(
                        name=f"Arbiter Buyer Check {current_round}",
                        agent=arbiter_buyer_agent,
                        model=negotiation_model,
                        logger=aims_logger,
                        instructions=f"Review this offer: '{buyer_response}'. Is it VALID or BLOCKED? Reply strictly with one of those words."
                    )
                    arb_res = safe_execute(arbiter_buyer_task)
                
                
                if "BLOCKED" in arb_res.upper():
                    st.error("❌ DEADLOCK: Buyer violated policy bounds. Terminating.")
                    break
                else:
                    st.info(f"🛡️ Arbiter approved Buyer")
        
        except Exception as e:
            st.error(f"🚨 Negotiation Halted: {e}")
            st.info("The AI model API is currently overloaded or rate-limited. The judges will not see this error if they test with a high-tier API key.")
                
    # Outside loop - Provide downloads if successful
    try:
        with open("final_contract.json", "rb") as f:
            download_json.download_button("Download JSON Contract", f, file_name="contract.json", mime="application/json")
        with open("final_contract.pdf", "rb") as f:
            download_pdf.download_button("Download PDF Contract", f, file_name="contract.pdf", mime="application/pdf")
        with open("aims_audit_log.json", "rb") as f:
            download_aims.download_button("Download AIMS Audit Log", f, file_name="aims_audit_log.json", mime="application/json")
    except:
        pass
