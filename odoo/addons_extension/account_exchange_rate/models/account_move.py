from sdwot import api, fields, models, tools, _
# -*- coding: utf-8 -*-

import logging
from sdwot import api, fields, models, _, Command
from sdwot.tools import (
    float_compare,

)

_logger = logging.getLogger(__name__)

MAX_HASH_VERSION = 3

PAYMENT_STATE_SELECTION = [
    ('not_paid', 'Not Paid'),
    ('in_payment', 'In Payment'),
    ('paid', 'Paid'),
    ('partial', 'Partially Paid'),
    ('reversed', 'Reversed'),
    ('invoicing_legacy', 'Invoicing App Legacy'),
]

TYPE_REVERSE_MAP = {
    'entry': 'entry',
    'out_invoice': 'out_refund',
    'out_refund': 'entry',
    'in_invoice': 'in_refund',
    'in_refund': 'entry',
    'out_receipt': 'out_refund',
    'in_receipt': 'in_refund',
}

EMPTY = object()


class AccountMove(models.Model):
    _inherit = 'account.move'

    invoice_line_ids_in_cc = fields.One2many('account.move.line', 'move_id', copy=False,
                                             readonly=True,
                                             domain=[('display_type', 'in', ('product', 'line_section', 'line_note'))],
                                             states={'draft': [('readonly', False)]})
    exchange_rate = fields.Float(string='Exchange Rate', copy=False, digits="Exchange Rate")
    inverse_exchange_rate = fields.Float(string='Inverse Exchange Rate', copy=False, digits="Inverse Exchange Rate")
    amount_untaxed_unsigned = fields.Monetary(
        string='Untaxed Amount Unsigned',
        compute='_compute_amount', store=True, readonly=True,
        currency_field='company_currency_id',
    )
    amount_tax_unsigned = fields.Monetary(
        string='Tax Unsigned',
        compute='_compute_amount', store=True, readonly=True,
        currency_field='company_currency_id',
    )
    amount_total_unsigned = fields.Monetary(
        string='Total Unsigned',
        compute='_compute_amount', store=True, readonly=True,
        currency_field='company_currency_id',
    )
    amount_residual_unsigned = fields.Monetary(
        string='Amount Due Unsigned',
        compute='_compute_amount', store=True,
        currency_field='company_currency_id',
    )

    def _get_conversion_rate(self, from_currency, to_currency, company, date):
        # if not self.fx_currency_id or (self.exchange_rate and self.currency_id == self.env.company.currency_id):
        currency_rates = {}
        if self.exchange_rate in (1, 0) and self.inverse_exchange_rate in (1, 0):
            if self.move_type not in ('out_invoice', 'out_invoice'):
                rate = sorted(self.currency_id.rate_ids.filtered(lambda x: x.name <= date), key=lambda x: x.name)
                return rate[-1].buy_inverse_company_rate if rate else 1
            else:
                rate = sorted(self.currency_id.rate_ids.filtered(lambda x: x.name <= date), key=lambda x: x.name)
                return rate[-1].inverse_company_rate if rate else 1
        if from_currency == self.company_currency_id:
            currency_rates[from_currency.id] = 1
            currency_rates[to_currency.id] = self.inverse_exchange_rate
        elif to_currency == self.company_currency_id:
            currency_rates[to_currency.id] = 1
            currency_rates[from_currency.id] = self.inverse_exchange_rate
        if not currency_rates.get(to_currency.id):
            currency_rates[to_currency.id] = 1
        if not currency_rates.get(from_currency.id):
            currency_rates[from_currency.id] = 1

        res = currency_rates.get(to_currency.id) / currency_rates.get(from_currency.id)
        # if not (self.exchange_rate and self.currency_id == self.env.company.currency_id):
            # res = to_currency.round(res)
            # precision = self.env['decimal.precision'].precision_get('exchange_rate')
            # res = round(res, precision)

        if self.payment_id.is_fx_transaction:
            currency_rates = {}
            if from_currency == self.company_currency_id:
                currency_rates[from_currency.id] = 1
                currency_rates[to_currency.id] = 1 / self.payment_id.fx_exchange_rate
            elif to_currency == self.company_currency_id:
                currency_rates[to_currency.id] = 1
                currency_rates[from_currency.id] = 1 / self.payment_id.fx_exchange_rate
            res = currency_rates.get(to_currency.id) / currency_rates.get(from_currency.id)

        return res

    def _convert(self, from_amount, from_currency, to_currency, company, date, round=True):
        """Returns the converted amount of ``from_amount``` from the currency
           ``self`` to the currency ``to_currency`` for the given ``date`` and
           company.

           :param company: The company from which we retrieve the convertion rate
           :param date: The nearest date from which we retriev the conversion rate.
           :param round: Round the result or not
        """
        from_currency, to_currency = from_currency or to_currency, to_currency or from_currency
        assert from_currency, "convert amount from unknown currency"
        assert to_currency, "convert amount to unknown currency"
        assert company, "convert amount from unknown company"
        assert date, "convert amount from unknown date"
        # apply conversion rate
        if from_currency == to_currency:
            to_amount = from_amount
        else:
            to_amount = from_amount * self._get_conversion_rate(from_currency, to_currency, company, date)
        # apply rounding
        return to_currency.round(to_amount) if round else to_amount

    @api.onchange('date', 'invoice_date')
    def _onchange_date(self):
        if self.invoice_date or self.date:
            self._inverse_currency_id()

    @api.onchange('currency_id')
    def _inverse_currency_id(self):
        record = self
        if self.company_currency_id != self.currency_id and self.currency_id:
            invoice_date = self.invoice_date or self.date
            if record.move_type == 'out_invoice' or record.payment_id and record.payment_id.partner_type == 'customer':
                currency_rate = record._get_conversion_rate(record.currency_id, record.company_currency_id,
                                                            record.company_id, invoice_date)
                record.exchange_rate = currency_rate
                record.inverse_exchange_rate = 1 / currency_rate

            elif record.move_type == 'in_invoice' or record.payment_id and record.payment_id.partner_type == 'supplier':
                currency_rate = record.with_context(type='buy')._get_conversion_rate(record.currency_id,
                                                                                     record.company_currency_id,
                                                                                     record.company_id,
                                                                                     invoice_date)
                record.exchange_rate = currency_rate
                record.inverse_exchange_rate = 1 / currency_rate
        return super(AccountMove, self)._inverse_currency_id()

    @api.onchange('exchange_rate')
    def onchange_exchange_rate(self):
        if self.exchange_rate:
            self.inverse_exchange_rate = 1 / self.exchange_rate
        else:
            self.inverse_exchange_rate = 0
        self.line_ids.write({'currency_rate': self.inverse_exchange_rate})
        self.line_ids.set_company_currency_values()

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type in ('tree', 'form'):
            currency_name = (self.env['res.company'].browse(
                self._context.get('company_id')) or self.env.company.root_id).currency_id.name
            fields_maps = [
                [['invoice_tab_in_cc'], _('Invoice Lines in %s', currency_name)],
            ]
            for fnames, label in fields_maps:
                xpath_expression = '//page[' + " or ".join(f"@id='{f}'" for f in fnames) + "][1]"
                node = arch.xpath(xpath_expression)
                if node:
                    node[0].set('string', label)
        return arch, view

    @api.depends(
        'line_ids.matched_debit_ids.debit_move_id.move_id.payment_id.is_matched',
        'line_ids.matched_debit_ids.debit_move_id.move_id.line_ids.amount_residual',
        'line_ids.matched_debit_ids.debit_move_id.move_id.line_ids.amount_residual_currency',
        'line_ids.matched_credit_ids.credit_move_id.move_id.payment_id.is_matched',
        'line_ids.matched_credit_ids.credit_move_id.move_id.line_ids.amount_residual',
        'line_ids.matched_credit_ids.credit_move_id.move_id.line_ids.amount_residual_currency',
        'line_ids.balance',
        'line_ids.currency_id',
        'line_ids.amount_currency',
        'line_ids.amount_residual',
        'line_ids.amount_residual_currency',
        'line_ids.payment_id.state',
        'line_ids.full_reconcile_id',
        'state')
    def _compute_amount(self):
        for move in self:
            total_untaxed, total_untaxed_currency = 0.0, 0.0
            total_tax, total_tax_currency = 0.0, 0.0
            total_residual, total_residual_currency = 0.0, 0.0
            total, total_currency = 0.0, 0.0

            for line in move.line_ids:
                if move.is_invoice(True):
                    # === Invoices ===
                    if line.display_type == 'tax' or (line.display_type == 'rounding' and line.tax_repartition_line_id):
                        # Tax amount.
                        total_tax += line.balance
                        total_tax_currency += line.amount_currency
                        total += line.balance
                        total_currency += line.amount_currency
                    elif line.display_type in ('product', 'rounding'):
                        # Untaxed amount.
                        total_untaxed += line.balance
                        total_untaxed_currency += line.amount_currency
                        total += line.balance
                        total_currency += line.amount_currency
                    elif line.display_type == 'payment_term':
                        # Residual amount.
                        total_residual += line.amount_residual
                        total_residual_currency += line.amount_residual_currency
                else:
                    # === Miscellaneous journal entry ===
                    if line.debit:
                        total += line.balance
                        total_currency += line.amount_currency

            sign = move.direction_sign
            move.amount_untaxed = sign * total_untaxed_currency
            move.amount_tax = sign * total_tax_currency
            move.amount_total = sign * total_currency
            move.amount_residual = -sign * total_residual_currency
            move.amount_untaxed_signed = -total_untaxed
            move.amount_tax_signed = -total_tax
            move.amount_total_signed = abs(total) if move.move_type == 'entry' else -total
            move.amount_residual_signed = total_residual
            move.amount_untaxed_unsigned = abs(total_untaxed)
            move.amount_tax_unsigned = abs(total_tax)
            move.amount_total_unsigned = abs(total)
            move.amount_residual_unsigned = abs(total_residual)
            move.amount_total_in_currency_signed = abs(move.amount_total) if move.move_type == 'entry' else -(
                    sign * move.amount_total)

    def _recompute_cash_rounding_lines(self):
        ''' Handle the cash rounding feature on invoices.

        In some countries, the smallest coins do not exist. For example, in Switzerland, there is no coin for 0.01 CHF.
        For this reason, if invoices are paid in cash, you have to round their total amount to the smallest coin that
        exists in the currency. For the CHF, the smallest coin is 0.05 CHF.

        There are two strategies for the rounding:

        1) Add a line on the invoice for the rounding: The cash rounding line is added as a new invoice line.
        2) Add the rounding in the biggest tax amount: The cash rounding line is added as a new tax line on the tax
        having the biggest balance.
        '''
        self.ensure_one()

        def _compute_cash_rounding(self, total_amount_currency):
            ''' Compute the amount differences due to the cash rounding.
            :param self:                    The current account.move record.
            :param total_amount_currency:   The invoice's total in invoice's currency.
            :return:                        The amount differences both in company's currency & invoice's currency.
            '''
            difference = self.invoice_cash_rounding_id.compute_difference(self.currency_id, total_amount_currency)
            if self.currency_id == self.company_id.currency_id:
                diff_amount_currency = diff_balance = difference
            else:
                diff_amount_currency = difference
                diff_balance = self._convert(diff_amount_currency, self.currency_id, self.company_id.currency_id,
                                             self.company_id, self.invoice_date or self.date)
            return diff_balance, diff_amount_currency

        def _apply_cash_rounding(self, diff_balance, diff_amount_currency, cash_rounding_line):
            ''' Apply the cash rounding.
            :param self:                    The current account.move record.
            :param diff_balance:            The computed balance to set on the new rounding line.
            :param diff_amount_currency:    The computed amount in invoice's currency to set on the new rounding line.
            :param cash_rounding_line:      The existing cash rounding line.
            :return:                        The newly created rounding line.
            '''
            rounding_line_vals = {
                'balance': diff_balance,
                'amount_currency': diff_amount_currency,
                'partner_id': self.partner_id.id,
                'move_id': self.id,
                'currency_id': self.currency_id.id,
                'company_id': self.company_id.id,
                'company_currency_id': self.company_id.currency_id.id,
                'display_type': 'rounding',
            }

            if self.invoice_cash_rounding_id.strategy == 'biggest_tax':
                biggest_tax_line = None
                for tax_line in self.line_ids.filtered('tax_repartition_line_id'):
                    if not biggest_tax_line or abs(tax_line.balance) > abs(biggest_tax_line.balance):
                        biggest_tax_line = tax_line

                # No tax found.
                if not biggest_tax_line:
                    return

                rounding_line_vals.update({
                    'name': _('%s (rounding)', biggest_tax_line.name),
                    'account_id': biggest_tax_line.account_id.id,
                    'tax_repartition_line_id': biggest_tax_line.tax_repartition_line_id.id,
                    'tax_tag_ids': [(6, 0, biggest_tax_line.tax_tag_ids.ids)],
                    'tax_ids': [Command.set(biggest_tax_line.tax_ids.ids)]
                })

            elif self.invoice_cash_rounding_id.strategy == 'add_invoice_line':
                if diff_balance > 0.0 and self.invoice_cash_rounding_id.loss_account_id:
                    account_id = self.invoice_cash_rounding_id.loss_account_id.id
                else:
                    account_id = self.invoice_cash_rounding_id.profit_account_id.id
                rounding_line_vals.update({
                    'name': self.invoice_cash_rounding_id.name,
                    'account_id': account_id,
                    'tax_ids': [Command.clear()]
                })

            # Create or update the cash rounding line.
            if cash_rounding_line:
                cash_rounding_line.write(rounding_line_vals)
            else:
                cash_rounding_line = self.env['account.move.line'].create(rounding_line_vals)

        existing_cash_rounding_line = self.line_ids.filtered(lambda line: line.display_type == 'rounding')

        # The cash rounding has been removed.
        if not self.invoice_cash_rounding_id:
            existing_cash_rounding_line.unlink()
            # self.line_ids -= existing_cash_rounding_line
            return

        # The cash rounding strategy has changed.
        if self.invoice_cash_rounding_id and existing_cash_rounding_line:
            strategy = self.invoice_cash_rounding_id.strategy
            old_strategy = 'biggest_tax' if existing_cash_rounding_line.tax_line_id else 'add_invoice_line'
            if strategy != old_strategy:
                # self.line_ids -= existing_cash_rounding_line
                existing_cash_rounding_line.unlink()
                existing_cash_rounding_line = self.env['account.move.line']

        others_lines = self.line_ids.filtered(
            lambda line: line.account_id.account_type not in ('asset_receivable', 'liability_payable'))
        others_lines -= existing_cash_rounding_line
        total_amount_currency = sum(others_lines.mapped('amount_currency'))

        diff_balance, diff_amount_currency = _compute_cash_rounding(self, total_amount_currency)

        # The invoice is already rounded.
        if self.currency_id.is_zero(diff_balance) and self.currency_id.is_zero(diff_amount_currency):
            existing_cash_rounding_line.unlink()
            # self.line_ids -= existing_cash_rounding_line
            return

        # No update needed
        if existing_cash_rounding_line \
                and float_compare(existing_cash_rounding_line.balance, diff_balance,
                                  precision_rounding=self.currency_id.rounding) == 0 \
                and float_compare(existing_cash_rounding_line.amount_currency, diff_amount_currency,
                                  precision_rounding=self.currency_id.rounding) == 0:
            return

        _apply_cash_rounding(self, diff_balance, diff_amount_currency, existing_cash_rounding_line)

    def _compute_payments_widget_to_reconcile_info(self):
        for move in self:
            move.invoice_outstanding_credits_debits_widget = False
            move.invoice_has_outstanding = False

            if move.state != 'posted' \
                    or move.payment_state not in ('not_paid', 'partial') \
                    or not move.is_invoice(include_receipts=True):
                continue

            pay_term_lines = move.line_ids \
                .filtered(lambda line: line.account_id.account_type in ('asset_receivable', 'liability_payable'))

            domain = [
                ('account_id', 'in', pay_term_lines.account_id.ids),
                ('parent_state', '=', 'posted'),
                ('partner_id', '=', move.commercial_partner_id.id),
                ('reconciled', '=', False),
                '|', ('amount_residual', '!=', 0.0), ('amount_residual_currency', '!=', 0.0),
            ]

            payments_widget_vals = {'outstanding': True, 'content': [], 'move_id': move.id}

            if move.is_inbound():
                domain.append(('balance', '<', 0.0))
                payments_widget_vals['title'] = _('Outstanding credits')
            else:
                domain.append(('balance', '>', 0.0))
                payments_widget_vals['title'] = _('Outstanding debits')

            for line in self.env['account.move.line'].search(domain):

                if line.currency_id == move.currency_id:
                    # Same foreign currency.
                    amount = abs(line.amount_residual_currency)
                else:
                    # Different foreign currencies.
                    amount = line.move_id._convert(
                        abs(line.amount_residual), line.company_currency_id,
                        move.currency_id,
                        move.company_id,
                        line.date,
                    )

                if move.currency_id.is_zero(amount):
                    continue

                payments_widget_vals['content'].append({
                    'journal_name': line.ref or line.move_id.name,
                    'amount': amount,
                    'currency_id': move.currency_id.id,
                    'id': line.id,
                    'move_id': line.move_id.id,
                    'date': fields.Date.to_string(line.date),
                    'account_payment_id': line.payment_id.id,
                })

            if not payments_widget_vals['content']:
                continue

            move.invoice_outstanding_credits_debits_widget = payments_widget_vals
            move.invoice_has_outstanding = True

    def _inverse_amount_total(self):
        for move in self:
            if len(move.line_ids) != 2 or move.is_invoice(include_receipts=True):
                continue

            to_write = []

            amount_currency = abs(move.amount_total)
            balance = move._convert(amount_currency, move.currency_id, move.company_currency_id, move.company_id,
                                    move.invoice_date or move.date)

            for line in move.line_ids:
                if not line.currency_id.is_zero(balance - abs(line.balance)):
                    to_write.append((1, line.id, {
                        'debit': line.balance > 0.0 and balance or 0.0,
                        'credit': line.balance < 0.0 and balance or 0.0,
                        'amount_currency': line.balance > 0.0 and amount_currency or -amount_currency,
                    }))

            move.write({'line_ids': to_write})
