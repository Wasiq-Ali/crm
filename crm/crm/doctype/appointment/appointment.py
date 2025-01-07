# -*- coding: utf-8 -*-
# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
import erpnext
from frappe import _
from frappe.utils.status_updater import StatusUpdater
from frappe.utils import (
	cint, today, getdate, get_time, get_datetime, combine_datetime, date_diff, comma_or,
	format_datetime, formatdate, now_datetime, add_days, clean_whitespace
)
from frappe.contacts.doctype.address.address import get_default_address
from frappe.contacts.doctype.contact.contact import get_default_contact, get_all_contact_nos
from crm.crm.utils import get_contact_details, get_address_display
from frappe.core.doctype.sms_settings.sms_settings import enqueue_template_sms
from frappe.core.doctype.notification_count.notification_count import get_all_notification_count
from frappe.model.mapper import get_mapped_doc
import datetime
import json


class Appointment(StatusUpdater):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.force_party_fields = [
			'customer_name', 'tax_id', 'tax_cnic', 'tax_strn',
			'address_display', 'contact_display', 'contact_email', 'secondary_contact_display',
		]

	def get_feed(self):
		return _("For {0}").format(self.get("customer_name") or self.get('party_name'))

	def onload(self):
		if self.docstatus == 0:
			self.set_missing_values()
		elif self.docstatus == 1:
			self.set_onload('disallow_on_submit', self.get_disallow_on_submit_fields())

		self.set_onload('appointment_timeslots_data', get_appointment_timeslots(self.scheduled_date, self.appointment_type))
		self.set_onload('contact_nos', get_all_contact_nos(self.appointment_for, self.party_name))
		self.set_onload('notification_count', get_all_notification_count(self.doctype, self.name))

		self.set_can_notify_onload()
		self.set_scheduled_reminder_onload()

	def validate(self):
		self.set_missing_values()
		self.validate_previous_appointment()
		self.validate_timeslot_validity()
		self.validate_sales_person_availability()
		self.validate_timeslot_availability()
		self.clean_remarks()
		self.set_status()

	def before_update_after_submit(self):
		if self.status not in ["Closed", "Rescheduled"]:
			self.set_missing_values_after_submit()

		self.validate_sales_person_mandatory()
		self.validate_sales_person_availability()
		self.clean_remarks()
		self.set_status()
		self.get_disallow_on_submit_fields()

	def before_submit(self):
		self.validate_sales_person_mandatory()
		self.confirmation_dt = now_datetime()

	def on_submit(self):
		self.update_previous_appointment()
		self.update_opportunity_status()
		self.create_calendar_event(update=True)
		self.send_appointment_confirmation_notification()

	def on_cancel(self):
		self.db_set('status', 'Cancelled')
		self.validate_next_document_on_cancel()
		self.update_opportunity_status()
		self.send_appointment_cancellation_notification()

	def before_print(self, print_settings=None):
		self.company_address_doc = erpnext.get_company_address_doc(self)

	def after_delete(self):
		self.update_previous_appointment()
		self.update_opportunity_status()

	@classmethod
	def get_allowed_party_types(cls):
		return ["Lead"]

	@classmethod
	def validate_appointment_for(cls, appointment_for):
		allowed_party_types = cls.get_allowed_party_types()
		if appointment_for not in allowed_party_types:
			frappe.throw(_("Appointment For must be {0}").format(comma_or(allowed_party_types)))

	def get_disallow_on_submit_fields(self):
		if self.status in ["Closed", "Rescheduled"]:
			self.flags.disallow_on_submit = self.get_fields_for_disallow_on_submit(['remarks'])

		return self.flags.disallow_on_submit or []

	def set_missing_values(self):
		self.set_previous_appointment_details()
		self.set_missing_duration()
		self.set_scheduled_date_time()
		self.set_customer_details()

	def set_missing_values_after_submit(self):
		self.set_customer_details()

	def set_previous_appointment_details(self):
		if self.previous_appointment:
			self.previous_appointment_dt = frappe.db.get_value("Appointment", self.previous_appointment, "scheduled_dt")
		else:
			self.previous_appointment_dt = None

	def set_missing_duration(self):
		if self.get('appointment_type'):
			appointment_type_doc = frappe.get_cached_doc("Appointment Type", self.appointment_type)
			if cint(self.appointment_duration) <= 0:
				self.appointment_duration = cint(appointment_type_doc.appointment_duration)

	def set_scheduled_date_time(self):
		if not self.scheduled_dt and self.scheduled_date and self.scheduled_time:
			self.scheduled_dt = combine_datetime(self.scheduled_date, self.scheduled_time)

		if self.scheduled_dt:
			self.scheduled_dt = get_datetime(self.scheduled_dt)
			self.scheduled_date = getdate(self.scheduled_dt)
			self.scheduled_time = get_time(self.scheduled_dt)
		else:
			self.scheduled_date = None
			self.scheduled_time = None

		self.appointment_duration = cint(self.appointment_duration)
		if self.scheduled_dt and self.appointment_duration > 0:
			duration = datetime.timedelta(minutes=self.appointment_duration)
			self.end_dt = self.scheduled_dt + duration
		else:
			self.end_dt = self.scheduled_dt

		if self.scheduled_date:
			self.scheduled_day_of_week = formatdate(self.scheduled_date, "EEEE")
		else:
			self.scheduled_day_of_week = None

	def set_customer_details(self):
		customer_details = get_customer_details(self.as_dict())
		for k, v in customer_details.items():
			if self.meta.has_field(k) and (not self.get(k) or k in self.force_party_fields):
				self.set(k, v)

	def clean_remarks(self):
		fields = ['remarks']

		if self.status not in ["Closed", "Rescheduled"]:
			fields.append('voice_of_customer')

		for f in fields:
			if self.meta.has_field(f):
				self.set(f, clean_whitespace(self.get(f)))

	def validate_timeslot_validity(self):
		if not self.appointment_type:
			return

		appointment_type_doc = frappe.get_cached_doc("Appointment Type", self.appointment_type)

		# check if in past
		if get_datetime(self.end_dt) < now_datetime():
			timeslot_str = self.get_timeslot_str()
			frappe.msgprint(_("Time slot {0} is in the past").format(
				timeslot_str
			), raise_exception=appointment_type_doc.validate_past_timeslot)

		advance_days = date_diff(getdate(self.scheduled_dt), today())
		if cint(appointment_type_doc.advance_booking_days) and advance_days > cint(appointment_type_doc.advance_booking_days):
			frappe.msgprint(_("Scheduled Date {0} is {1} days in advance")
				.format(frappe.bold(frappe.format(getdate(self.scheduled_date))), frappe.bold(advance_days)),
				raise_exception=appointment_type_doc.validate_availability)

		# check if in valid timeslot
		if not appointment_type_doc.is_in_timeslot(self.scheduled_dt, self.end_dt):
			timeslot_str = self.get_timeslot_str()
			frappe.msgprint(_('{0} is not a valid available time slot for appointment type {1}')
				.format(timeslot_str, self.appointment_type), raise_exception=appointment_type_doc.validate_availability)

	def validate_timeslot_availability(self):
		if not self.appointment_type:
			return

		appointment_type_doc = frappe.get_cached_doc("Appointment Type", self.appointment_type)

		# check if holiday
		holiday = appointment_type_doc.is_holiday(self.scheduled_dt)
		if holiday:
			frappe.msgprint(_("{0} is a holiday: {1}").format(
				frappe.bold(formatdate(self.scheduled_dt, "EEEE, d MMMM, y")), holiday
			), raise_exception=appointment_type_doc.validate_availability)

		# check if already booked
		appointments_in_slot = count_appointments_in_slot(self.scheduled_dt, self.end_dt,
			self.appointment_type, appointment=self.name if not self.is_new() else None)
		no_of_agents = cint(appointment_type_doc.number_of_agents)

		if no_of_agents and appointments_in_slot >= no_of_agents:
			timeslot_str = self.get_timeslot_str()
			frappe.msgprint(_('Time slot {0} is already booked by {1} other appointments for appointment type {2}').format(
				timeslot_str, frappe.bold(appointments_in_slot), self.appointment_type
			), raise_exception=appointment_type_doc.validate_availability)

	def validate_sales_person_mandatory(self):
		if not self.appointment_type:
			return

		appointment_type_doc = frappe.get_cached_doc("Appointment Type", self.appointment_type)
		if not self.sales_person and appointment_type_doc.sales_person_mandatory:
			frappe.throw(_("{0} is mandatory for appointment confirmation").format(self.meta.get_label("sales_person")))

	def validate_sales_person_availability(self):
		appointment_type_doc = frappe.get_cached_doc("Appointment Type", self.appointment_type) \
			if self.appointment_type else frappe._dict()

		if self.sales_person:
			# Check allowed sales persons
			allowed_sales_persons = get_allowed_sales_persons(self.appointment_type)
			if allowed_sales_persons and self.sales_person not in allowed_sales_persons:
				frappe.msgprint(_("{0} is not a valid {1} for appointment type {2}").format(
					frappe.bold(self.sales_person),
					self.meta.get_label("sales_person"),
					self.appointment_type,
				), raise_exception=appointment_type_doc.validate_sales_person_availability)

			# Check if not already booked
			appointments_in_slot = get_appointments_in_slot(self.scheduled_dt, self.end_dt,
				sales_person=self.sales_person,
				appointment=self.name if not self.is_new() else None
			)
			if appointments_in_slot:
				conflict_appointment = appointments_in_slot[0].name
				timeslot_str = self.get_timeslot_str()
				frappe.msgprint(_("{0} {1} is already assigned to another {2} for time slot {3}").format(
					self.meta.get_label("sales_person"),
					frappe.bold(self.sales_person),
					frappe.get_desk_link("Appointment", conflict_appointment),
					timeslot_str,
				), raise_exception=appointment_type_doc.validate_sales_person_availability)

	def validate_previous_appointment(self):
		if self.previous_appointment:
			previous_appointment = frappe.db.get_value("Appointment", self.previous_appointment,
				['docstatus', 'status'], as_dict=1)
			if not previous_appointment:
				frappe.throw(_("Previous Appointment {0} does not exist").format(self.previous_appointment))

			if previous_appointment.docstatus == 0:
				frappe.throw(_("Previous {0} is not submitted")
					.format(frappe.get_desk_link("Appointment", self.previous_appointment)))
			if previous_appointment.docstatus == 2:
				frappe.throw(_("Previous {0} is cancelled")
					.format(frappe.get_desk_link("Appointment", self.previous_appointment)))
			if previous_appointment.status not in ["Open", "Checked In", "Missed"] and not self.amended_from:
				frappe.throw(_("Previous {0} is {1}. Only Open and Missed appointments can be resheduled")
					.format(frappe.get_desk_link("Appointment", self.previous_appointment), previous_appointment.status))

	def update_previous_appointment(self):
		if self.previous_appointment:
			doc = frappe.get_doc("Appointment", self.previous_appointment)
			doc.set_status(update=True)
			doc.notify_update()

	def validate_next_document_on_cancel(self):
		pass

	def create_lead_and_link(self):
		if self.party_name:
			return

		lead = frappe.get_doc({
			'doctype': 'Lead',
			'lead_name': self.customer_name,
			'email_id': self.contact_email,
			'notes': self.description,
			'mobile_no': self.contact_mobile,
		})
		lead.insert(ignore_permissions=True)

		self.appointment_for = "Lead"
		self.party_name = lead.name

	def create_calendar_event(self, update=False):
		if self.status != "Open":
			return
		if self.calendar_event:
			return
		if not self.appointment_type:
			return

		appointment_type_doc = frappe.get_cached_doc("Appointment Type", self.appointment_type)
		if not appointment_type_doc.create_calendar_event:
			return

		event_participants = []
		if self.get('appointment_for') and self.get('party_name'):
			event_participants.append({"reference_doctype": self.appointment_for, "reference_docname": self.party_name})

		appointment_event = frappe.get_doc({
			'doctype': 'Event',
			'subject': ' '.join(['Appointment with', self.customer_name]),
			'starts_on': self.scheduled_dt,
			'ends_on': self.end_dt,
			'status': 'Open',
			'type': 'Public',
			'send_reminder': appointment_type_doc.email_reminders,
			'event_participants': event_participants
		})

		if self.sales_person:
			appointment_event.append('event_participants', dict(
				reference_doctype='Sales Person',
				reference_docname=self.sales_person
			))

		appointment_event.insert(ignore_permissions=True)

		self.calendar_event = appointment_event.name
		if update:
			self.db_set('calendar_event', self.calendar_event)

	def sync_calendar_event(self):
		if not self.calendar_event:
			return

		cal_event = frappe.get_doc('Event', self.calendar_event)
		cal_event.starts_on = self.scheduled_dt
		cal_event.end_on = self.end_dt
		cal_event.save(ignore_permissions=True)

	def set_status(self, update=False, status=None, update_modified=True):
		previous_status = self.status
		previous_is_closed = self.is_closed
		previous_is_missed = self.is_missed
		previous_is_checked_in = self.is_checked_in
		previous_check_in_dt = self.check_in_dt

		if self.docstatus == 0:
			self.status = "Draft"

		elif self.docstatus == 1:
			if status == "Open":
				self.is_checked_in = 0
				self.is_closed = 0
				self.is_missed = 0
			elif status == "Closed":
				self.is_closed = 1
				self.is_missed = 0
			elif status == "Missed":
				self.is_missed = 1
				self.is_closed = 0
			elif status == "Checked In":
				self.is_checked_in = 1
				self.is_missed = 0

			# Submitted or cancelled rescheduled appointment
			is_rescheduled = frappe.get_all("Appointment", filters={'previous_appointment': self.name, 'docstatus': ['>', 0]})

			if is_rescheduled:
				self.status = "Rescheduled"
			elif self.is_appointment_closed():
				self.status = "Closed"
			elif self.is_checked_in:
				self.status = "Checked In"
			elif self.is_missed or getdate(today()) > getdate(self.scheduled_date):
				self.status = "Missed"
			else:
				self.status = "Open"

		else:
			self.status = "Cancelled"

		if not previous_is_checked_in and self.is_checked_in:
			self.check_in_dt = now_datetime()
			self.check_in_user = frappe.session.user
		if not self.is_checked_in:
			self.check_in_dt = None
			self.check_in_user = None

		self.add_status_comment(previous_status)

		if update:
			if (
				previous_status != self.status
				or previous_is_closed != self.is_closed
				or previous_is_missed != self.is_missed
				or previous_is_checked_in != self.is_checked_in
				or previous_check_in_dt != self.check_in_dt
			):
				self.db_set({
					'status': self.status,
					'is_checked_in': self.is_checked_in,
					'is_closed': self.is_closed,
					'is_missed': self.is_missed,
					'check_in_dt': self.check_in_dt,
					'check_in_user': self.check_in_user,
				}, update_modified=update_modified)

	def is_appointment_closed(self):
		return cint(self.is_closed)

	def get_timeslot_str(self):
		if self.scheduled_dt == self.end_dt:
			timeslot_str = frappe.bold(self.get_formatted_dt())
		elif getdate(self.scheduled_dt) == getdate(self.end_dt):
			timeslot_str = _("{0} {1} till {2}").format(
				frappe.bold(format_datetime(self.scheduled_dt, "EEEE, d MMMM, y")),
				frappe.bold(format_datetime(self.scheduled_dt, "hh:mm:ss a")),
				frappe.bold(format_datetime(self.end_dt, "hh:mm:ss a"))
			)
		else:
			timeslot_str = _("{0} till {1}").format(
				frappe.bold(self.get_formatted('scheduled_dt')),
				frappe.bold(self.get_formatted('end_dt'))
			)

		return timeslot_str

	def get_formatted_dt(self, dt=None):
		if not dt:
			dt = self.scheduled_dt

		if dt:
			return format_datetime(self.scheduled_dt, "EEEE, d MMMM, y hh:mm:ss a")
		else:
			return ""

	def get_sms_args(self, notification_type=None, child_doctype=None, child_name=None):
		return frappe._dict({
			'receiver_list': [self.contact_mobile],
			'party_doctype': self.appointment_for,
			'party': self.party_name
		})

	def set_can_notify_onload(self):
		notification_types = [
			'Appointment Confirmation',
			'Appointment Reminder',
			'Appointment Cancellation',
		]

		can_notify = frappe._dict()
		for notification_type in notification_types:
			can_notify[notification_type] = self.validate_notification(notification_type, throw=False)

		self.set_onload('can_notify', can_notify)

	def set_scheduled_reminder_onload(self):
		self.set_onload('scheduled_reminder', self.get_reminder_schedule())

	def get_reminder_schedule(self):
		if self.docstatus != 1 or not self.scheduled_date or not automated_reminder_enabled():
			return None

		reminder_date = get_reminder_date_from_appointment_date(self.scheduled_date)
		appointments_for_reminder = get_appointments_for_reminder_notification(reminder_date, appointments=self.name)

		if self.name in appointments_for_reminder:
			return get_appointment_reminders_scheduled_time(reminder_date)

	def validate_notification(self, notification_type=None, child_doctype=None, child_name=None, throw=False):
		if not notification_type:
			if throw:
				frappe.throw(_("Notification Type is mandatory"))
			return False

		if notification_type == 'Appointment Cancellation':
			# Must be cancelled
			if self.docstatus != 2:
				if throw:
					frappe.throw(_("Cannot send Appointment Cancellation notification because Appointment is not cancelled"))
				return False
		elif notification_type != 'Custom Message':
			# Must be submitted
			if self.docstatus != 1:
				if throw:
					frappe.throw(_("Cannot send notification because Appointment is not submitted"))
				return False

		# Must be Open
		if notification_type in ("Appointment Confirmation", "Appointment Reminder"):
			if self.status != "Open":
				if throw:
					frappe.throw(_("Cannot send {0} notification because Appointment status is not 'Open'")
						.format(notification_type))
				return False

		# Appointment Start Date/Time is in the past or End Date/Time if cancellation
		if notification_type in ("Appointment Confirmation", "Appointment Reminder", "Appointment Cancellation"):
			appointment_dt = self.end_dt if "Appointment Cancellation" else self.scheduled_dt
			appointment_dt = get_datetime(appointment_dt or self.scheduled_dt)

			if appointment_dt <= now_datetime():
				if throw:
					frappe.throw(_("Cannot send {0} notification after Appointment Time has passed")
						.format(notification_type))
				return False

		return True

	def update_opportunity_status(self):
		if self.opportunity:
			doc = frappe.get_doc("Opportunity", self.opportunity)
			doc.set_status(update=True)
			doc.update_lead_status()
			doc.notify_update()

	def send_appointment_confirmation_notification(self):
		if not self.dont_send_automated_notification():
			enqueue_template_sms(self, notification_type="Appointment Confirmation")

	def send_appointment_cancellation_notification(self):
		if not self.dont_send_automated_notification():
			enqueue_template_sms(self, notification_type="Appointment Cancellation")

	def send_appointment_reminder_notification(self):
		if not self.dont_send_automated_notification():
			enqueue_template_sms(self, notification_type="Appointment Reminder")

	def dont_send_automated_notification(self):
		return cint(frappe.get_cached_value("Appointment Source", self.appointment_source,
			"disable_automated_notifications"))


