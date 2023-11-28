# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.utils.nestedset import NestedSet, get_root_of


class SalesPerson(NestedSet):
	nsm_parent_field = 'parent_sales_person'

	def validate(self):
		if not self.parent_sales_person:
			self.parent_sales_person = get_root_of("Sales Person")

	def on_update(self):
		super(SalesPerson, self).on_update()
		self.validate_one_root()

	@staticmethod
	def get_timeline_data(name):
		out = dict(frappe.db.sql("""
			select unix_timestamp(dt.transaction_date), count(dt.name)
			from `tabOpportunity` dt
			where dt.sales_person = %s and dt.transaction_date > date_sub(curdate(), interval 1 year)
			group by dt.transaction_date
		""", name))

		return out


def on_doctype_update():
	frappe.db.add_index("Sales Person", ["lft", "rgt"])


@frappe.whitelist()
def get_sales_person_from_user():
	return frappe.db.get_value("Sales Person", {"user_id": frappe.session.user, "enabled": 1})
