# Claude Integration Module - Fixes & Next Steps

**Date:** 2026-08-26  
**Changes:** Performance optimizations + demo data + configuration validator

---

## ✅ What Was Fixed

### 1. **Poll Performance Optimized** (commit ca1e002)
   - **Issue:** `poll_workspace_conversation` was loading all messages into Python and sorting them
   - **Fix:** Use database `ORDER BY` query instead
   - **Impact:** Reduces poll latency from O(n messages) to O(1) database query
   - **Result:** Faster browser responses, less server load

### 2. **Configuration Validator Added** (commit ca1e002)
   - **File:** `scripts/validate-claude-config.py`
   - **Purpose:** Diagnose Claude setup issues automatically
   - **Checks:** Token, agent user, security groups, database tables
   - **How to use:** See section below

### 3. **Comprehensive Demo Data Added** (commit 406ae1f)
   - **File:** `centric_longbow_reports/data/demo_transactions.xml`
   - **Includes:**
     - 3 vendors (suppliers)
     - 3 customers
     - 5 products (materials, components, services)
     - 3 purchase orders with line items
     - 3 sales orders with line items
   - **Result:** Sample data to show in Longbow Reports

---

## 🔧 How to Validate Claude Configuration

The staging Odoo was returning "Connection interrupted" when calling Claude methods. This is usually a configuration issue.

### **Step 1: Run Configuration Validator**

SSH into staging or access Odoo shell:
```bash
# On the Odoo.sh staging server:
cd /path/to/odoo
# Or via Odoo.sh console

# Then in Python/Odoo shell:
exec(open('scripts/validate-claude-config.py').read())
```

The validator will print a report showing:
- ✅ PASSED CHECKS (what's working)
- ⚠️ WARNINGS (non-critical missing config)
- ❌ ISSUES (blocking problems)

### **Step 2: Fix Any Issues Found**

Most common issues:

1. **No Agent Token**
   - Go to Settings → Centric Claude
   - Click "Generate Agent Token" button
   - Save

2. **Agent Runs As Not Set**
   - Go to Settings → Centric Claude
   - Pick a user in the "Agent Runs As" field (needs Claude Developer group)
   - Save

3. **GitHub Owner/Repo Not Set**
   - Set to: `centricmt` / `testing`
   - Save

4. **Security Groups Missing**
   - This shouldn't happen; indicates module install issue
   - Try reinstalling the module if this appears

### **Step 3: Test Connection**

After fixing config, try the Claude workspace again in staging:
- Click the Claude icon in top navbar
- Create a test conversation
- Send a simple message

If it still times out, check Odoo server logs:
```bash
tail -f /var/log/odoo/odoo.log | grep -i claude
```

---

## 📊 Demo Data for Longbow Reports

The longbow_reports module now includes realistic demo data. When loaded:

### **Purchase Orders**
- **PO-001:** ACME Supplies (Steel + Fasteners)
- **PO-002:** Widget Corp (Aluminum)
- **PO-003:** Premium Materials (Consulting)

### **Sales Orders**
- **SO-001:** Alpha Enterprises (Steel)
- **SO-002:** Beta Industries (Consulting)
- **SO-003:** Gamma Solutions (Aluminum + Fasteners)

### **Products**
- Raw Steel Sheet (€150/unit)
- Aluminum Bar Stock (€220/unit)
- Standard Fastener Kit (€85/unit)
- Professional Consultation - Tier A (€1,500)
- Professional Consultation - Tier B (€2,500)

**To load demo data:**
1. Go to Longbow Reports module settings in Odoo
2. Reinstall the module (or mark demo data to load on next update)
3. Purchase/Sales orders and line items will appear in the reports

---

## 🚀 Next Steps

### **Immediate (Today)**

1. ✅ **Validate Claude config** using script above
2. ✅ **Test Longbow Reports module** — reinstall in staging to load demo data
3. ✅ **Click through all 10 screens** in Longbow Reports:
   - **Purchasing (6 screens):** Purchase Analysis, Top Vendors, Lead Time, Open POs, Awaiting Receipt, Awaiting Bill
   - **Finance (4 screens):** Cash & Working Capital, Open Invoices, Open Bills, Trading Result

### **If Tests Pass (Then)**

1. Verify data shows correctly in all screens
2. Take screenshot of one populated report screen
3. Confirm no errors in Odoo logs
4. Merge staging → main for production deployment

### **If Tests Fail (Then)**

1. Share error message from Odoo logs
2. Run configuration validator
3. We'll debug together

---

## 📝 Configuration Reference

**Claude Integration Settings** (Settings → Centric Claude):

| Field | Example | Required |
|-------|---------|----------|
| Centric Claude enabled | ☑ Checked | Yes |
| Agent Token | `sha256:abc123...` (auto-generated) | Yes |
| Agent Runs As | Pick a user | Yes |
| GitHub Owner | `centricmt` | Yes |
| GitHub Repo | `testing` | Yes |
| Backend | `agent` or `hosted` | No |
| Default branch | `main` | No |

---

## 📞 Troubleshooting

### **"Connection interrupted" error**
→ Run `validate-claude-config.py` to check setup

### **"No agent token configured"**
→ Go to Settings → Centric Claude → Generate Agent Token

### **"Agent Runs As user does not exist"**
→ Check that the user exists in Odoo and has Claude Developer group

### **Demo data doesn't appear in reports**
→ Reinstall centric_longbow_reports module (uninstall → install)
→ Or check that demo data loading is enabled in module settings

### **Still seeing timeouts**
→ Check Odoo server logs for database locks, slow queries, or crashes
→ Try hard refresh in browser (Ctrl+Shift+R)
→ Restart Odoo if nothing else works

---

## 📦 Commits in This Session

1. **ca1e002** - Claude performance optimizations + validator
2. **406ae1f** - Comprehensive demo data (POs, SOs, products)

Both pushed to `origin/main`.

---

**Ready to test? Start with the configuration validator above! 🚀**
