import frappe
from frappe import _
from frappe.model.document import Document


class AssistantSettings(Document):
	def validate(self):
		if self.enabled and not self.get_password("api_key", raise_exception=False):
			frappe.throw(_("Add your Anthropic API key before enabling the assistant."))

		key = self.get_password("api_key", raise_exception=False) or ""
		if key and not key.startswith("sk-ant-"):
			frappe.msgprint(
				_("That key does not look like an Anthropic API key (they start with sk-ant-). "
				  "Double-check it if the assistant cannot connect."),
				indicator="orange",
			)

		if self.max_results_per_query and self.max_results_per_query > 100:
			self.max_results_per_query = 100

	def get_blocked_doctypes(self) -> set[str]:
		configured = {
			line.strip()
			for line in (self.blocked_doctypes or "").splitlines()
			if line.strip()
		}
		return configured
