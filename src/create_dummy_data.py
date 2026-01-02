import json
import os

# Configuration
DATA_DIR = "./data"
PROFILE_FILE = "vendor_profile.json"

def create_dummy_profile():
    # Ensure the data directory exists
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        print(f"📁 Created directory: {DATA_DIR}")

    # Define a "High Risk" Dummy Vendor
    # We choose 'PUBLIC' and 'HEALTHCARE' to trigger both SOX and HIPAA checks
    dummy_data = {
        "company_name": "HealthTech Solutions Inc.",
        "industry": "HEALTHCARE",
        "type": "PUBLIC",
        "controls": {
            "mfa_enabled": False,              # CRITICAL FAIL: No Multi-Factor Auth
            "incident_response_sla": 72,       # FAIL: Takes 3 days to report breach (Limit is 24h)
            "baa_signed": True,                # PASS: Legal agreement exists
            "prod_access_restricted": False,   # CRITICAL FAIL (SOX): Devs can push to Prod
            "iso_27001_certified": True,       # PASS: General security cert
            "background_checks": True          # PASS: HR security check
        }
    }

    # Write to JSON file
    filepath = os.path.join(DATA_DIR, PROFILE_FILE)
    with open(filepath, 'w') as f:
        json.dump(dummy_data, f, indent=4)
    
    print(f"✅ Generated dummy vendor profile at: {filepath}")
    print("🚀 You can now run 'python src/analyzer.py' to see the risk report!")

if __name__ == "__main__":
    create_dummy_profile()
