# -*- coding: utf-8 -*-
# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr
from frappe.model.mapper import get_mapped_doc
from frappe.utils import getdate, get_time, get_datetime, combine_datetime


class CustomerFeedback(Document):
	def validate(self):
		self.set_missing_values()
		self.set_title()
		self.set_status()
		self.get_previous_values()

	def on_update(self):
		self.update_communication()

	@classmethod
	def get_allowed_party_types(cls):
		return ["Lead"]

	@frappe.whitelist()
	def determine_party_from_reference_name(self):
		if not self.get("reference_doctype") or not self.get("reference_name"):
			return

		self.determine_party_from_reference_document(frappe.get_doc(self.reference_doctype, self.reference_name))

	def determine_party_from_reference_document(self, source, throw=False):
		party_name_df = source.meta.get_field("party_name")

		if source.get("customer"):
			self.feedback_from = "Customer"
			self.party_name = source.get("customer")
		elif source.get("lead"):
			self.feedback_from = "Lead"
			self.party_name = source.get("lead")
		elif source.get("party_type") and source.get("party"):
			self.feedback_from = source.get("party_type")
			self.party_name = source.get("party")
		elif party_name_df and party_name_df.fieldtype == "Dynamic Link":
			self.feedback_from = source.get(party_name_df.options)
			self.party_name = source.get("party_name")
		else:
			self.party_name = None
			if throw:
				frappe.throw(_("Could not determine party from reference document {0}").format(
					frappe.get_desk_link(source.doctype, source.name)
				))

		if self.feedback_from and self.party_name:
			self.set_customer_name()

	def set_missing_values(self):
		self.set_customer_name()

	def set_customer_name(self):
		self.customer_name = get_customer_name(self.feedback_from, self.party_name)

	def set_title(self):
		self.title = self.customer_name or self.party_name

	def set_status(self):
		if self.customer_feedback:
			self.status = "Completed"
		else:
			self.status = "Pending"

	def get_previous_values(self):
		self.previous_values = {}
		if not self.is_new():
			self.previous_values = frappe.db.get_value(
				"Customer Feedback",
				self.name,
				["contact_remarks", "customer_feedback"],
				as_dict=True
			) or {}

	def update_communication(self):
		previous_values = self.get('previous_values') or {}
		if self.get("contact_remarks") and cstr(previous_values.get('contact_remarks')) != cstr(self.contact_remarks):
			self.make_communication_doc("contact_remarks", set_timeline_links=False).insert()

		if self.get("customer_feedback") and cstr(previous_values.get('customer_feedback')) != cstr(self.customer_feedback):
			self.make_communication_doc("customer_feedback", set_timeline_links=True).insert()

	def make_communication_doc(self, for_field, set_timeline_links):
		subject = _("Customer Feedback") + (_(" Remarks") if for_field == "contact_remarks" else "")

		if self.reference_doctype and self.reference_name:
			subject += " ({0})".format(self.reference_name)

		communication_doc = frappe.get_doc({
			"doctype": "Communication",
			"reference_doctype": self.get('doctype'),
			"reference_name": self.get('name'),
			"content": self.get(for_field),
			"communication_type": "Feedback",
			"sent_or_received": "Received",
			"subject": subject,
			"sender": frappe.session.user
		})

		if set_timeline_links:
			if self.reference_doctype and self.reference_name:
				communication_doc.append("timeline_links", {
					"link_doctype": self.reference_doctype,
					"link_name": self.reference_name
				})

			if self.feedback_from and self.party_name:
				communication_doc.append("timeline_links", {
					"link_doctype": self.feedback_from,
					"link_name": self.party_name,
				})

		communication_doc.flags.ignore_permissions = True
		return communication_doc


@frappe.whitelist()
def get_customer_name(feedback_from, party_name):
	if not feedback_from or not party_name:
		frappe.throw(_("Party is mandatory"))

	party = frappe.get_cached_doc(feedback_from, party_name)
	if party.doctype == "Lead":
		return party.company_name or party.lead_name
	else:
		return party.get("customer_name")


@frappe.whitelist()
def submit_customer_feedback(reference_doctype, reference_name, feedback_or_remark, message):
	if not message:
		frappe.throw(_('Message cannot be empty'))

	if not frappe.db.exists(reference_doctype, reference_name):
		frappe.throw(_("{0} {1} does not exist".format(reference_doctype, reference_name)))

	feedback_doc = get_customer_feedback_doc(reference_doctype, reference_name)

	cur_dt = get_datetime()
	cur_date = getdate(cur_dt)
	cur_time = get_time(cur_dt)

	if feedback_or_remark == "Feedback":
		feedback_doc.update({
			"feedback_date": cur_date,
			"feedback_time": cur_time,
			"customer_feedback": message
		})
	else:
		feedback_doc.update({
			"contact_date": cur_date,
			"contact_time": cur_time,
			"contact_remarks": message
		})

	feedback_doc.save()

	return {
		"contact_remarks": feedback_doc.get('contact_remarks'),
		"customer_feedback": feedback_doc.get('customer_feedback'),
		"contact_dt": combine_datetime(feedback_doc.contact_date, feedback_doc.contact_time)
			if feedback_doc.get('contact_remarks') else None,
		"feedback_dt": combine_datetime(feedback_doc.feedback_date, feedback_doc.feedback_time)
			if feedback_doc.get('customer_feedback') else None
	}


def get_customer_feedback_doc(reference_doctype, reference_name):
	filters = {
		'reference_doctype': reference_doctype,
		'reference_name': reference_name
	}

	customer_feedback = frappe.db.get_value("Customer Feedback", filters=filters)

	if customer_feedback:
		feedback_doc = frappe.get_doc("Customer Feedback", customer_feedback)
	else:
		feedback_doc = make_feedback_doc(reference_doctype, reference_name)

	return feedback_doc


def make_feedback_doc(reference_doctype, reference_name):
	def postprocess(source, target):
		target.determine_party_from_reference_document(source, throw=True)

	return get_mapped_doc(reference_doctype, reference_name, {
		reference_doctype: {
			"doctype": "Customer Feedback",
			"field_map": {
				"doctype": "reference_doctype",
				"name": "reference_name"
			}
		},
	}, postprocess=postprocess)
