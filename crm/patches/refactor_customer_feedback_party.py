import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	frappe.db.sql("""
		update `tabCustomer Feedback`
		set feedback_from = 'Customer'
	""")

	if frappe.db.has_column("Customer Feedback", "customer"):
		rename_field("Customer Feedback", "customer", "party_name")