@frappe.whitelist()
def get_appointment_timeslots(scheduled_date, appointment_type, appointment=None):
	out = frappe._dict({
		'holiday': None,
		'timeslots': []
	})

	if not scheduled_date or not appointment_type:
		return out

	scheduled_date = getdate(scheduled_date)
	appointment_type_doc = frappe.get_cached_doc("Appointment Type", appointment_type)

	out.holiday = appointment_type_doc.is_holiday(scheduled_date)

	timeslots = appointment_type_doc.get_timeslots(scheduled_date)
	no_of_agents = cint(appointment_type_doc.number_of_agents)

	if timeslots:
		for timeslot_start, timeslot_end in timeslots:
			appointments_in_slots = count_appointments_in_slot(timeslot_start, timeslot_end, appointment_type,
				appointment)

			timeslot_data = {
				'timeslot_start': timeslot_start,
				'timeslot_end': timeslot_end,
				'timeslot_duration': round((timeslot_end - timeslot_start) / datetime.timedelta(minutes=1)),
				'number_of_agents': no_of_agents,
				'booked': appointments_in_slots,
				'available': max(0, no_of_agents - appointments_in_slots)
			}
			out.timeslots.append(timeslot_data)

	elif timeslots is None:
		out.timeslots = None

	return out


def get_allowed_sales_persons(appointment_type):
	if not appointment_type:
		return []

	appointment_type_doc = frappe.get_cached_doc('Appointment Type', appointment_type)
	return appointment_type_doc.get_sales_persons()


