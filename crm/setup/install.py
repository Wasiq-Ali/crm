import frappe
from crm.setup.install_fixtures import create_default_records


def after_install():
	# install fixtures from installer rather than setup wizard if setup is already completed
	if frappe.db.get_single_value("System Settings", "setup_complete"):
		create_default_records(frappe.db.get_single_value("System Settings", "country"))
