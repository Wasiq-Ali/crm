import frappe
from frappe import _


def get_data():
	vehicle_domain_links = []
	vehicle_gate_pass_links = []
	if 'Vehicles' in frappe.get_active_domains():
		vehicle_domain_links.append({
			'label': _('Vehicle Booking'),
			'items': ['Vehicle Quotation', 'Vehicle Booking Order']
		})

		vehicle_gate_pass_links.append('Vehicle Gate Pass')

	return {
		'fieldname': 'opportunity',
		'transactions': vehicle_domain_links + [
			{
				'label': _("Pre Sales"),
				'items': ['Quotation', 'Supplier Quotation']
			},
			{
				'label': _("Reference"),
				'items': ['Appointment'] + vehicle_gate_pass_links
			},
		]
	}