def count_appointments_in_slot(start_dt, end_dt, appointment_type, appointment=None):
	appointments = get_appointments_in_slot(
		start_dt,
		end_dt,
		appointment_type=appointment_type,
		appointment=appointment
	)
	return len(appointments) if appointments else 0


def get_appointments_in_slot(start_dt, end_dt, appointment_type=None, appointment=None, sales_person=None):
	start_dt = get_datetime(start_dt)
	end_dt = get_datetime(end_dt)

	appointment_type_condition = ""
	if appointment_type:
		appointment_type_condition = "and appointment_type = %(appointment_type)s"

	sales_person_condition = ""
	if sales_person:
		sales_person_condition = "and sales_person = %(sales_person)s"

	exclude_condition = ""
	if appointment:
		exclude_condition = "and name != %(appointment)s"

	appointments = frappe.db.sql(f"""
		select name, sales_person
		from `tabAppointment`
		where docstatus = 1 and status != 'Rescheduled'
			and %(start_dt)s < end_dt AND %(end_dt)s > scheduled_dt
			{appointment_type_condition}
			{sales_person_condition}
			{exclude_condition}
	""", {
		'start_dt': start_dt,
		'end_dt': end_dt,
		'appointment_type': appointment_type,
		'appointment': appointment,
		'sales_person': sales_person,
	}, as_dict=1)

	return appointments


