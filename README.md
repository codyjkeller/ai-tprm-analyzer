# AI-Powered TPRM Analyzer

## 📌 Overview
An automated Third-Party Risk Management (TPRM) tool designed to reduce the time spent reviewing vendor security questionnaires.

This tool utilizes **Large Language Models (LLMs)** to ingest unstructured vendor responses (PDFs, Excel exports) and validate them against a defined `risk_matrix.yaml`.

## 🚀 Features
* **Auto-Grading:** Automatically assigns a risk score (Low/Med/High) based on missing controls (e.g., No MFA, Outdated Pen Test).
* **Context Awareness:** Can distinguish between "We don't do that" and "We use a compensating control."
* **NIST Alignment:** Maps findings back to NIST 800-53 rev5 families (AC, PE, SC).

## 📂 Configuration
* [`/config/risk_matrix.yaml`](config/risk_matrix.yaml): Define your "Deal Breakers" and risk weighting logic here.
* [`/scripts/analyze_vendor.py`](scripts/analyze_vendor.py): The core logic for processing vendor text inputs.

---
*Maintained by [Cody Keller](https://github.com/codyjkeller)*
