# ⚖️ AI TPRM Risk Engine (Context-Aware)

### Dynamic Vendor Risk Assessment & Compliance Auditing

[![Status](https://img.shields.io/badge/Status-Active-success.svg)]()
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Logic](https://img.shields.io/badge/Logic-Dynamic_Overlays-purple.svg)]()

---

### 📖 Overview
Legacy TPRM tools treat every vendor the same. This engine uses **"Context-Aware Logic"** to dynamically generate risk frameworks based on the vendor's profile.

Instead of a static checklist, the system applies **Policy Overlays**:
* **Healthcare Vendor?** -> Automatically enforces **HIPAA BAA** & Data Retention checks.
* **Public Company?** -> Automatically enforces **SOX ITGC** (Segregation of Duties).
* **Enterprise Scale?** -> Automatically enforces stricter **SLA & Insurance** limits.

### ⚡ Feature Highlights
* **Dynamic Policy Overlays:** Merges a "Universal Baseline" with industry-specific rule sets (YAML-based).
* **Hybrid Grading Engine:** Uses **GenAI (OpenAI)** for semantic analysis of unstructured answers, with a **Deterministic Fallback** for hard-fail logic (e.g., missing certifications).
* **Rich CLI Dashboard:** Provides immediate, high-visibility risk scoring for security engineers.

---

### 🛠️ Quick Start

**1. Clone the Repository**
```bash
git clone [https://github.com/codyjkeller/ai-tprm-analyzer.git](https://github.com/codyjkeller/ai-tprm-analyzer.git)
cd ai-tprm-analyzer

pip install -r requirements.txt
python src/analyzer.py

graph TD
    A[Vendor Profile] --> B{Determine Context}
    B -->|Healthcare?| C[Load HIPAA Overlay]
    B -->|Public Co?| D[Load SOX Overlay]
    B -->|Baseline| E[Load Standard Policy]
    
    C & D & E --> F[Master Policy Object]
    
    G[Vendor Answers] --> H(Risk Engine)
    F --> H
    
    H --> I{AI Analysis}
    I -->|Gap Found| J[Generate Risk Finding]
    I -->|Compliance Met| K[Pass]
    
    J & K --> L[Final CLI Report]

.
├── src/
│   └── analyzer.py          # Core Logic: Policy Merging & Risk Grading
├── data/
│   ├── policies.yaml        # The "Brain": Baseline rules + Context Overlays
│   └── vendor_response.json # The "Evidence": Vendor answers & profile data
├── requirements.txt         # Dependencies (Rich, PyYAML, OpenAI)
└── README.md                # Documentation

