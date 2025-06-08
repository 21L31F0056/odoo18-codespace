# -*- coding: utf-8 -*-
"""Classes defining the populate factory for Payments and related models."""
from sdwot.exceptions import AccessError, UserError, RedirectWarning, ValidationError
from sdwot import api, fields, models, _, Command
from sdwot.exceptions import UserError
from sdwot.tools.misc import formatLang, format_date, parse_date


class AccountPayment(models.Model):
    _inherit = "account.payment"

    @api.depends('amount', 'fx_exchange_rate', 'charges')
    def _compute_amount_in_currency(self):
        for record in self:
            exchange_rate = record.fx_exchange_rate
            if exchange_rate == 0:
                exchange_rate = 1
            record.fx_amount_in_currency = (record.amount - record.charges) / exchange_rate

    is_fx_transaction = fields.Boolean('FX Transaction', copy=False, default=False)
    fx_currency_id = fields.Many2one('res.currency', 'Forex Currency', copy=False)
    fx_exchange_rate = fields.Float('Exchange Rate', default=1, copy=False, digits="fx_exchange_rate")
    fx_amount_in_currency = fields.Monetary(string='Amount in currency', store=True, copy=False,
                                            digits="fx_exchange_rate",
                                            compute=_compute_amount_in_currency, currency_field='fx_currency_id')
    bank_charge = fields.Float(string='Intermediary Bank Charges')
    charge_account_id = fields.Many2one('account.account', string="Charges Account")
    charges = fields.Monetary('Charges', copy=False)
    add_charges = fields.Boolean('Add Charges', copy=False, default=False)

    @api.onchange('fx_currency_id', 'fx_exchange_rate', 'is_fx_transaction')
    def set_exchange_rate_values(self):
        if self.is_fx_transaction:
            self.move_id.write({'currency_id': self.fx_currency_id.id})
            self.move_id.exchange_rate = self.fx_exchange_rate
        else:
            self.move_id.write({'currency_id': self.currency_id.id})
            self.move_id.exchange_rate = 0

    @api.onchange('exchange_rate')
    def onchange_exchange_rates(self):
        self.move_id.onchange_exchange_rate()

    @api.onchange('date', 'currency_id')
    def _onchange_date(self):
        if self.date and self.currency_id != self.company_currency_id:
            self.move_id._inverse_currency_id()

    def _prepare_move_line_default_vals(self, write_off_line_vals=None, force_balance=None):
        ''' Prepare the dictionary to create the default account.move.lines for the current payment.
        :param write_off_line_vals: Optional list of dictionaries to create a write-off account.move.line easily containing:
            * amount:       The amount to be added to the counterpart amount.
            * name:         The label to set on the line.
            * account_id:   The account on which create the write-off.
        :param force_balance: Optional balance.
        :return: A list of python dictionary to be passed to the account.move.line's 'create' method.
        '''
        self.ensure_one()
        write_off_line_vals = write_off_line_vals or {}

        if not self.outstanding_account_id:
            raise UserError(_(
                "You can't create a new payment without an outstanding payments/receipts account set either on the company or the %s payment method in the %s journal.",
                self.payment_method_line_id.name, self.journal_id.display_name))

        # Compute amounts.
        bank_charge = self.bank_charge
        for line in write_off_line_vals:
            if line['name'] == 'Bank Charges':
                line['balance'] = -bank_charge
                line['amount_currency'] = -bank_charge
                line[ 'account_id'] = self.charge_account_id.id

        write_off_line_vals_list = write_off_line_vals or []
        write_off_amount_currency = sum(x['amount_currency'] for x in write_off_line_vals_list)
        write_off_balance = sum(x['balance'] for x in write_off_line_vals_list)

        if self.payment_type == 'inbound':
            # Receive money.
            # liquidity_amount_currency = self.amount if not self.is_fx_transaction else self.fx_amount_in_currency
            liquidity_amount_currency = self.amount
        elif self.payment_type == 'outbound':
            # Send money.
            # liquidity_amount_currency = -self.amount if not self.is_fx_transaction else -self.fx_amount_in_currency
            liquidity_amount_currency = -self.amount
        else:
            liquidity_amount_currency = 0.0

        # currency_id = self.currency_id if not self.is_fx_transaction else self.fx_currency_id
        currency_id = self.currency_id

        if not write_off_line_vals and force_balance is not None:
            sign = 1 if liquidity_amount_currency > 0 else -1
            liquidity_balance = sign * abs(force_balance)
        else:
            liquidity_balance = self.move_id._convert(liquidity_amount_currency, currency_id, self.company_currency_id,
                                                      self.company_id,
                                                      self.date)
        counterpart_amount_currency = -liquidity_amount_currency - write_off_amount_currency
        counterpart_balance = -liquidity_balance - write_off_balance
        currency_id = currency_id.id

        # Compute a default label to set on the journal items.
        liquidity_line_name = ''.join(x[1] for x in self._get_liquidity_aml_display_name_list())
        counterpart_line_name = ''.join(x[1] for x in self._get_counterpart_aml_display_name_list())

        line_vals_list = [
            # Liquidity line.
            {
                'name': liquidity_line_name,
                'date_maturity': self.date,
                'amount_currency': liquidity_amount_currency,
                'currency_id': currency_id,
                'debit': liquidity_balance if liquidity_balance > 0.0 else 0.0,
                'credit': -liquidity_balance if liquidity_balance < 0.0 else 0.0,
                'partner_id': self.partner_id.id,
                'account_id': self.outstanding_account_id.id,
            },
            # Receivable / Payable.
            {
                'name': counterpart_line_name,
                'date_maturity': self.date,
                'amount_currency': counterpart_amount_currency + bank_charge if not write_off_line_vals else counterpart_amount_currency,
                'currency_id': currency_id,
                'debit': (counterpart_balance - bank_charge if write_off_line_vals else counterpart_balance) if counterpart_balance > 0.0 else 0.0,
                'credit': (-counterpart_balance - bank_charge if write_off_line_vals else -counterpart_balance) if counterpart_balance < 0.0 else 0.0,
                'partner_id': self.partner_id.id,
                'account_id': self.destination_account_id.id,
            },
        ]
        if not write_off_line_vals:
            if bank_charge:
                line_vals_list.append({
                    'name': 'Bank Charges',
                    'date_maturity': self.date,
                    'amount_currency': -bank_charge,
                    'currency_id': currency_id,
                    'debit': bank_charge if counterpart_balance > 0.0 else 0.0,
                    'credit': bank_charge if counterpart_balance < 0.0 else 0.0,
                    'partner_id': self.partner_id.id,
                    'account_id': self.charge_account_id.id
                })

        return line_vals_list + write_off_line_vals_list

    @api.model
    def _get_trigger_fields_to_synchronize(self):
        return (
            'date', 'amount', 'payment_type', 'partner_type', 'payment_reference', 'is_internal_transfer',
            'currency_id', 'fx_currency_id', 'partner_id', 'destination_account_id', 'partner_bank_id', 'journal_id',
            'exchange_rate', 'inverse_exchange_rate','bank_charge','charge_account_id'
        )

    def _synchronize_to_moves(self, changed_fields):
        ''' Update the account.move regarding the modified account.payment.
        :param changed_fields: A list containing all modified fields on account.payment.
        '''
        if self._context.get('skip_account_move_synchronization'):
            return

        if not any(field_name in changed_fields for field_name in self._get_trigger_fields_to_synchronize()):
            return

        for pay in self.with_context(skip_account_move_synchronization=True):
            liquidity_lines, counterpart_lines, writeoff_lines = pay._seek_for_lines()

            # Make sure to preserve the write-off amount.
            # This allows to create a new payment with custom 'line_ids'.

            write_off_line_vals = []
            if liquidity_lines and counterpart_lines and writeoff_lines:
                write_off_line_vals.append({
                    'name': writeoff_lines[0].name,
                    'account_id': writeoff_lines[0].account_id.id,
                    'partner_id': writeoff_lines[0].partner_id.id,
                    'currency_id': writeoff_lines[0].currency_id.id,
                    'amount_currency': sum(writeoff_lines.mapped('amount_currency')),
                    'balance': sum(writeoff_lines.mapped('balance')),
                })

            line_vals_list = pay._prepare_move_line_default_vals(write_off_line_vals=write_off_line_vals)

            line_ids_commands = [
                Command.update(liquidity_lines.id, line_vals_list[0]) if liquidity_lines else Command.create(
                    line_vals_list[0]),
                Command.update(counterpart_lines.id, line_vals_list[1]) if counterpart_lines else Command.create(
                    line_vals_list[1])
            ]

            for line in writeoff_lines:
                line_ids_commands.append((2, line.id))

            for extra_line_vals in line_vals_list[2:]:
                line_ids_commands.append((0, 0, extra_line_vals))

            # Update the existing journal items.
            # If dealing with multiple write-off lines, they are dropped and a new one is generated.

            pay.move_id \
                .with_context(skip_invoice_sync=True) \
                .write({
                'partner_id': pay.partner_id.id,
                # 'currency_id': pay.currency_id.id if not pay.is_fx_transaction else pay.fx_currency_id.id,
                'currency_id': pay.currency_id.id,
                'partner_bank_id': pay.partner_bank_id.id,
                'line_ids': line_ids_commands,
            })

