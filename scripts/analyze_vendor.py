import yaml
import argparse
import json
import os
# from openai import OpenAI  # Uncomment for real usage

# Setup (Uncomment for real usage)
# client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- CONFIG ---
POLICY_PATH = 'policies/vendor_standards.yaml'

def load_dynamic_policy(yaml_path):
    """
    Loads the 'active' frameworks defined in the YAML configuration.
    This allows a user to toggle between NIST, CJIS, ISO, etc.
    """
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f"Policy file not found: {yaml_path}")

    with open(yaml_path, 'r') as f:
        full_config = yaml.safe_load(f)
    
    active_keys = full_config.get('active_frameworks', [])
    compiled_policy = {}
    
    print(f"⚙️  Loading Active Frameworks: {active_keys}")
    
    for key in active_keys:
        if key in full_config.get('frameworks', {}):
            # Merge the controls from this framework into our main policy object
            framework_controls = full_config['frameworks'][key]
            compiled_policy.update(framework_controls)
            
    return compiled_policy

def generate_system_prompt(policy_dict):
    """
    Dynamically builds the AI instructions based on the Active Policy.
    This is 'Policy-as-Code' in action.
    """
    prompt = "You are a GRC Risk Analyst. Analyze the vendor response against these specific security controls:\n\n"
    
    for control_id, criteria in policy_dict.items():
        prompt += f"CONTROL: {criteria.get('domain', control_id)}\n"
        prompt += f" - Requirement: {criteria.get('description', 'No description provided.')}\n"
        
        if 'acceptable_answers' in criteria:
            prompt += f" - Acceptable Terms: {', '.join(criteria['acceptable_answers'])}\n"
            
        if 'forbidden_terms' in criteria:
            prompt += f" - FORBIDDEN TERMS (Trigger Failure): {', '.join(criteria['forbidden_terms'])}\n"
            
        if 'critical_flag' in criteria:
            prompt += f" - CRITICAL FAIL CONDITION: {criteria['critical_flag']}\n"
        
        prompt += "\n"
        
    prompt += "Output Format: Return a JSON list of objects with keys: 'control_id', 'status' (PASS/FAIL), 'severity', 'finding', 'recommendation'."
    return prompt

def analyze_vendor_response(vendor_text, policy):
    print(f"🤖 AI Engine: Analyzing against {len(policy)} active controls...")
    
    system_prompt = generate_system_prompt(policy)
    
    # --- MOCK LLM RESPONSE FOR DEMO ---
    # In production, you would pass 'system_prompt' and 'vendor_text' to GPT-4.
    # Here we simulate what GPT-4 would return based on the dummy input.
    
    detected_risks = []

    # Simulation Logic (Mocking the AI's reasoning based on input)
    # 1. Check Encryption (NIST/CIS)
    if "DES" in vendor_text or "AES-256" not in vendor_text:
        detected_risks.append({
            "control_id": "encryption",
            "status": "FAIL",
            "severity": "HIGH",
            "finding": "Vendor uses legacy encryption (DES) or failed to specify AES-256.",
            "recommendation": "Require upgrade to AES-256 per policy."
        })
        
    # 2. Check MFA (CJIS/NIST)
    if "contractors" in vendor_text and "strong passwords" in vendor_text:
        detected_risks.append({
            "control_id": "ac_control",
            "status": "FAIL",
            "severity": "CRITICAL",
            "finding": "Contractors are using passwords only, bypassing MFA requirements.",
            "recommendation": "Enforce MFA for all contractor accounts immediately."
        })

    return detected_risks

if __name__ == "__main__":
    print("--- 🤖 AI TPRM Analyzer v2.1 (Dynamic Standards) ---")
    
    # 1. Load the Policy (YAML)
    try:
        policy = load_dynamic_policy(POLICY_PATH)
    except FileNotFoundError:
        print(f"❌ Error: '{POLICY_PATH}' not found. Please ensure the file exists.")
        exit(1)

    if not policy:
        print("⚠️  Warning: No active frameworks found in policy file.")
        exit(1)

    # 2. Simulate Vendor Input
    dummy_vendor_response = """
    Security: We use encryption for all data, primarily DES for legacy support. 
    Access: Employees use MFA, but contractors use strong passwords to access the portal.
    Data: We keep customer data as long as the account is active.
    """
    print(f"\n📝 Vendor Response Snippet:\n{dummy_vendor_response.strip()}\n")

    # 3. Analyze
    risks = analyze_vendor_response(dummy_vendor_response, policy)

    # 4. Report
    print("\n[🔍 AI Analysis Result]")
    if risks:
        for risk in risks:
            color = "🔴" if risk['severity'] == "CRITICAL" else "🟠"
            print(f"{color} [{risk['severity']}] Control: {risk['control_id']}")
            print(f"   └── Finding: {risk['finding']}")
            print(f"   └── Fix: {risk['recommendation']}")
    else:
        print("✅ No risks detected based on current active standards.")
