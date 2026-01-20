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
EXPORT_FILE = "risk_assessment_report.csv"

# --- 1. CONFIGURATION (Should ideally be in a YAML) ---
# Expanded for modern GRC domains
RISK_WEIGHTS = {
    "mfa_failure": 25,        # Access Control
    "sox_failure": 25,        # Financial Compliance
    "encrypt_failure": 20,    # Data Protection
    "residency_failure": 15,  # GDPR/Privacy
    "sla_failure": 10,        # Availability
    "subproc_failure": 5      # Supply Chain
}

REMEDIATION_MAP = {
    "mfa_failure": "MANDATORY: Enforce SSO/MFA for all users, including contractors.",
    "sox_failure": "CRITICAL: Revoke developer access to production environment immediately.",
    "encrypt_failure": "Reject weak cyphers. Require AES-256 for storage and TLS 1.3 for transit.",
    "residency_failure": "Data Sovereignty Risk: Require EU-only hosting or SCCs (Standard Contractual Clauses).",
    "sla_failure": "Contractual Amendment: Enforce 24h SEV1 Notification SLA.",
    "subproc_failure": "Vendor Review: Require list of 4th-party subprocessors for review."
}

def load_files():
    # Mocking data loading for the script to run standalone
    # In production, replace this with actual file I/O
    return {}, {
        "vendor_profile": {"name": "MediCloud AI", "industry": "Healthcare", "size": "Enterprise", "type": "Public"},
        "answers": {
            "mfa_status": "Internal staff uses Okta. Contractors use shared passwords.",
            "encryption": "We use DES for legacy compatibility.",
            "hosting": "Data is replicated globally including APAC regions.",
            "incident_notification": "We notify within 72 business hours.",
            "change_management": "Developers have temporary access to prod for debugging."
        }
    }

def analyze_risk(policy, vendor):
    results = []
    answers = vendor['answers']
    profile = vendor['vendor_profile']
    current_score = 100

    # --- CHECK 1: ACCESS CONTROL (MFA) ---
    if "shared" in answers['mfa_status'].lower() or "contractors" in answers['mfa_status'].lower():
        current_score -= RISK_WEIGHTS['mfa_failure']
        results.append({
            "domain": "Identity (IAM)",
            "status": "FAIL",
            "severity": "Critical",
            "finding": "Contractors utilizing shared credentials/no MFA.",
            "fix": REMEDIATION_MAP['mfa_failure']
        })
    else:
        results.append({"domain": "Identity (IAM)", "status": "PASS", "severity": "Low", "finding": "MFA Standard Met", "fix": "-"})

    # --- CHECK 2: DATA PROTECTION (Encryption) ---
    # Senior Logic: Flag deprecated algorithms (DES, MD5, SHA1)
    if any(x in answers['encryption'] for x in ['DES', 'MD5', 'RC4']):
        current_score -= RISK_WEIGHTS['encrypt_failure']
        results.append({
            "domain": "Data Security",
            "status": "FAIL",
            "severity": "High",
            "finding": f"Weak Encryption Algorithm Detected: {answers['encryption']}",
            "fix": REMEDIATION_MAP['encrypt_failure']
        })

    # --- CHECK 3: DATA SOVEREIGNTY (GDPR/Locality) ---
    # If they replicate globally but we are a US/EU company, this is a risk.
    if "globally" in answers['hosting'].lower() or "apac" in answers['hosting'].lower():
        current_score -= RISK_WEIGHTS['residency_failure']
        results.append({
            "domain": "Privacy (GDPR)",
            "status": "WARN",
            "severity": "Medium",
            "finding": "Uncontrolled Global Replication Detected.",
            "fix": REMEDIATION_MAP['residency_failure']
        })

    # --- CHECK 4: COMPLIANCE (SOX/ITGC) ---
    if profile['type'] == 'Public' and "developers" in answers['change_management'].lower():
        current_score -= RISK_WEIGHTS['sox_failure']
        results.append({
            "domain": "Compliance (SOX)",
            "status": "FAIL",
            "severity": "Critical",
            "finding": "Segregation of Duties Conflict (Dev access to Prod).",
            "fix": REMEDIATION_MAP['sox_failure']
        })

    return results, max(current_score, 0) # Score floor at 0

def main():
    console.print(Panel.fit("[bold blue]🛡️  Automated TPRM Risk Engine v2.0[/bold blue]\nAnalyst: Cody Keller", border_style="blue"))

    # Load Mock Data
    policy, vendor = load_files()
    
    prof = vendor['vendor_profile']
    console.print(f"[dim]Assessing Vendor:[/dim] [cyan bold]{prof['name']}[/cyan bold] ({prof['industry']})")

    with console.status("[bold yellow]⚙️  Running heuristics against Security Policy...[/bold yellow]", spinner="dots"):
        import time; time.sleep(1.2) # UX Pause
        findings, score = analyze_risk(policy, vendor)

    # Output Table
    table = Table(title="Risk Findings Report", box=box.SIMPLE_HEAD)
    table.add_column("Domain", style="cyan")
    table.add_column("Severity", style="magenta")
    table.add_column("Finding", style="white")
    table.add_column("Remediation Plan", style="yellow")

    for f in findings:
        if f['status'] != "PASS":
            table.add_row(f['domain'], f['severity'], f['finding'], f['fix'])

    console.print(table)
    
    # Score Card
    color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
    console.print(Panel(f"[bold {color}]Risk Score: {score}/100[/bold {color}]", title="Final Rating", expand=False))

    if score < 70:
        console.print("[bold red]🚫 RECOMMENDATION: DO NOT ONBOARD UNTIL REMEDIATION COMPLETE[/bold red]")

if __name__ == "__main__":
    main()
