from odoo import models, fields, api

class Lead(models.Model):
    _inherit = "crm.lead"

    def action_set_won_rainbowman(self):
        if 'skip_won' not in self._context:
            crm_id = self.env['won.wizard'].create({'crm_id':self.id})
            view_id = self.env.ref('project_extension.view_won_wizard').id
            return {
                'type': 'ir.actions.act_window',
                'name': 'Create a Project',
                'res_model': 'won.wizard',
                'view_mode': 'form',
                'res_id': crm_id.id,
                'views': [[view_id, 'form']],
                'target': 'new',
                }
        else:
            return super(Lead, self).action_set_won_rainbowman()

class WonWizard(models.TransientModel):
    _name = 'won.wizard'
    _description = 'Confirmation Wizard'

    name = fields.Char(string='Title')
    project_type = fields.Selection(selection=[('existing', 'Existing'),('new', 'New')],string="Project Type",default='new')
    project_id = fields.Many2one('project.project',string='Related Project')
    crm_id = fields.Many2one('crm.lead',string="Lead")

    def action_confirm_won(self):
        if self.project_type == 'new':
            self.env['project.project'].create({'name' : self.name})
        elif self.project_type == 'existing':
            self.env['project.task'].create({'display_name' : self.name, 'project_id' : self.project_id.id})
        self.crm_id.with_context(skip_won = True).action_set_won_rainbowman()