from sdwot import api, fields, models, tools, _
from sdwot.exceptions import UserError


class Currency(models.Model):
    _inherit = "res.currency"

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type in ('tree', 'form'):
            currency_name = (self.env['res.company'].browse(
                self._context.get('company_id')) or self.env.company.root_id).currency_id.name
            fields_maps = [
                [['company_rate', 'rate'], _('Unit per %s', currency_name)],
                [['inverse_company_rate', 'inverse_rate'], _('%s per Unit', currency_name)],
                [['buy_company_rate'], _('Buy Unit per %s', currency_name)],
                [['buy_inverse_company_rate'], _('%s per Buy Unit', currency_name)],
            ]
            for fnames, label in fields_maps:
                xpath_expression = '//tree//field[' + " or ".join(f"@name='{f}'" for f in fnames) + "][1]"
                node = arch.xpath(xpath_expression)
                if node:
                    node[0].set('string', label)
        return arch, view


class ExchangeRate(models.Model):
    _inherit = "res.currency.rate"

    buy_company_rate = fields.Float(
        string="Buy Rate",
        digits=0,
        help="The currency of rate 1 to the rate of the currency.",
    )
    buy_inverse_company_rate = fields.Float(
        string="Buy Exchange Rate",
        digits=0,
        help="The rate of the currency to the currency of rate 1 ",
    )
    _sql_constraints = [
        ('currency_rate_check', 'CHECK (buy_inverse_company_rate>0)', 'The currency rate must be strictly positive.'),
    ]

    @api.onchange('buy_company_rate')
    def _onchange_buy_company_rate(self):
        for line in self:
            if line.buy_company_rate > 0:
                line.buy_inverse_company_rate = 1 / line.buy_company_rate
            else:
                line.buy_inverse_company_rate = 0

    @api.onchange('buy_inverse_company_rate')
    def _onchange_buy_inverse_company_rate(self):
        for line in self:
            if line.buy_inverse_company_rate > 0:
                line.buy_company_rate = 1 / line.buy_inverse_company_rate
            else:
                line.buy_company_rate = 0