def auto_mark_missed():
	auto_mark_missed_days = cint(frappe.get_cached_value("Appointment Booking Settings", None, "auto_mark_missed_days"))
	if auto_mark_missed_days > 0:
		frappe.db.sql("""
			update `tabAppointment`
			set status = 'Missed'
			where docstatus = 1 and status = 'Open' and DATEDIFF(CURDATE(), scheduled_date) >= %s
		""", auto_mark_missed_days)


@frappe.whitelist()
def get_customer_details(args):
	from frappe.model.base_document import get_controller

	if isinstance(args, str):
		args = json.loads(args)

	args = frappe._dict(args)
	out = frappe._dict()

	if not args.appointment_for or not args.party_name:
		party = frappe._dict()
	else:
		appointment_controler = get_controller("Appointment")
		appointment_controler.validate_appointment_for(args.appointment_for)

		party = frappe.get_cached_doc(args.appointment_for, args.party_name)

	# Customer Name
	if party.doctype == "Lead":
		out.customer_name = party.company_name or party.lead_name
	else:
		out.customer_name = party.get("customer_name")

	# Tax IDs
	out.tax_id = party.get('tax_id')
	out.tax_cnic = party.get('tax_cnic')
	out.tax_strn = party.get('tax_strn')

	lead = party if party.doctype == "Lead" else None

	# Address
	out.customer_address = args.customer_address
	if not out.customer_address and party.doctype != "Lead":
		out.customer_address = get_default_address(party.doctype, party.name)

	out.address_display = get_address_display(out.customer_address, lead=lead)

	# Contact
	out.contact_person = args.contact_person
	if not out.contact_person and party.doctype != "Lead":
		out.contact_person = get_default_contact(party.doctype, party.name)

	out.update(get_contact_details(out.contact_person, lead=lead))

	out.secondary_contact_person = args.secondary_contact_person
	secondary_contact_details = get_contact_details(out.secondary_contact_person)
	secondary_contact_details = {"secondary_" + k: v for k, v in secondary_contact_details.items()}
	out.update(secondary_contact_details)

	out.contact_nos = get_all_contact_nos(party.doctype, party.name)

	return out


