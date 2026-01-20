import yaml
import argparse
import json
import os
# from openai import OpenAI  # Uncomment for real usage

# Setup (Uncomment for real usage)
# client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def load_risk_matrix():
    # Ensure this path matches your actual folder structure
    with open('config/risk_matrix.yaml', 'r') as f:
        return yaml.safe_load(f)

def generate_system_prompt(matrix):
    """
    Dynamically builds the AI instructions based on the YAML Policy.
    This is 'Policy-as-Code' in action.
    """
    prompt = "You are a GRC Risk Analyst. Analyze the vendor response against these criteria:\n\n"
    
    prompt += "CRITICAL FLAGS (Immediate Rejection):\n"
    for item in matrix.get('critical_flags', []):
        prompt += f"- {item}\n"
        
    prompt += "\nHIGH RISKS (Requires Remediation):\n"
    for item in matrix.get('high_risks', []):
        prompt += f"- {item}\n"
        
    prompt += "\nOutput Format: Return a JSON list of objects with keys: 'severity', 'finding', 'recommendation'."
    return prompt

def analyze_vendor_response(vendor_text, matrix):
    print(f"🤖 Loading Policy: {len(matrix.get('critical_flags', []))} Critical & {len(matrix.get('high_risks', []))} High checks.")
    
    system_prompt = generate_system_prompt(matrix)
    
    # --- MOCK LLM RESPONSE FOR DEMO ---
    # In production, you would pass 'system_prompt' and 'vendor_text' to GPT-4.
    # Here we simulate what GPT-4 would return based on your input.
    
    detected_risks = []

    # Logic Simulation (Mocking the AI's reasoning)
    if "AES-256" not in vendor_text and "encrypt" in vendor_text.lower():
        # AI would catch vague encryption claims
        pass 
    
    if "contractors" not in vendor_text or "exempt" in vendor_text:
         # Simulating a finding based on the input text provided in main
         pass

    # Let's return a structured mock response resembling a real LLM output
    mock_ai_output = [
        {
            "severity": "CRITICAL",
            "finding": "Vendor access policy implies contractors are exempt from MFA.",
            "recommendation": "Enforce strict MFA for all identities, no exceptions."
        },
        {
            "severity": "HIGH",
            "finding": "Data retention policy is vague ('we keep data as long as needed').",
            "recommendation": "Require defined retention schedule (e.g., 30 days post-termination)."
        }
    ]
    
    return mock_ai_output

if __name__ == "__main__":
    print("--- 🤖 AI TPRM Analyzer v2.0 ---")
    
    # 1. Load the Policy (YAML)
    try:
        matrix = load_risk_matrix()
    except FileNotFoundError:
        print("❌ Error: 'config/risk_matrix.yaml' not found. Creating dummy config...")
        matrix = {"critical_flags": ["No MFA", "No Encryption"], "high_risks": ["Vague SLA"]}

    # 2. Simulate Vendor Input
    dummy_vendor_response = """
    Security: We use encryption for all data. 
    Access: Employees use MFA, contractors use strong passwords.
    Data: We keep customer data as long as the account is active.
    """
    print(f"\n📝 Vendor Response Snippet:\n{dummy_vendor_response.strip()}\n")

    # 3. Analyze
    risks = analyze_vendor_response(dummy_vendor_response, matrix)

    # 4. Report
    print("\n[🔍 AI Analysis Result]")
    if risks:
        for risk in risks:
            color = "🔴" if risk['severity'] == "CRITICAL" else "PY"
            print(f"{color} [{risk['severity']}] {risk['finding']}")
            print(f"   └── Fix: {risk['recommendation']}")
    else:
        print("✅ No risks detected based on current policy.")
