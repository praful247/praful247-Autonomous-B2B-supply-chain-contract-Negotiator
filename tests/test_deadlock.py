import pytest
import os
from lyzr_automata import Task

# Skip tests if no API key is provided
if not os.environ.get("GEMINI_API_KEY"):
    pytest.skip("Skipping live tests because GEMINI_API_KEY is not set in environment.", allow_module_level=True)

from main import arbiter_vendor_agent, arbiter_buyer_agent, negotiation_model, safe_execute

def test_vendor_arbiter_blocks_illegal_bid():
    """
    Test that the Legal Arbiter successfully blocks a Vendor bid 
    that falls below the $1,000 policy floor.
    """
    illegal_bid = "I can offer $950 for the servers."
    
    test_task = Task(
        name="Test Vendor Arbiter",
        agent=arbiter_vendor_agent,
        model=negotiation_model,
        instructions=f"Review this offer from Vendor: '{illegal_bid}'. Is it VALID or BLOCKED? Reply strictly with one of those words."
    )
    
    response = safe_execute(test_task)
    assert "BLOCKED" in response.upper(), f"Arbiter failed to block illegal vendor bid! Got: {response}"

def test_buyer_arbiter_blocks_illegal_bid():
    """
    Test that the Legal Arbiter successfully blocks a Buyer bid 
    that goes above the $1,200 policy ceiling.
    """
    illegal_bid = "I will pay $1,500 per server to expedite shipping."
    
    test_task = Task(
        name="Test Buyer Arbiter",
        agent=arbiter_buyer_agent,
        model=negotiation_model,
        instructions=f"Review this offer from Buyer: '{illegal_bid}'. Is it VALID or BLOCKED? Reply strictly with one of those words."
    )
    
    response = safe_execute(test_task)
    assert "BLOCKED" in response.upper(), f"Arbiter failed to block illegal buyer bid! Got: {response}"

def test_arbiter_allows_valid_bid():
    """
    Test that the Legal Arbiter allows a bid within the strict bounds.
    """
    valid_bid = "I can offer $1,150 for the servers."
    
    test_task = Task(
        name="Test Valid Vendor",
        agent=arbiter_vendor_agent,
        model=negotiation_model,
        instructions=f"Review this offer from Vendor: '{valid_bid}'. Is it VALID or BLOCKED? Reply strictly with one of those words."
    )
    
    response = safe_execute(test_task)
    assert "VALID" in response.upper(), f"Arbiter wrongly blocked a valid bid! Got: {response}"
