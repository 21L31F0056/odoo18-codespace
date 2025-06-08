{
    'name': 'Project Extension',
    'version': '1.0',
    'summary': 'Project timesheet tracking with billable/non-billable buckets',
    'depends': ['project', 'hr_timesheet', 'sale', 'crm','hr','hr_holidays'],
    'data': [
        'security/ir.model.access.csv',
        'views/project_timesheet_view.xml',
        'views/hr_employee.xml',
        'views/project_wizard.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}