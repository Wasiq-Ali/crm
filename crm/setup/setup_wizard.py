import frappe
from frappe import _
from crm.setup.install_fixtures import get_default_records


def get_setup_stages(args=None):
	stages = [
		{
			'status': _('Installing CRM presets'),
			'fail_msg': _('Failed to install CRM presets'),
			'tasks': [
				{
					'fn': stage_fixtures,
					'args': args,
					'fail_msg': _("Failed to install presets")
				}
			]
		},
	]

	return stages


def stage_fixtures(args):
	create_default_records(args.get("country"))


def create_default_records(country):
	data = get_default_records(country)

	for doctype, records in data.items():
		if frappe.db.count(doctype):
			continue

		for d in records:
			doc = frappe.get_doc(d)
			doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
