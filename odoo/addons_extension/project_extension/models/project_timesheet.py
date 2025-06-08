from odoo import models, fields, api
from odoo.exceptions import ValidationError

class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    timesheet_type = fields.Selection([
        ('extra_hrs', 'Extra Hours'),
        ('billable', 'Billable'),
        ('non_billable', 'Non-Billable'),
    ], string="Type", default='non_billable')

    @api.constrains('employee_id', 'timesheet_type', 'task_id','unit_amount')
    def _check_timesheet_type_role(self):
        for record in self:
            if record.task_id and record.employee_id and record.project_id:
                user_id = record.employee_id.user_id.id
                assignees = record.task_id.user_ids.ids
                shadows = record.task_id.shadow_ids.ids

                if user_id in shadows and record.timesheet_type != 'non_billable':
                    raise ValidationError("Shadow persons can only log Non-Billable hours.")
                if user_id in assignees and record.timesheet_type == 'non_billable':
                    raise ValidationError("Assignees can select Billable or Extra hours.")
            else:
                if record.timesheet_type != 'non_billable':
                    raise ValidationError("Please non-billable.")
            all_lines = self.env['account.analytic.line'].search([('employee_id', '=', record.employee_id.id),('name', 'not ilike', 'Time Off')])
            total_task_hrs = record.task_id.allocated_hours
            billable_task_hrs = sum(record.task_id.timesheet_ids.filtered(lambda x: x.employee_id == record.employee_id and
                                                                           x.timesheet_type == 'billable' and
                                                                           'Time Off' not in x.name).mapped('unit_amount'))
            if billable_task_hrs > total_task_hrs:
                raise ValidationError(f"The Billable hours ({billable_task_hrs}) should not greater than Allocated Time ({total_task_hrs})")

            non_billable_task_hrs = sum(record.task_id.timesheet_ids.filtered(lambda x: x.employee_id == record.employee_id
                                                                                and x.timesheet_type=='non_billable'
                                                                                and 'Time Off' not in x.name).mapped('unit_amount'))
            employee_non_billable_hrs = sum(l.unit_amount for l in all_lines if l.timesheet_type == 'non_billable')
            total_non_billable_hrs = record.employee_id.non_billable_hrs

            if non_billable_task_hrs > total_task_hrs and 'Time Off' not in record.task_id.name:
                raise ValidationError(f"The Non-Billable hours ({non_billable_task_hrs}) should not greater than Allocated Time ({total_task_hrs})")

            if employee_non_billable_hrs > total_non_billable_hrs:

                raise ValidationError(f"The Total Non-billable hours ({employee_non_billable_hrs}) should not be greater than the calendar year Non-billable hours ({total_non_billable_hrs}).")

class Task(models.Model):
    _inherit = "project.task"

    shadow_ids = fields.Many2many('res.users', string='Shadow persons')

class ResourceCalendar(models.Model):
    _inherit = 'resource.calendar'

    @api.model
    def write(self, vals):
        result = super().write(vals)
        if self.global_leave_ids:
            for employee in self.env['hr.employee'].search([('resource_calendar_id', '=',self.id)]):
                employee.compute_total_working_hours()
        return result

class HrLeave(models.Model):
    _inherit = 'hr.leave'

    def action_validate(self, check_state=True):
        # self.employee_id.compute_total_working_hours()
        res = super().action_validate(check_state)
        return res