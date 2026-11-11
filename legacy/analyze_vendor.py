import yaml
import argparse
import json
import os
import logging
from typing import Dict, List, Tuple, Any

# Configure Enterprise Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [TPRM_ENGINE] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- CONFIG ---
POLICY_PATH = 'policies/vendor_standards.yaml'

def load_policy_and_config(yaml_path: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Loads both the 'active' frameworks and the scoring configuration.
    """
    if not os.path.exists(yaml_path):
        logger.error(f"Policy file not found: {yaml_path}")
        raise FileNotFoundError(f"Policy file not found: {yaml_path}")

    try:
        with open(yaml_path, 'r') as f:
            full_config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML policy: {e}")
        raise

    # 1. Extract Scoring Config
    scoring_config = full_config.get('scoring_matrix', {})
    
    # 2. Extract Active Controls
    active_keys = full_config.get('active_frameworks', [])
    compiled_policy = {}
    
    logger.info(f"Loading Active Frameworks: {active_keys}")
    for key in active_keys:
        frameworks = full_config.get('frameworks', {})
        if key in frameworks:
            compiled_policy.update(frameworks[key])
        else:
            logger.warning(f"Framework '{key}' defined in active_frameworks but not found in definitions.")
            
    return compiled_policy, scoring_config

def generate_system_prompt(policy_dict: Dict[str, Any]) -> str:
    """
    Dynamically builds the AI instructions based on loaded policies.
    """
    prompt = "You are a GRC Risk Analyst. Analyze the vendor response against these controls:\n\n"
    for control_id, criteria in policy_dict.items():
        domain = criteria.get('domain', control_id)
        weight = criteria.get('weight', 0)
        desc = criteria.get('description', 'No description provided.')
        
        prompt += f"CONTROL: {domain} (Weight: {weight})\n"
        prompt += f" - Requirement: {desc}\n"
        
        if 'acceptable_answers' in criteria:
            acceptable = ', '.join(criteria['acceptable_answers'])
            prompt += f" - Acceptable: {acceptable}\n"
        
        if 'forbidden_terms' in criteria:
            forbidden = ', '.join(criteria['forbidden_terms'])
            prompt += f" - FAIL IF FOUND: {forbidden}\n"
        prompt += "\n"
        
    prompt += "Output Format: JSON list [{control_id, status (PASS/FAIL), finding, recommendation}]"
    return prompt

def calculate_final_score(risks: List[Dict[str, Any]], policy: Dict[str, Any], config: Dict[str, Any]) -> Tuple[int, str]:
    """
    Calculates the score based on the YAML weights and thresholds.
    """
    score = config.get('starting_score', 100)
    critical_hit = False

    for risk in risks:
        if risk['status'] == 'FAIL':
            # Find the weight of this specific control
            control_id = risk.get('control_id')
            if control_id and control_id in policy:
                weight = policy[control_id].get('weight', 0)
                score -= weight
            
            # Check for Critical Overrides (Immediate Fail)
            if risk.get('severity') == 'CRITICAL' and config.get('critical_override'):
                critical_hit = True
                logger.warning(f"Critical failure detected: {risk.get('finding')}")

    # Floor at 0
    score = max(0, score)
    if critical_hit:
        score = 0

    # Determine Label (High/Med/Low)
    label = "Unknown"
    thresholds = config.get('thresholds', {})
    
    # Safely get threshold values with defaults
    low_min = thresholds.get('low_risk', {}).get('min', 90)
    med_min = thresholds.get('medium_risk', {}).get('min', 70)
    
    if score >= low_min:
        label = thresholds.get('low_risk', {}).get('label', 'LOW RISK')
    elif score >= med_min:
        label = thresholds.get('medium_risk', {}).get('label', 'MEDIUM RISK')
    else:
        label = thresholds.get('high_risk', {}).get('label', 'HIGH RISK')
        
    return score, label

def analyze_vendor_response(vendor_text: str, policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    logger.info(f"AI Engine: Analyzing against {len(policy)} active controls...")
    
    # --- MOCK AI SIMULATION ---
    # In a real environment, this would call the OpenAI/Azure API
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
    print("\n--- AI TPRM Analyzer v3.0 (Scoring Engine) ---\n")
    
    try:
        policy, config = load_policy_and_config(POLICY_PATH)
    except FileNotFoundError:
        logger.critical(f"Execution halted: Policy file '{POLICY_PATH}' missing.")
        exit(1)
    except Exception as e:
        logger.critical(f"Execution halted: {e}")
        exit(1)

    # Dummy Input for Demonstration
    dummy_vendor_response = """
    Security: We use DES encryption for legacy support. 
    Access: Employees use MFA, contractors use passwords.
    """
    print(f"Vendor Response Summary:\n{dummy_vendor_response.strip()}\n")

    # Analyze
    risks = analyze_vendor_response(dummy_vendor_response, policy)
    score, label = calculate_final_score(risks, policy, config)

    # Report Output
    print("\n[AI Analysis Result]")
    if risks:
        for risk in risks:
            weight = policy.get(risk['control_id'], {}).get('weight', 0)
            print(f"[FAIL] {risk['finding']} (-{weight} pts)")
            print(f"   -> Fix: {risk['recommendation']}")
    else:
        print("No risks detected.")

    # Final Grading
    print("\n" + "="*30)
    print(f"FINAL SCORE: {score}/100")
    print(f"STATUS: {label}")
    print("="*30 + "\n")
