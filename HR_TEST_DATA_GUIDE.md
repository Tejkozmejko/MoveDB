# HR Test Data Generation Guide

This guide explains how to generate 10 test employees with interviews, trials, and HR issues in Odoo.

## Overview

The `generate_hr_test_data.py` script creates:
- **10 Employees**: 5 managed service + 5 full-time outsourced
- **5 Supervisors**: Each employee has a different supervisor assigned
- **Interviews**: One for each employee (different interview types)
- **Active Trials**: One for each employee (trial period contracts)
- **HR Issues**: One for each employee (attendance, performance, policy, safety)

## Usage

### Option 1: Local Odoo Instance

If you have a local Odoo installation running on `localhost:8069`:

```bash
cd C:\Users\Mr.Sant\Desktop\testing\scripts
python generate_hr_test_data.py --url http://localhost:8069 --db centric --username admin --password your_password
```

### Option 2: Odoo.sh Cloud Instance

If using Odoo.sh (e.g., `https://mycompany.odoo.com`):

```bash
cd C:\Users\Mr.Sant\Desktop\testing\scripts
python generate_hr_test_data.py --url https://mycompany.odoo.com --db centric --username admin --password your_password
```

### Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `--url` | Odoo server URL (required) | `http://localhost:8069` or `https://mycompany.odoo.com` |
| `--db` | Database name (required) | `centric` |
| `--username` | Admin username (default: `admin`) | `admin` |
| `--password` | Admin password (required) | `your_secure_password` |

## Employee Details

### Managed Service Employees (Service Type: managed_services)
1. **Alice Johnson** - Site Operative (Supervisor: Supervisor One)
2. **Bob Martinez** - Cleaning Operative (Supervisor: Supervisor Two)
3. **Catherine Davis** - Receptionist (Supervisor: Supervisor Three)
4. **David Wilson** - Administrative Assistant (Supervisor: Supervisor Four)
5. **Emma Brown** - IT Support Technician (Supervisor: Supervisor Five)

### Full-Time Outsourced Employees (Service Type: full_time_outsourced)
6. **Frank Taylor** - Accounts Clerk (Supervisor: Supervisor One)
7. **Grace Anderson** - Administrative Assistant (Supervisor: Supervisor Two)
8. **Henry Lee** - IT Support Technician (Supervisor: Supervisor Three)
9. **Isabella White** - Receptionist (Supervisor: Supervisor Four)
10. **James Harris** - Site Operative (Supervisor: Supervisor Five)

## Employee Data Fields

Each employee is created with:
- Full name
- Job title & department
- Work email & phone
- Mobile phone
- Service type (managed_services or full_time_outsourced)
- Assigned supervisor
- Rate basis (hourly)
- Employee rate (€/hour)
- Client rate (€/hour)
- PIN code (for clocking in/out)
- Barcode (for system integration)
- Hourly cost

## Supervisors Created

Five supervisors are automatically created and assigned to employees (rotating):
1. Supervisor One (supervisor1@example.test)
2. Supervisor Two (supervisor2@example.test)
3. Supervisor Three (supervisor3@example.test)
4. Supervisor Four (supervisor4@example.test)
5. Supervisor Five (supervisor5@example.test)

## HR Data Generated

### Interviews
- Interview types: Phone Screen, Technical, HR Round, Final Round
- One interview per employee
- Scheduled for 5+ days in the future

### Active Trials
- Trial start date: 10 days ago (simulating ongoing trial)
- Trial end date: 80 days from now (3+ month trial period)
- State: Open/Active

### HR Issues
- Issue types: Attendance Issue, Performance Concern, Policy Violation, Safety Concern
- One issue per employee
- Linked to employee record

## Viewing Results

After running the script, you can see the generated data in Odoo:

1. **Employees**: HR > Employees (should show 10 new employees)
2. **Supervisors**: Contacts > Contacts (should show 5 new supervisors marked as supervisors)
3. **Interviews**: HR > Interviews or Recruitment > Interviews
4. **Active Trials**: HR > Contracts (filter by state = Open)
5. **HR Issues**: HR > HR Issues or Reports (dashboard should update)

## Dashboard Impact

The OZO dashboard card will update to show:
- **HR Issues**: 10 (one per employee)
- **Active Trials**: 10 (one per employee with trial contracts)
- **Interviews**: 10 (one per employee)

## Troubleshooting

### Authentication Error
- Verify your Odoo URL is correct
- Check username and password
- Ensure the user has admin privileges

### Model Not Found Errors
- Some HR modules may have different model names
- Check the actual module models in `centric_employee_changes` and `centric_recruitment`
- Adjust script model references as needed

### Connection Timeout
- For Odoo.sh, ensure you're using HTTPS (not HTTP)
- Check your internet connection
- Verify the Odoo.sh instance is running

## Script Features

✅ Creates employees with all required fields  
✅ Assigns 5 different supervisors (rotates through them)  
✅ Separates managed service vs full-time outsourced employees  
✅ Generates interviews with different types  
✅ Creates active trial period contracts  
✅ Creates HR issues for reporting  
✅ Full error handling and informative output  
✅ Progress tracking during creation  

## Next Steps

After running the script:
1. Open Odoo dashboard to verify creation
2. Check HR Issues report (should show 10 issues)
3. View Active Trials list (should show 10 trials)
4. Check Interviews (should show 10 interviews)
5. Verify supervisor assignments in each employee record
