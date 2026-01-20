import yaml
import argparse
import json
import os
# from openai import OpenAI  # Uncomment for real usage

# --- CONFIG ---
POLICY_PATH = 'policies/vendor_standards.yaml'

def load_policy_and_config(yaml_path):
    """
    Loads both the 'active' frameworks and the scoring configuration.
    """
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f"Policy file not found: {yaml_path}")

    with open(yaml_path, 'r') as f:
        full_config = yaml.safe_load(f)
    
    # 1. Extract Scoring Config
    scoring_config = full_config.get('scoring_matrix', {})
    
    # 2. Extract Active Controls
    active_keys = full_config.get('active_frameworks', [])
    compiled_policy = {}
    
    print(f"⚙️  Loading Active Frameworks: {active_keys}")
    for key in active_keys:
        if key in full_config.get('frameworks', {}):
            compiled_policy.update(full_config['frameworks'][key])
            
    return compiled_policy, scoring_config

def generate_system_prompt(policy_dict):
    """
    Dynamically builds the AI instructions.
    """
    prompt = "You are a GRC Risk Analyst. Analyze the vendor response against these controls:\n\n"
    for control_id, criteria in policy_dict.items():
        prompt += f"CONTROL: {criteria.get('domain', control_id)} (Weight: {criteria.get('weight', 0)})\n"
        prompt += f" - Requirement: {criteria.get('description')}\n"
        if 'acceptable_answers' in criteria:
            prompt += f" - Acceptable: {', '.join(criteria['acceptable_answers'])}\n"
        if 'forbidden_terms' in criteria:
            prompt += f" - FAIL IF FOUND: {', '.join(criteria['forbidden_terms'])}\n"
        prompt += "\n"
    prompt += "Output Format: JSON list [{control_id, status (PASS/FAIL), finding, recommendation}]"
    return prompt

def calculate_final_score(risks, policy, config):
    """
    Calculates the score based on the YAML weights and thresholds.
    """
    score = config.get('starting_score', 100)
    critical_hit = False

    for risk in risks:
        if risk['status'] == 'FAIL':
            # Find the weight of this specific control
            control_id = risk['control_id']
            weight = policy.get(control_id, {}).get('weight', 0)
            score -= weight
            
            # Check for Critical Overrides (Immediate Fail)
            if risk.get('severity') == 'CRITICAL' and config.get('critical_override'):
                critical_hit = True

    # Floor at 0
    score = max(0, score)
    if critical_hit: score = 0

    # Determine Label (High/Med/Low)
    label = "Unknown"
    thresholds = config.get('thresholds', {})
    
    if score >= thresholds['low_risk']['min']:
        label = thresholds['low_risk']['label']
    elif score >= thresholds['medium_risk']['min']:
        label = thresholds['medium_risk']['label']
    else:
        label = thresholds['high_risk']['label']
        
    return score, label

def analyze_vendor_response(vendor_text, policy):
    print(f"🤖 AI Engine: Analyzing against {len(policy)} active controls...")
    
    # --- MOCK AI SIMULATION ---
    detected_risks = []

    # Simulating Failures based on input text
    if "DES" in vendor_text:
        detected_risks.append({
            "control_id": "encryption",
            "status": "FAIL",
            "severity": "HIGH",
            "finding": "Vendor uses legacy encryption (DES).",
            "recommendation": "Require AES-256."
        })
        
    if "contractors" in vendor_text and "passwords" in vendor_text:
        detected_risks.append({
            "control_id": "ia_control",
            "status": "FAIL",
            "severity": "CRITICAL",
            "finding": "MFA not enforced for contractors.",
            "recommendation": "Enforce MFA immediately."
        })

    return detected_risks

if __name__ == "__main__":
    print("--- 🤖 AI TPRM Analyzer v3.0 (Scoring Engine) ---")
    
    try:
        policy, config = load_policy_and_config(POLICY_PATH)
    except FileNotFoundError:
        print(f"❌ Error: '{POLICY_PATH}' not found.")
        exit(1)

    # Dummy Input
    dummy_vendor_response = """
    Security: We use DES encryption for legacy support. 
    Access: Employees use MFA, contractors use passwords.
    """
    print(f"\n📝 Vendor Response:\n{dummy_vendor_response.strip()}\n")

    # Analyze
    risks = analyze_vendor_response(dummy_vendor_response, policy)
    score, label = calculate_final_score(risks, policy, config)

    # Report
    print("\n[🔍 AI Analysis Result]")
    if risks:
        for risk in risks:
            print(f"🔴 [FAIL] {risk['finding']} (-{policy[risk['control_id']]['weight']} pts)")
            print(f"   └── Fix: {risk['recommendation']}")
    else:
        print("✅ No risks detected.")

    # Final Grading
    print("\n" + "="*30)
    print(f"📊 FINAL SCORE: {score}/100")
    print(f"🏷️  STATUS: {label}")
    print("="*30)