@frappe.whitelist()
def get_rescheduled_appointment(source_name, target_doc=None):
	def set_missing_values(source, target):
		target.run_method("set_missing_values")

	mapper = {
		"Appointment": {
			"doctype": "Appointment",
			"field_no_map": [
				'scheduled_date',
				'scheduled_time',
				'scheduled_day_of_week',
				'scheduled_dt',
				'end_dt',
			],
			"field_map": {
				"name": "previous_appointment",
				"scheduled_dt": "previous_appointment_dt",
				"appointment_duration": "appointment_duration",
				"appointment_type": "appointment_type",
				"appointment_for": "appointment_for",
				"party_name": "party_name",
				"contact_person": "contact_person",
				"customer_address": "customer_address",
				"voice_of_customer": "voice_of_customer",
				"description": "description",
			}
		},
		"postprocess": set_missing_values,
	}

	frappe.utils.call_hook_method("update_reschedule_appointment_mapper", mapper, "Appointment")

	doclist = get_mapped_doc("Appointment", source_name, mapper, target_doc)

	return doclist


@frappe.whitelist()
def update_status(appointment, status):
	doc = frappe.get_doc("Appointment", appointment)
	doc.check_permission('write')
	doc.set_status(update=True, status=status)
	doc.notify_update()


def send_appointment_reminder_notifications():
	if not automated_reminder_enabled():
		return

	# Do not send until reminder scheduled time has passed
	now_dt = now_datetime()
	reminder_date = getdate(now_dt)
	reminder_dt = get_appointment_reminders_scheduled_time(reminder_date)
	if now_dt < reminder_dt:
		return

	notification_last_sent_date = frappe.db.get_global("appointment_reminder_notification_last_sent_date")
	if notification_last_sent_date and getdate(notification_last_sent_date) >= reminder_date:
		return

	appointments_to_remind = get_appointments_for_reminder_notification(reminder_date)

	for name in appointments_to_remind:
		doc = frappe.get_doc("Appointment", name)
		doc.send_appointment_reminder_notification()

	frappe.db.set_global("appointment_reminder_notification_last_sent_date", reminder_date)


