import frappe


def execute():
	rename_map = {
		"Projects Manager": "Service Manager",
		"Projects User": "Service User",
		"Projects User (Read Only)": "Service User (Read Only)",
	}
	for old, new in rename_map.items():
		if frappe.db.exists("Role", old):
			frappe.rename_doc("Role", old, new, force=True)
