# Claude Agent Workflow for Odoo Development

This guide explains how Claude agents (and humans) should work with this repository to ensure quality code.

## The Workflow

### 1. **Develop** (Claude writes code)
```bash
# Claude creates/modifies files
# Example: Create a new module or update views
```

### 2. **Validate** (Before committing)
```bash
# Local validation - catches errors immediately
python scripts/validate-modules.py

# Should see: ✅ All checks passed!
# If errors: fix them, then validate again
```

### 3. **Commit** (With confidence)
```bash
git add <files>
git commit -m "Your commit message"

# Pre-commit hook (if enabled) runs validation automatically
# Won't let you commit if validation fails
```

### 4. **Push to Staging**
```bash
git push origin staging
```

### 5. **GitHub Actions** (Auto-runs on push)
- Runs validation again on the server
- View results: PR → Checks tab
- Deployment proceeds only if checks pass

### 6. **Odoo.sh Build** (If Actions pass)
- Staging tier builds and tests the module
- If there are still errors, they show up here
- **This is rare** because validation caught 80% earlier

### 7. **Manual Testing** (If build succeeds)
- Click through all screens in the staging environment
- Verify data looks correct
- Confirm no regressions

### 8. **Merge to Main** (After staging validated)
```bash
# In Odoo.sh: drag Staging → Main
# Or via git:
git checkout main
git merge staging
git push origin main
```

---

## Key Checkpoints for Claude Agents

### Before Committing: Always Run
```bash
python scripts/validate-modules.py
```

**Expected output if successful:**
```
🔍 Odoo Module Validation

Checking XML syntax...
  ✓ centric_longbow_reports/views/longbow_purchase_views.xml
  ✓ centric_longbow_reports/views/longbow_finance_views.xml

Checking __manifest__.py files...
  ✓ centric_longbow_reports/__manifest__.py

Checking field references...
  ✓ All fields valid

Checking XML ID references...
  ✓ All XML ID references resolved

Checking domain syntax...
  ✓ Domain syntax checked

✅ All checks passed!
```

### If Validation Fails
1. **Read the error message** — it tells you exactly what's wrong
2. **Look up the fix** in VALIDATION.md
3. **Edit the file** to fix the issue
4. **Run validation again** to confirm the fix
5. **Then commit**

### Common Mistakes to Avoid

❌ **Using non-stored fields in pivots**
```xml
<field name="account_type" type="row"/>  <!-- ❌ Non-stored! -->
```
✅ **Solution:** Use stored field + domain filter
```xml
<field name="account_id" type="row"/>  <!-- ✅ Stored -->
<field name="domain">[('account_id.account_type', '=', 'asset_receivable')]</field>
```

❌ **Invalid aggregator attribute**
```xml
<field name="price_total" type="measure" aggregator="sum"/>  <!-- ❌ Not valid -->
```
✅ **Solution:** Remove aggregator
```xml
<field name="price_total" type="measure"/>  <!-- ✅ Correct -->
```

❌ **Unescaped XML characters**
```xml
<field name="help">Cash & Working Capital</field>  <!-- ❌ & not escaped -->
```
✅ **Solution:** Use XML entities
```xml
<field name="help">Cash &amp; Working Capital</field>  <!-- ✅ Correct -->
```

❌ **Missing mandatory XML attributes**
```xml
<record model="ir.ui.view">  <!-- ❌ Missing id= -->
```
✅ **Solution:** Add all required attributes
```xml
<record id="view_my_pivot" model="ir.ui.view">  <!-- ✅ Correct -->
```

---

## For Future Claude Agents

When you're building an Odoo module:

1. **Verify all field types first**
   ```python
   # Before using a field in a pivot, confirm it's stored:
   # - purchase.report.price_total → stored ✓
   # - account.move.line.account_type → non-stored ✗
   ```

2. **Use the validation script early and often**
   ```bash
   python scripts/validate-modules.py  # After each file creation
   ```

3. **Read validation warnings** — they're hints, not errors
   - Example: "Non-stored field account_type" → Switch to account_id + domain

4. **Don't commit if validation fails**
   - Local validation is free; Odoo.sh builds cost real time
   - Fix locally first, then commit

5. **Reference existing modules** for patterns
   - Look at `centric_reports` for working view examples
   - Study `centric_gym` for correct pivot structure

---

## Enabling the Pre-Commit Hook

This runs validation automatically on every commit:

```bash
# One-time setup
mkdir -p .git/hooks
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
echo "🔍 Running Odoo validation..."
python scripts/validate-modules.py
if [ $? -ne 0 ]; then
    echo "❌ Validation failed. Commit blocked."
    echo "Run: python scripts/validate-modules.py"
    exit 1
fi
EOF

chmod +x .git/hooks/pre-commit
```

Now every `git commit` will validate first. To bypass (rarely needed):
```bash
git commit --no-verify
```

---

## Troubleshooting

**Q: Validation passes locally but fails in GitHub Actions**
A: Different environment or new changes. Pull latest and re-run locally.

**Q: How do I test a module before the official Odoo.sh build?**
A: Use a local Odoo installation or wait for Odoo.sh staging to build.

**Q: Can I add custom validation checks?**
A: Yes! Edit `.github/workflows/odoo-validate.yml` or `scripts/validate-modules.py`.

**Q: My IDE doesn't run the pre-commit hook. What do I do?**
A: Run `python scripts/validate-modules.py` manually before pushing.

---

## Goal

**Catch errors fast, fix them early, deploy with confidence.**

Validation = Claude agents can work autonomously without waiting for Odoo.sh build feedback loops.
