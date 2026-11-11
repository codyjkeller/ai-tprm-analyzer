import json
import yaml
import os

DATA_DIR = "./data"

def create_data():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

    # 1. Create vendor_response.json
    # This matches the specific keys your analyzer looks for
    vendor_data = {
        "vendor_profile": {
            "name": "HealthTech Solutions Inc.",
            "industry": "healthcare",
            "size": "enterprise",
            "type": "public"
        },
        "answers": {
            "mfa_status": "Internal employees enforced; Contractors exempt from MFA.",
            "incident_notification": "We will notify customers within 72 hours of a confirmed breach.",
            "agreements": ["MSA", "NDA"], # Missing BAA
            "change_management": "Developers have access to push code to production for hotfixes."
        }
    }
    
    with open(f"{DATA_DIR}/vendor_response.json", 'w') as f:
        json.dump(vendor_data, f, indent=4)

    # 2. Create policies.yaml
    policy_data = {
        "industry_specific": {
            "healthcare": ["BAA", "HIPAA Compliance"],
            "finance": ["GLBA", "SOX"]
        }
    }
    
    with open(f"{DATA_DIR}/policies.yaml", 'w') as f:
        yaml.dump(policy_data, f)

    print("✅ Dummy Data Created: vendor_response.json & policies.yaml")

if __name__ == "__main__":
    create_data()
