import os
import yaml
import json
import pandas as pd
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

# Setup
load_dotenv()
console = Console()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EXPORT_FILE = "risk_assessment_report.csv"

# KB: Risk Configuration
# Define how much each failure hurts the score (Total = 100)
RISK_WEIGHTS = {
    "mfa_failure": 25,        # Critical
    "sla_failure": 15,        # High
    "baa_failure": 20,        # High (Legal)
    "sox_failure": 25         # Critical (Financial)
}

# Define the "Fix" for each failure
REMEDIATION_MAP = {
    "mfa_failure": "Enforce SSO integration or unconditional MFA for all accounts.",
    "sla_failure": "Renegotiate contract to ensure SEV1 reporting within 24h.",
    "baa_failure": "Legal Hold: Do not onboard until HIPAA BAA is signed.",
    "sox_failure": "Revoke developer access to Prod; Implement CI/CD pipelines."
}

def load_files():
    try:
        # We check for these specific files as per your structure
        if not os.path.exists('data/policies.yaml') or not os.path.exists('data/vendor_response.json'):
            raise FileNotFoundError
            
        with open('data/policies.yaml', 'r') as f:
            policy = yaml.safe_load(f)
        with open('data/vendor_response.json', 'r') as f:
            vendor = json.load(f)
        return policy, vendor
    except FileNotFoundError:
        console.print("[bold red]❌ Error: Missing data files in /data folder.[/bold red]")
        console.print("[yellow]    Run 'python src/create_dummy_data.py' to generate them.[/yellow]")
        return None, None

def analyze_risk(full_policy, vendor):
    results = []
    profile = vendor['vendor_profile']
    answers = vendor['answers']
    
    current_score = 100

    # --- 1. BASELINE CHECKS ---
    # MFA Check
    if "contractors" in answers['mfa_status'].lower() and "exempt" in answers['mfa_status'].lower():
        current_score -= RISK_WEIGHTS['mfa_failure']
        results.append({
            "domain": "Baseline: Access", 
            "status": "FAIL", 
            "finding": "Contractors exempt from MFA.",
            "fix": REMEDIATION_MAP['mfa_failure']
        })
    else:
        results.append({"domain": "Baseline: Access", "status": "PASS", "finding": "MFA requirements met.", "fix": "-"})

    # SLA Check
    if "72 hours" in answers['incident_notification']:
        current_score -= RISK_WEIGHTS['sla_failure']
        results.append({
            "domain": "Baseline: Incident Response", 
            "status": "FAIL", 
            "finding": "Vendor SLA (72h) exceeds limit (24h).",
            "fix": REMEDIATION_MAP['sla_failure']
        })

    # --- 2. DYNAMIC INDUSTRY CHECKS ---
    if profile['industry'].lower() == 'healthcare':
        if "BAA" in answers['agreements']:
            results.append({"domain": "Industry: Healthcare", "status": "PASS", "finding": "BAA Agreement confirmed.", "fix": "-"})
        else:
            current_score -= RISK_WEIGHTS['baa_failure']
            results.append({
                "domain": "Industry: Healthcare", 
                "status": "FAIL", 
                "finding": "Missing HIPAA BAA.",
                "fix": REMEDIATION_MAP['baa_failure']
            })

    # --- 3. DYNAMIC STRUCTURE CHECKS ---
    if profile['type'].lower() == 'public':
        # Check for SOX ITGCs
        if "developers have access" in answers['change_management'].lower():
            current_score -= RISK_WEIGHTS['sox_failure']
            results.append({
                "domain": "Public Co: SOX/ITGC", 
                "status": "FAIL", 
                "finding": "Segregation of Duties failure (Devs have Prod access).",
                "fix": REMEDIATION_MAP['sox_failure']
            })
        else:
            results.append({"domain": "Public Co: SOX/ITGC", "status": "PASS", "finding": "Change management adequate.", "fix": "-"})

    return results, current_score

def main():
    console.print(Panel.fit("[bold blue]⚖️  Dynamic TPRM Engine[/bold blue]\nContext-Aware Risk Assessment", border_style="blue"))

    policy, vendor = load_files()
    if not policy: return

    # Print Context
    prof = vendor['vendor_profile']
    console.print(f"[dim]Analyzing Profile:[/dim] [cyan]{prof['name']}[/cyan]")
    console.print(f" • Industry:    [bold]{prof['industry'].upper()}[/bold]")
    console.print(f" • Scale:       [bold]{prof['size'].upper()}[/bold]")
    console.print(f" • Type:        [bold]{prof['type'].upper()}[/bold]\n")

    with console.status("[bold yellow]⚙️  Applying Policy Overlays...[/bold yellow]", spinner="dots"):
        import time; time.sleep(1)
        findings, score = analyze_risk(policy, vendor)

    # Output Table
    table = Table(title="Context-Aware Risk Report & Remediation", box=box.ROUNDED)
    table.add_column("Policy Domain", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Audit Finding", style="white")
    table.add_column("Recommended Action", style="yellow")

    for f in findings:
        status_style = "green" if f['status'] == "PASS" else "red"
        table.add_row(
            f['domain'], 
            f"[{status_style}]{f['status']}[/{status_style}]", 
            f['finding'],
            f['fix']
        )

    console.print(table)
    
    # Final Score Visualization
    score_color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
    console.print(f"\n📊 Risk Score: [bold {score_color}]{score}/100[/bold {score_color}]")

    # CSV Export
    df = pd.DataFrame(findings)
    df['Overall_Score'] = score
    df.to_csv(EXPORT_FILE, index=False)
    console.print(f"💾 Report saved to: [underline]{EXPORT_FILE}[/underline]")

if __name__ == "__main__":
    main()