class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    def _prepare_move_line_default_vals(self, counterpart_account_id=None):
        """ Prepare the dictionary to create the default account.move.lines for the current account.bank.statement.line
        record.
        :return: A list of python dictionary to be passed to the account.move.line's 'create' method.
        """
        self.ensure_one()

        if not counterpart_account_id:
            counterpart_account_id = self.journal_id.suspense_account_id.id

        if not counterpart_account_id:
            raise UserError(_(
                "You can't create a new statement line without a suspense account set on the %s journal.",
                self.journal_id.display_name,
            ))

        company_currency = self.journal_id.company_id.sudo().currency_id
        journal_currency = self.journal_id.currency_id or company_currency
        foreign_currency = self.foreign_currency_id or journal_currency or company_currency

        journal_amount = self.amount
        if foreign_currency == journal_currency:
            transaction_amount = journal_amount
        else:
            transaction_amount = self.amount_currency
        if journal_currency == company_currency:
            company_amount = journal_amount
        elif foreign_currency == company_currency:
            company_amount = transaction_amount
        else:
            company_amount = self.reconcile_payment_id.move_id\
                ._convert(journal_amount,journal_currency, company_currency, self.journal_id.company_id, self.date)

        liquidity_line_vals = {
            'name': self.payment_ref,
            'move_id': self.move_id.id,
            'partner_id': self.partner_id.id,
            'account_id': self.journal_id.default_account_id.id,
            'currency_id': journal_currency.id,
            'amount_currency': journal_amount,
            'debit': company_amount > 0 and company_amount or 0.0,
            'credit': company_amount < 0 and -company_amount or 0.0,
        }

        # Create the counterpart line values.
        counterpart_line_vals = {
            'name': self.payment_ref,
            'account_id': counterpart_account_id,
            'move_id': self.move_id.id,
            'partner_id': self.partner_id.id,
            'currency_id': foreign_currency.id,
            'amount_currency': -transaction_amount,
            'debit': -company_amount if company_amount < 0.0 else 0.0,
            'credit': company_amount if company_amount > 0.0 else 0.0,
        }
        return [liquidity_line_vals, counterpart_line_vals]
