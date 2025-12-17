import yaml
import argparse
# import openai (commented out for demo)

def load_risk_matrix():
    with open('../config/risk_matrix.yaml', 'r') as f:
        return yaml.safe_load(f)

def analyze_vendor_response(vendor_text, matrix):
    """
    Simulates sending vendor responses to an LLM (GPT-4) 
    to extract risk flags based on our YAML definition.
    """
    print(f"Analyzing vendor response against {len(matrix['critical_flags'])} risk criteria...")

    # Mocking the AI detection logic for the demo
    detected_risks = []

    # In production, this would be: 
    # response = openai.ChatCompletion.create(...)

    if "MFA" not in vendor_text:
        detected_risks.append("CRITICAL: Vendor did not mention MFA in access controls.")

    if "SOC 2" not in vendor_text:
        detected_risks.append("HIGH: No SOC 2 Type 2 report referenced.")

    return detected_risks

if __name__ == "__main__":
    print("--- AI TPRM Analyzer v1.0 ---")
    # Simulating a vendor input
    dummy_vendor_response = "We encrypt data at rest using AES-256. We perform annual background checks."

    risks = analyze_vendor_response(dummy_vendor_response, load_risk_matrix())

    print("\n[Analysis Result]")
    if risks:
        for risk in risks:
            print(f"[X] {risk}")
    else:
        print("[OK] No critical risks detected.")