def automated_reminder_enabled():
	from frappe.core.doctype.sms_settings.sms_settings import is_automated_sms_enabled
	from frappe.core.doctype.sms_template.sms_template import has_automated_sms_template

	if is_automated_sms_enabled() and has_automated_sms_template("Appointment", "Appointment Reminder"):
		return True
	else:
		return False


def get_appointments_for_reminder_notification(reminder_date=None, appointments=None):
	appointment_settings = frappe.get_cached_doc("Appointment Booking Settings", None)

	now_dt = now_datetime()
	reminder_date = getdate(reminder_date)
	reminder_dt = get_appointment_reminders_scheduled_time(reminder_date)

	remind_days_before = cint(appointment_settings.appointment_reminder_days_before)
	if remind_days_before < 0:
		remind_days_before = 0

	appointment_reminder_confirmation_hours = cint(appointment_settings.appointment_reminder_confirmation_hours)
	if appointment_reminder_confirmation_hours < 0:
		appointment_reminder_confirmation_hours = 0

	appointment_date = add_days(reminder_date, remind_days_before)

	if appointments and isinstance(appointments, str):
		appointments = [appointments]

	appointments_condition = " and a.name in %(appointments)s" if appointments else ""

	appointments_to_remind = frappe.db.sql_list("""
		select a.name
		from `tabAppointment` a
		left join `tabNotification Count` n on n.reference_doctype = 'Appointment' and n.reference_name = a.name
			and n.notification_type = 'Appointment Reminder' and n.notification_medium = 'SMS'
		where a.docstatus = 1
			and a.status = 'Open'
			and a.scheduled_date = %(appointment_date)s
			and %(reminder_dt)s < a.scheduled_dt
			and %(now_dt)s < a.scheduled_dt
			and TIMESTAMPDIFF(MINUTE, a.confirmation_dt, %(reminder_dt)s) >= %(required_minutes)s
			and n.last_scheduled_dt is null
			and (n.last_sent_dt is null or DATE(n.last_sent_dt) != %(reminder_date)s)
			{0}
	""".format(appointments_condition), {
		'appointment_date': appointment_date,
		'reminder_dt': reminder_dt,
		'reminder_date': reminder_date,
		'now_dt': now_dt,
		'required_minutes': appointment_reminder_confirmation_hours * 60,
		'appointments': appointments,
	})

	return appointments_to_remind


