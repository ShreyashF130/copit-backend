# 🚀 CopIt Backend | The Engine of High-Speed WhatsApp Commerce

![Status](https://img.shields.io/badge/Status-Production%20Ready-success)
![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-High%20Performance-009688?logo=fastapi&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL-3ECF8E?logo=supabase&logoColor=white)
![Shiprocket](https://img.shields.io/badge/Integration-Shiprocket-purple)
![WhatsApp](https://img.shields.io/badge/Integration-WhatsApp%20Cloud%20API-25D366?logo=whatsapp&logoColor=white)

> **CopIt** is a high-speed e-commerce enabler designed to automate the sales funnel for Instagram sellers. By turning WhatsApp into a fully functional storefront, we reduce checkout friction, automate logistics, and increase conversion rates.

---

## 📖 Table of Contents
- [The Problem & Solution](#-the-problem--solution)
- [Key Features](#-key-features)
- [System Architecture](#-system-architecture)
- [Tech Stack](#-tech-stack)
- [Technical Highlights (Recruiter's Corner)](#-technical-highlights-recruiters-corner)
- [Installation & Setup](#-installation--setup)
- [API Documentation](#-api-documentation)
- [Future Roadmap](#-future-roadmap)

---

## 💡 The Problem & Solution
**The Pain:** Instagram sellers lose 40-50% of customers due to manual DM replies, slow checkout links, and unverified addresses leading to high RTO (Return to Origin).

**The CopIt Solution:** An automated **WhatsApp-First Commerce Engine**.
1.  **Instant Catalog:** Users browse products directly inside WhatsApp.
2.  **Smart Checkout:** A hybrid approach using secure web-handoffs for address validation.
3.  **Automated Logistics:** Real-time pincode checks via Shiprocket to prevent undeliverable orders.

---

## ✨ Key Features

### 🤖 Automated Sales Agent
- Handles incoming messages using **WhatsApp Cloud API**.
- Manages user sessions and cart state (Add to Cart, Update Quantity).
- Interactive message templates for higher engagement.

### 📦 Smart Logistics (Shiprocket Integrated)
- **Real-Time Serviceability:** Validates pincodes instantly before payment to ensure delivery coverage.
- **RTO Protection:** Prevents orders from non-serviceable zones.
- **Shipping Estimates:** Calculates delivery costs dynamically.

### 💳 Secure Payments (Razorpay)
- Generates dynamic payment links.
- **Webhook Listening:** Auto-confirms orders in the database the second a payment succeeds.
- Handles payment failures and retries gracefully.

### 🔐 Secure Web Handoff (The "Hybrid" Flow)
- Generates **Masked Session Links** (e.g., `copit.in/checkout/{uuid}`) to protect user privacy.
- Pre-fills addresses for returning users to enable **1-Click Checkout**.
- Deep-links users back to the WhatsApp bot after address confirmation.

---

## 🏗 System Architecture

The backend follows an **Event-Driven Architecture** centered around FastAPI webhooks.

```mermaid
graph TD
    User((User)) -->|"Sends Message"| WA[WhatsApp Cloud API]
    WA -->|"Webhook Payload"| API[FastAPI Backend]
    
    subgraph "CopIt Engine"
        API -->|"Check Session"| DB[("Supabase/PostgreSQL")]
        API -->|"Validate Pincode"| Ship[Shiprocket API]
        API -->|"Generate Link"| Pay[Razorpay API]
        
        API -->|"State Logic"| Controller[State Manager]
    end
    
    Controller -->|"Response"| WA
    User -->|"Click Checkout Link"| Web[Next.js Frontend]
    Web -->|"Fetch Data (UUID)"| API
    Web -->|"Confirm Address"| DB
