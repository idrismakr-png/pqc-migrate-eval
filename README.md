# PQC-MigrateEval

## 1. Short Description

**Domain:** Enterprise post-quantum cryptography (PQC) migration planning.

**Gap:** Frontier AI models can generate a plausible-sounding PQC migration plan in seconds, but they fail to produce a *valid* one. They violate hard constraints (change freezes, budget limits), hallucinate vendor readiness, miss prerequisite chains (lab testing before production), and fail to explain blockers with actionable resolutions. An expert enterprise security architect would not make these errors.

**Key finding:** On an 8-task suite, `deepseek-chat` averaged **53.47%**, including **two full zero-scores (critical failures)** on tasks where it violated change-freeze and prerequisite constraints. It consistently failed the "blocker coverage" rule across all 8 tasks — naming vendors but not explaining why they block migration or what evidence would resolve them.

## 2. Video Walkthrough

[VIDEO_LINK_HERE]

## 3. Domain and Expertise

This eval draws on enterprise cybersecurity architecture expertise in post-quantum cryptography migration, specifically:

- NIST FIPS 203 (ML-KEM / Kyber), FIPS 204 (ML-DSA / Dilithium), FIPS 205 (SLH-DSA / SPHINCS+).
- Cryptographic Bill of Materials (CBOM) and asset discovery.
- Harvest-Now-Decrypt-Later (HNDL) threat modeling.
- Hybrid cryptography and crypto-agility engineering.
- Vendor compatibility management (HSMs, core banking platforms, cloud KMS).
- Change freeze coordination and operational downtime management.

## 4. What It Tests and Why It Matters

**What it measures:** Whether a frontier AI model can produce a *technically defensible, constraint-compliant, operationally feasible* PQC migration plan under realistic enterprise conditions.

**Who it is for:** Enterprise security architects, CISOs, and AI labs evaluating agentic planning capability. The eval is also directly usable by any organization that wants to benchmark an AI assistant before trusting it with PQC strategy work.

**Why it matters:** PQC migration is a multi-year, high-stakes engineering program that is being mandated by governments (US NSM-10, EU NIS2, UK NCSC). Organizations are increasingly tempted to use AI to draft these plans. If the AI produces a plan that schedules production changes during a change freeze, assumes a vendor's HSM supports ML-KEM when it does not, or omits the prerequisite lab-testing phase, the resulting program will fail — or worse, cause an outage. This eval exposes that gap before it reaches production.

## 5. Setup and Run Instructions

**Prerequisites:** Python 3.10+, a DeepSeek API key (`DEEPSEEK_API_KEY`), internet access.

**One-command run from a clean environment:**

```bash
git clone https://github.com/idrismakr-png/pqc-migrate-eval.git
cd pqc-migrate-eval
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your DEEPSEEK_API_KEY
python check_env.py                # verifies API key + connectivity
python run_eval.py                 # runs all 8 tasks against the configured model(s)