def get_appointment_reminders_scheduled_time(reminder_date=None):
	appointment_settings = frappe.get_cached_doc("Appointment Booking Settings", None)

	reminder_date = getdate(reminder_date)
	reminder_time = appointment_settings.appointment_reminder_time or get_time("00:00:00")
	reminder_dt = combine_datetime(reminder_date, reminder_time)

	return reminder_dt


def get_reminder_date_from_appointment_date(appointment_date):
	appointment_settings = frappe.get_cached_doc("Appointment Booking Settings", None)

	appointment_date = getdate(appointment_date)

	remind_days_before = cint(appointment_settings.appointment_reminder_days_before)
	if remind_days_before < 0:
		remind_days_before = 0

	reminder_date = add_days(appointment_date, -remind_days_before)
	return reminder_date


@frappe.whitelist()
def get_events(start, end, filters=None):
	from frappe.desk.calendar import get_event_conditions
	conditions = get_event_conditions("Appointment", filters)

	data = frappe.db.sql("""
		select
			`tabAppointment`.name, `tabAppointment`.customer_name, `tabAppointment`.status,
			`tabAppointment`.scheduled_dt, `tabAppointment`.end_dt, `tabAppointment`.status
		from
			`tabAppointment`
		where ifnull(`tabAppointment`.scheduled_dt, '0000-00-00') != '0000-00-00'
			and `tabAppointment`.scheduled_dt between %(start)s and %(end)s
			and `tabAppointment`.docstatus < 2
			{conditions}
		""".format(conditions=conditions), {
			"start": start,
			"end": end
		}, as_dict=True, update={"allDay": 0})

	return data


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def appointment_sales_person_query(doctype, txt, searchfield, start, page_len, filters):
	from crm.queries import get_fields
	from frappe.desk.reportview import get_match_cond, get_filters_cond

	conditions = []
	fields = get_fields("Sales Person")
	fields_str = ", ".join([f"`tabSales Person`.{f}" for f in fields if f != 'name'])
	fields_str = ", " + fields_str if fields_str else ""

	searchfields = frappe.get_meta("Sales Person").get_search_fields()
	searchfields = " or ".join([f"`tabSales Person`.{field} like %(txt)s" for field in searchfields])

	appointment_type = filters.pop("appointment_type", None)
	allowed_sales_persons = get_allowed_sales_persons(appointment_type)

	appointment = filters.pop("appointment", None)
	scheduled_dt = filters.pop("scheduled_dt", None)
	end_dt = filters.pop("end_dt", None)

	appointment_join = ""
	availability_field = ""
	availability_sort = ""
	if scheduled_dt and end_dt:
		appointment_join = """
			left join `tabAppointment`
			on `tabAppointment`.sales_person = `tabSales Person`.name
			and `tabAppointment`.docstatus = 1
			and `tabAppointment`.status != 'Rescheduled'
			and %(start_dt)s < `tabAppointment`.end_dt
			and %(end_dt)s > `tabAppointment`.scheduled_dt
		"""

		if appointment:
			appointment_join += " and `tabAppointment`.name != %(appointment)s"

		availability_field = ", COUNT(`tabAppointment`.name)"
		availability_sort = "COUNT(`tabAppointment`.name), "

	if allowed_sales_persons:
		sales_person_conditions = "`tabSales Person`.name in %(allowed_sales_persons)s"
	else:
		sales_person_conditions = "`tabSales Person`.is_group = 0"

	out = frappe.db.sql("""
		select `tabSales Person`.name {availability_field} {fields}
		from `tabSales Person`
		{appointment_join}
		where `tabSales Person`.enabled = 1 and {sales_person_conditions} and ({scond}) {fcond} {mcond}
		group by `tabSales Person`.name
		order by
			if(locate(%(_txt)s, `tabSales Person`.name), locate(%(_txt)s, `tabSales Person`.name), 99999),
			{availability_sort}
			`tabSales Person`.name
		limit %(start)s, %(page_len)s
	""".format(**{
		'fields': fields_str,
		"scond": searchfields,
		'key': searchfield,
		'fcond': get_filters_cond(doctype, filters, conditions),
		'mcond': get_match_cond(doctype),
		'sales_person_conditions': sales_person_conditions,
		'availability_field': availability_field,
		'availability_sort': availability_sort,
		'appointment_join': appointment_join,
	}), {
		'txt': "%%%s%%" % txt,
		'_txt': txt.replace("%", ""),
		'start': start,
		'page_len': page_len,
		'allowed_sales_persons': allowed_sales_persons,
		'appointment': appointment,
		'start_dt': scheduled_dt,
		'end_dt': end_dt,
	}, as_list=1)

	if availability_field:
		for d in out:
			d[1] = _("Unavailable") if cint(d[1]) else _("Available")

	return out


def on_doctype_update():
	frappe.db.add_index("Appointment", ["scheduled_dt", "end_dt"])
