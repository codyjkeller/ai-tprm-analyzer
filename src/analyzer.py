import os
import yaml
import json
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Setup
load_dotenv()
console = Console()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

def load_files():
    try:
        with open('data/policies.yaml', 'r') as f:
            policy = yaml.safe_load(f)
        with open('data/vendor_response.json', 'r') as f:
            vendor = json.load(f)
        return policy, vendor
    except FileNotFoundError:
        console.print("[bold red]❌ Error: Missing data files in /data folder.[/bold red]")
        return None, None

def analyze_risk(full_policy, vendor):
    results = []
    profile = vendor['vendor_profile']
    answers = vendor['answers']

    # --- 1. BASELINE CHECKS ---
    # MFA Check
    if "contractors" in answers['mfa_status'].lower() and "exempt" in answers['mfa_status'].lower():
        results.append({"domain": "Baseline: Access", "status": "FAIL", "finding": "Contractors exempt from MFA."})
    else:
        results.append({"domain": "Baseline: Access", "status": "PASS", "finding": "MFA requirements met."})

    # SLA Check
    if "72 hours" in answers['incident_notification']:
        results.append({"domain": "Baseline: Incident Response", "status": "FAIL", "finding": "Vendor SLA (72h) exceeds limit (24h)."})

    # --- 2. DYNAMIC INDUSTRY CHECKS ---
    if profile['industry'] == 'healthcare':
        reqs = full_policy['industry_specific']['healthcare']
        if "BAA" in answers['agreements']:
             results.append({"domain": "Industry: Healthcare", "status": "PASS", "finding": "BAA Agreement confirmed."})
        else:
             results.append({"domain": "Industry: Healthcare", "status": "FAIL", "finding": "Missing HIPAA BAA."})

    # --- 3. DYNAMIC STRUCTURE CHECKS ---
    if profile['type'] == 'public':
        # Check for SOX ITGCs (Segregation of Duties)
        if "developers have access" in answers['change_management'].lower():
            results.append({"domain": "Public Co: SOX/ITGC", "status": "FAIL", "finding": "Segregation of Duties failure (Devs have Prod access)."})
        else:
            results.append({"domain": "Public Co: SOX/ITGC", "status": "PASS", "finding": "Change management adequate."})

    return results

def main():
    console.print(Panel.fit("[bold blue]⚖️  Dynamic TPRM Engine[/bold blue]\nContext-Aware Risk Assessment", border_style="blue"))

    policy, vendor = load_files()
    if not policy: return

    # Print Context
    prof = vendor['vendor_profile']
    console.print(f"[dim]Analyzing Profile:[/dim] [cyan]{prof['name']}[/cyan]")
    console.print(f" • Industry: [bold]{prof['industry'].upper()}[/bold]")
    console.print(f" • Scale:    [bold]{prof['size'].upper()}[/bold]")
    console.print(f" • Type:     [bold]{prof['type'].upper()}[/bold]\n")

    with console.status("[bold yellow]⚙️  Applying Policy Overlays...[/bold yellow]", spinner="dots"):
        import time; time.sleep(1)
        findings = analyze_risk(policy, vendor)

    # Output Table
    table = Table(title="Context-Aware Risk Report")
    table.add_column("Policy Domain", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Audit Finding", style="white")

    score = 0
    for f in findings:
        status_style = "green" if f['status'] == "PASS" else "red"
        if f['status'] == "PASS": score += 1
        table.add_row(f['domain'], f"[{status_style}]{f['status']}[/{status_style}]", f['finding'])

    console.print(table)
    
    # Final Score
    final_color = "red" if score < len(findings) else "green"
    console.print(f"\n[bold {final_color}]Risk Score: {score}/{len(findings)}[/bold {final_color}]")

if __name__ == "__main__":
    main()
