#!/usr/bin/env python3
"""
Give Administrator user full access to all companies in Odoo.
Run in Odoo shell: odoo shell -c /etc/odoo/odoo.conf -d [database]
Then: exec(open('give_admin_full_access.py').read())
"""

print("Giving Administrator full access to all companies...")

# Get Administrator user
admin = env['res.users'].browse(2)
if not admin.exists():
    print("ERROR: Administrator user (id=2) not found")
else:
    print(f"Found: {admin.login}")

    # Get all companies
    companies = env['res.company'].search([])
    print(f"Found {len(companies)} companies:")
    for c in companies:
        print(f"  - {c.name} (ID: {c.id})")

    # Add admin to all companies
    admin.write({'company_ids': [(6, 0, companies.ids)]})
    print(f"\nAdded Administrator to all {len(companies)} companies")

    # Make sure admin is in all security groups
    admin.write({
        'groups_id': [(4, env.ref('base.group_system').id)],  # System admin
    })
    print("Ensured Administrator is in system admin group")

    # Commit changes
    env.cr.commit()
    print("\nDone! Administrator now has full access to all companies and groups.")
    print("Reload Odoo (Ctrl+Shift+R) for changes to take effect.")
