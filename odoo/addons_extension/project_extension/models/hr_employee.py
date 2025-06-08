from odoo import models, fields, api
from odoo.exceptions import ValidationError

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    join_date = fields.Date(string="Date of Joining")
    total_working_hours = fields.Float(string="Total Working Hours", compute="compute_total_working_hours",store=True)
    billable_hrs = fields.Float(string="Billable Hours", tracking=True)
    non_billable_hrs = fields.Float(string="Non-Billable Hours", tracking=True)
    reason = fields.Text(string='Reason')

    @api.depends('join_date')
    def compute_total_working_hours(self):
        for employee in self:
            total_hours = 0.0
            if employee.join_date:
                today = fields.Date.today()
                current_year = today.year

                if employee.join_date.year == current_year:
                    from_date = employee.join_date
                    to_date = fields.Date.to_date(f"{current_year}-12-31")
                else:
                    from_date = fields.Date.to_date(f"{current_year}-01-01")
                    to_date = fields.Date.to_date(f"{current_year}-12-31")

                # calendar = employee.resource_id.calendar_id if employee.resource_id else None
                calendar = employee.resource_calendar_id if employee.resource_calendar_id else None
                if not calendar:
                    raise ValidationError(f"Employee {employee.name} does not have a calendar assigned")

                work_hours_per_day = self._get_work_hours_per_day(calendar)
                company_holiday_days = self._get_company_holiday_days(calendar, from_date, to_date)
                # employee_leave_days = self._get_employee_leaves(employee, from_date, to_date)

                # Calculate total days between from_date and to_date
                total_days = (to_date - from_date).days + 1  # +1 to include both start and end dates

                # working_days = total_days - company_holiday_days - employee_leave_days
                working_days = total_days - company_holiday_days
                if working_days < 0:
                    working_days = 0  # Just in case

                # Now total working hours = working_days * work_hours_per_day
                total_hours = working_days * work_hours_per_day

                employee.total_working_hours = total_hours
                employee.billable_hrs = total_hours * 0.8
                employee.non_billable_hrs = total_hours * 0.2

            else:
                employee.total_working_hours = total_hours

    def _get_work_hours_per_day(self, calendar):
        attendances = self.env['resource.calendar.attendance'].search(
            [('calendar_id', '=', calendar.id), ('dayofweek', 'in', [0, 1, 2, 3, 4, 5, 6])])
        attendances = attendances.filtered(lambda x: x.day_period == 'morning' or x.day_period == 'afternoon')
        total_work_hours = 0.0

        for attendance in attendances:
            total_work_hours += (attendance.hour_to - attendance.hour_from)

        weekdays_count = len(attendances) / 2
        return total_work_hours / weekdays_count if weekdays_count > 0 else 0.0

    def _get_employee_leaves(self, employee, date_from, date_to):
        leaves = self.env['hr.leave'].search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),  # Only approved leaves
            ('request_date_from', '<=', date_to),
            ('request_date_to', '>=', date_from),
        ])
        total_leave_days = sum(leave.number_of_days for leave in leaves)
        return total_leave_days

    def _get_company_holiday_days(self, calendar, date_from, date_to):
        holidays = self.env['resource.calendar.leaves'].search([
            ('calendar_id', '=', calendar.id),
            ('resource_id', '=', False),
            ('date_from', '<=', date_to),
            ('date_to', '>=', date_from),
        ])
        total_days = 0
        for holiday in holidays:
            holiday_start_dt = fields.Datetime.context_timestamp(self, holiday.date_from)
            holiday_end_dt = fields.Datetime.context_timestamp(self, holiday.date_to)
            holiday_start = max(holiday_start_dt.date(), date_from)
            holiday_end = min(holiday_end_dt.date(), date_to)
            total_days += (holiday_end - holiday_start).days + 1
        return total_days

    @api.onchange('billable_hrs')
    def _onchange_billable_hrs(self):
        for employee in self:
            if employee.total_working_hours:
                employee.non_billable_hrs = employee.total_working_hours - employee.billable_hrs
                if employee.non_billable_hrs < 0:
                    employee.non_billable_hrs = 0
                    employee.billable_hrs = employee.total_working_hours

    @api.onchange('non_billable_hrs')
    def _onchange_non_billable_hrs(self):
        for employee in self:
            if employee.total_working_hours:
                employee.billable_hrs = employee.total_working_hours - employee.non_billable_hrs
                if employee.billable_hrs < 0:
                    employee.billable_hrs = 0
                    employee.non_billable_hrs = employee.total_working_hours

    def write(self, vals):
        # if vals.get('non_billable_hrs') and vals.get('non_billable_hrs') and not vals.get('reason'):
        #     raise ValueError(f"Please Modify the Reason")
        if vals.get('reason'):
            self.message_post(body=vals.get('reason'))
        res = super().write(vals)
        return res
