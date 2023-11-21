import frappe
from crm.setup.install_fixtures import get_default_records


def after_install():
	create_default_records()


def create_default_records():
	data = get_default_records()

	for doctype, records in data.items():
		if frappe.db.count(doctype):
			continue

		for d in records:
			doc = frappe.get_doc(d)
			doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
