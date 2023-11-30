import frappe


def execute():
	frappe.db.sql("""
		update `tabLead`
		set status = 'Opportunity'
		where status = 'Quotation'
	""")

	frappe.db.sql("""
		update `tabLead`
		set status = 'Lost Opportunity'
		where status = 'Lost Quotation'
	""")

	frappe.db.sql("""
		update `tabLead`
		set status = 'Open'
		where status = 'Lead'
	""")
