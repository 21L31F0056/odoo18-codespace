{
    'name': 'Exchange Rates',
    'category': 'Accounting/Accounting',
    'summary': 'Exchange Rates',
    'version': '1.0',
    'description': """ This module is used to record different exchange rates separately for sales and purchases. """,
    'depends': ['account'],
    'data': [
        # "security/ir.model.access.csv",
        'views/account_move_view.xml',
        'views/account_payment.xml',
        'views/res_currency.xml',
    ],
    'installable': True,
    'auto_install': False,
    # 'license': 'Proprietary',
}
