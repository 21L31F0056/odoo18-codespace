from sdwot import api, fields, models, Command, _

INTEGRITY_HASH_LINE_FIELDS = ('debit', 'credit', 'account_id', 'partner_id')
from datetime import date, timedelta, datetime


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    price_unit_in_cc = fields.Monetary(string='Price', currency_field='company_currency_id', copy=False)
    price_subtotal_in_cc = fields.Monetary(string='Subtotal', currency_field='company_currency_id', copy=False)
    price_total_in_cc = fields.Monetary(string='Subtotal', currency_field='company_currency_id', copy=False)

    def _prepare_move_line_residual_amounts(self, aml_values, counterpart_currency, shadowed_aml_values=None, other_aml_values=None):
        """ Prepare the available residual amounts for each currency.
        :param aml_values: The values of account.move.line to consider.
        :param counterpart_currency: The currency of the opposite line this line will be reconciled with.
        :param shadowed_aml_values: A mapping aml -> dictionary to replace some original aml values to something else.
                                    This is usefull if you want to preview the reconciliation before doing some changes
                                    on amls like changing a date or an account.
        :param other_aml_values:    The other aml values to be reconciled with the current one.
        :return: A mapping currency -> dictionary containing:
            * residual: The residual amount left for this currency.
            * rate:     The rate applied regarding the company's currency.
        """

        def is_payment(aml):
            return aml.move_id.payment_id or aml.move_id.statement_line_id

        def get_sdwot_rate(aml, other_aml, currency):
                if forced_rate := self._context.get('forced_rate_from_register_payment'):
                    return forced_rate
                if other_aml and not is_payment(aml) and is_payment(other_aml):
                    return get_accounting_rate(other_aml, currency)
                if aml.payment_id.is_fx_transaction:
                    return aml.payment_id.inverse_exchange_rate
                if aml.move_id.is_invoice(include_receipts=True):
                    exchange_rate_date = aml.move_id.invoice_date
                else:
                    exchange_rate_date = aml._get_reconciliation_aml_field_value('date', shadowed_aml_values)
                return currency._get_conversion_rate(aml.company_currency_id, currency, aml.company_id, exchange_rate_date)

        def get_accounting_rate(aml, currency):
            if forced_rate := self._context.get('forced_rate_from_register_payment'):
                return forced_rate
            balance = aml._get_reconciliation_aml_field_value('balance', shadowed_aml_values)
            amount_currency = aml._get_reconciliation_aml_field_value('amount_currency', shadowed_aml_values)
            if not aml.company_currency_id.is_zero(balance) and not currency.is_zero(amount_currency):
                return abs(amount_currency / balance)

        aml = aml_values['aml']
        other_aml = (other_aml_values or {}).get('aml')
        remaining_amount_curr = aml_values['amount_residual_currency']
        remaining_amount = aml_values['amount_residual']
        company_currency = aml.company_currency_id
        currency = aml._get_reconciliation_aml_field_value('currency_id', shadowed_aml_values)
        account = aml._get_reconciliation_aml_field_value('account_id', shadowed_aml_values)
        has_zero_residual = company_currency.is_zero(remaining_amount)
        has_zero_residual_currency = currency.is_zero(remaining_amount_curr)
        is_rec_pay_account = account.account_type in ('asset_receivable', 'liability_payable')

        available_residual_per_currency = {}

        if not has_zero_residual:
            available_residual_per_currency[company_currency] = {
                'residual': remaining_amount,
                'rate': 1,
            }
        if currency != company_currency and not has_zero_residual_currency:
            available_residual_per_currency[currency] = {
                'residual': remaining_amount_curr,
                'rate': get_accounting_rate(aml, currency),
            }

        if currency == company_currency \
            and is_rec_pay_account \
            and not has_zero_residual \
            and counterpart_currency != company_currency:
            rate = get_sdwot_rate(aml, other_aml, counterpart_currency)
            # residual_in_foreign_curr = counterpart_currency.round(remaining_amount * rate) # commented by prasad
            residual_in_foreign_curr = remaining_amount * rate
            if not counterpart_currency.is_zero(residual_in_foreign_curr):
                available_residual_per_currency[counterpart_currency] = {
                    'residual': residual_in_foreign_curr,
                    'rate': rate,
                }
        elif currency == counterpart_currency \
            and currency != company_currency \
            and not has_zero_residual_currency:
            available_residual_per_currency[counterpart_currency] = {
                'residual': remaining_amount_curr,
                'rate': get_accounting_rate(aml, currency),
            }
        return available_residual_per_currency


    @api.constrains('price_total', 'price_unit', 'quantity', 'tax_ids', 'discount')
    def set_company_currency_values(self):
        for line in self:
            if not line.move_id.invoice_date and not line.move_id.date:
                invoice_date = datetime.datetime.now()
            else:
                invoice_date = line.move_id.invoice_date or line.move_id.date
            line.price_unit_in_cc = float(
                line.move_id._convert(line.price_unit, line.currency_id, line.company_currency_id,
                                      line.move_id.company_id,
                                      invoice_date))

            line.price_subtotal_in_cc = float(line.move_id._convert(line.price_subtotal, line.currency_id,
                                                                    line.company_currency_id,
                                                                    line.move_id.company_id,
                                                                    invoice_date))
            line.price_total_in_cc = float(line.move_id._convert(line.price_total, line.currency_id,
                                                                 line.company_currency_id,
                                                                 line.move_id.company_id,
                                                                 invoice_date))

    @api.depends('currency_id', 'company_id', 'move_id.date')
    def _compute_currency_rate(self):
        for line in self:
            if line.currency_id:
                rate = line.move_id._get_conversion_rate(
                    from_currency=line.currency_id,
                    to_currency=line.company_currency_id,
                    company=line.company_id,
                    date=line.move_id.invoice_date or line.move_id.date or fields.Date.context_today(line),
                )
                line.currency_rate = 1 / rate if rate else 1
            else:
                line.currency_rate = 1
