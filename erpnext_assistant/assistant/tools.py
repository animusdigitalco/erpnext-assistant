"""Read-only data tools for the assistant.

Every function here is a pure read. There is deliberately no tool that can
create, modify, submit, cancel, delete, or run SQL — the assistant's write
capability is bounded by what exists in this file. Every read runs through
frappe.get_list / frappe.get_doc under the session user, so ERPNext's own
permission system is the security boundary, not the model's instructions.
"""

import json

import frappe

# Always blocked, regardless of what the admin configures. These hold
# credentials or auth state and have no business in a chat context.
HARD_BLOCKED_DOCTYPES = {
	"User",
	"API Key",
	"API Secret",
	"OAuth Client",
	"OAuth Bearer Token",
	"OAuth Authorization Code",
	"Connected App",
	"Token Cache",
	"Social Login Key",
	"Email Account",
	"Email Queue",
	"LDAP Settings",
	"Webhook",
	"Assistant Settings",
	"Assistant Conversation",
}

ALLOWED_FILTER_OPERATORS = {
	"=", "!=", ">", "<", ">=", "<=",
	"like", "not like", "in", "not in", "between", "is",
}

MAX_RESULTS_HARD_CAP = 100
MAX_TEXT_FIELD_CHARS = 2000


def get_tool_definitions() -> list[dict]:
	"""Tool schemas sent to the model."""
	return [
		{
			"name": "list_doctypes",
			"description": (
				"List the doctypes (tables) in this system the current user can read, "
				"optionally filtered by a search term. Use this first when you are not "
				"sure which doctype holds the data."
			),
			"input_schema": {
				"type": "object",
				"properties": {
					"search": {
						"type": "string",
						"description": "Optional substring to filter doctype names, e.g. 'invoice'.",
					}
				},
			},
		},
		{
			"name": "get_doctype_schema",
			"description": (
				"Get the fields of a doctype: fieldname, label, type and options "
				"(link targets / select choices). Call this before filtering or "
				"selecting fields so you use real fieldnames."
			),
			"input_schema": {
				"type": "object",
				"properties": {
					"doctype": {"type": "string", "description": "Exact doctype name."}
				},
				"required": ["doctype"],
			},
		},
		{
			"name": "list_documents",
			"description": (
				"List documents of a doctype with optional filters, field selection, "
				"ordering and a limit. Results respect the current user's permissions."
			),
			"input_schema": {
				"type": "object",
				"properties": {
					"doctype": {"type": "string"},
					"filters": {
						"type": "array",
						"description": (
							"List of [fieldname, operator, value] triples, e.g. "
							"[[\"status\", \"=\", \"Paid\"], [\"posting_date\", \">=\", \"2026-01-01\"]]. "
							"Operators: = != > < >= <= like 'not like' in 'not in' between is."
						),
						"items": {"type": "array"},
					},
					"fields": {
						"type": "array",
						"description": "Fieldnames to return. Defaults to name and the title field.",
						"items": {"type": "string"},
					},
					"order_by": {
						"type": "string",
						"description": "e.g. 'posting_date desc'. Defaults to 'modified desc'.",
					},
					"limit": {"type": "integer", "description": "Max rows to return."},
				},
				"required": ["doctype"],
			},
		},
		{
			"name": "get_document",
			"description": "Fetch one document in full by doctype and name, including child tables.",
			"input_schema": {
				"type": "object",
				"properties": {
					"doctype": {"type": "string"},
					"name": {"type": "string"},
				},
				"required": ["doctype", "name"],
			},
		},
		{
			"name": "count_documents",
			"description": "Count documents of a doctype matching optional filters, or sum/average a numeric field over them.",
			"input_schema": {
				"type": "object",
				"properties": {
					"doctype": {"type": "string"},
					"filters": {
						"type": "array",
						"description": "Same shape as list_documents filters.",
						"items": {"type": "array"},
					},
					"aggregate": {
						"type": "string",
						"enum": ["count", "sum", "avg", "min", "max"],
						"description": "Defaults to count.",
					},
					"fieldname": {
						"type": "string",
						"description": "Numeric field to aggregate. Required for sum/avg/min/max.",
					},
				},
				"required": ["doctype"],
			},
		},
	]


def execute_tool(tool_name: str, tool_input: dict, settings) -> str:
	"""Dispatch one tool call. Returns a JSON string for the tool_result block.
	Raises ToolError for conditions the model should see and recover from."""
	handlers = {
		"list_doctypes": _list_doctypes,
		"get_doctype_schema": _get_doctype_schema,
		"list_documents": _list_documents,
		"get_document": _get_document,
		"count_documents": _count_documents,
	}
	handler = handlers.get(tool_name)
	if not handler:
		raise ToolError(f"Unknown tool: {tool_name}")
	result = handler(tool_input or {}, settings)
	return json.dumps(result, default=str)


class ToolError(Exception):
	"""An error the model should see as a tool_result with is_error, not a crash."""


def _check_doctype_access(doctype: str, settings):
	if not doctype or not isinstance(doctype, str):
		raise ToolError("doctype is required")
	if not frappe.db.exists("DocType", doctype):
		raise ToolError(f"DocType '{doctype}' does not exist. Use list_doctypes to find the right name.")
	if doctype in HARD_BLOCKED_DOCTYPES or doctype in settings.get_blocked_doctypes():
		raise ToolError(f"DocType '{doctype}' is not available to the assistant on this site.")
	if not frappe.has_permission(doctype, "read"):
		raise ToolError(f"You do not have permission to read '{doctype}'.")


def _sanitize_filters(doctype: str, filters) -> list:
	if not filters:
		return []
	if not isinstance(filters, list):
		raise ToolError("filters must be a list of [fieldname, operator, value] triples")
	meta = frappe.get_meta(doctype)
	clean = []
	for f in filters:
		if not isinstance(f, (list, tuple)) or len(f) != 3:
			raise ToolError(f"Bad filter {f!r}: each filter is [fieldname, operator, value]")
		fieldname, operator, value = f
		operator = str(operator).lower().strip()
		if operator not in ALLOWED_FILTER_OPERATORS:
			raise ToolError(f"Operator '{operator}' is not allowed")
		if fieldname != "name" and not meta.get_field(fieldname):
			raise ToolError(
				f"'{fieldname}' is not a field of {doctype}. Use get_doctype_schema to see its fields."
			)
		if _is_sensitive_field(meta.get_field(fieldname)) or (
			fieldname != "name" and fieldname not in _permitted_fieldnames(meta)
		):
			raise ToolError(f"'{fieldname}' is not available to the assistant.")
		clean.append([fieldname, operator, value])
	return clean


def _is_sensitive_field(df) -> bool:
	if df is None:
		return False
	return df.fieldtype == "Password"


def _permitted_fieldnames(meta, parenttype: str | None = None) -> set:
	"""Fieldnames the current user may read, honoring permlevel restrictions."""
	return set(meta.get_permitted_fieldnames(parenttype=parenttype))


def _visible_fields(meta, parenttype: str | None = None) -> list:
	permitted = _permitted_fieldnames(meta, parenttype=parenttype)
	return [
		df for df in meta.fields
		if not _is_sensitive_field(df) and df.fieldname in permitted
	]


def _truncate(value):
	if isinstance(value, str) and len(value) > MAX_TEXT_FIELD_CHARS:
		return value[:MAX_TEXT_FIELD_CHARS] + " …[truncated]"
	return value


def _list_doctypes(tool_input: dict, settings) -> dict:
	search = (tool_input.get("search") or "").strip().lower()
	blocked = HARD_BLOCKED_DOCTYPES | settings.get_blocked_doctypes()
	readable = frappe.get_user().get_can_read()
	names = sorted(
		dt for dt in readable
		if dt not in blocked and (not search or search in dt.lower())
	)
	return {"doctypes": names[:200], "total": len(names)}


def _get_doctype_schema(tool_input: dict, settings) -> dict:
	doctype = tool_input.get("doctype")
	_check_doctype_access(doctype, settings)
	meta = frappe.get_meta(doctype)
	fields = [
		{
			"fieldname": df.fieldname,
			"label": df.label,
			"fieldtype": df.fieldtype,
			"options": df.options,
		}
		for df in _visible_fields(meta)
		if df.fieldtype not in ("Section Break", "Column Break", "Tab Break", "HTML")
	]
	return {
		"doctype": doctype,
		"is_submittable": bool(meta.is_submittable),
		"title_field": meta.title_field,
		"fields": fields,
	}


def _list_documents(tool_input: dict, settings) -> dict:
	doctype = tool_input.get("doctype")
	_check_doctype_access(doctype, settings)
	meta = frappe.get_meta(doctype)
	if meta.issingle:
		raise ToolError(f"{doctype} is a single settings document. Use get_document with name='{doctype}'.")

	max_results = min(int(settings.max_results_per_query or 20), MAX_RESULTS_HARD_CAP)
	limit = min(int(tool_input.get("limit") or max_results), max_results)

	fields = tool_input.get("fields")
	if fields:
		clean_fields = []
		for fieldname in fields:
			df = meta.get_field(fieldname)
			if fieldname != "name" and df is None:
				raise ToolError(f"'{fieldname}' is not a field of {doctype}")
			if _is_sensitive_field(df):
				continue
			clean_fields.append(fieldname)
		fields = clean_fields or ["name"]
	else:
		fields = ["name"]
		if meta.title_field and meta.get_field(meta.title_field):
			fields.append(meta.title_field)

	order_by = tool_input.get("order_by") or "modified desc"
	parts = order_by.strip().split()
	if (
		len(parts) > 2
		or (parts and parts[0] != "name" and not meta.get_field(parts[0]))
		or (len(parts) == 2 and parts[1].lower() not in ("asc", "desc"))
	):
		raise ToolError(f"Bad order_by '{order_by}'. Use 'fieldname asc' or 'fieldname desc'.")

	rows = frappe.get_list(
		doctype,
		filters=_sanitize_filters(doctype, tool_input.get("filters")),
		fields=fields,
		order_by=order_by,
		limit_page_length=limit,
	)
	rows = [{k: _truncate(v) for k, v in row.items()} for row in rows]
	return {"doctype": doctype, "rows": rows, "returned": len(rows), "limit": limit}


def _get_document(tool_input: dict, settings) -> dict:
	doctype = tool_input.get("doctype")
	name = tool_input.get("name")
	_check_doctype_access(doctype, settings)
	if not name:
		raise ToolError("name is required")

	try:
		doc = frappe.get_doc(doctype, name)
	except frappe.DoesNotExistError:
		raise ToolError(f"{doctype} '{name}' not found")
	if not doc.has_permission("read"):
		raise ToolError(f"You do not have permission to read {doctype} '{name}'.")

	meta = frappe.get_meta(doctype)
	out = {"doctype": doctype, "name": doc.name}
	for df in _visible_fields(meta):
		if df.fieldtype in ("Section Break", "Column Break", "Tab Break", "HTML"):
			continue
		value = doc.get(df.fieldname)
		if df.fieldtype in ("Table", "Table MultiSelect"):
			child_meta = frappe.get_meta(df.options)
			child_fields = [
				c.fieldname
				for c in _visible_fields(child_meta, parenttype=doctype)
				if c.fieldtype not in ("Section Break", "Column Break", "Tab Break", "HTML")
			]
			value = [
				{c: _truncate(row.get(c)) for c in child_fields}
				for row in (value or [])
			]
		else:
			value = _truncate(value)
		out[df.fieldname] = value
	return out


def _count_documents(tool_input: dict, settings) -> dict:
	doctype = tool_input.get("doctype")
	_check_doctype_access(doctype, settings)
	meta = frappe.get_meta(doctype)
	if meta.issingle:
		raise ToolError(f"{doctype} is a single settings document. Use get_document with name='{doctype}'.")

	aggregate = (tool_input.get("aggregate") or "count").lower()
	if aggregate not in ("count", "sum", "avg", "min", "max"):
		raise ToolError(f"Bad aggregate '{aggregate}'")

	if aggregate == "count":
		expr = "count(name) as value"
	else:
		fieldname = tool_input.get("fieldname")
		df = meta.get_field(fieldname) if fieldname else None
		if df is None:
			raise ToolError(f"fieldname is required for {aggregate} and must be a real field")
		if df.fieldtype not in ("Currency", "Float", "Int", "Percent", "Duration"):
			raise ToolError(f"'{fieldname}' is not numeric ({df.fieldtype})")
		if _is_sensitive_field(df) or df.fieldname not in _permitted_fieldnames(meta):
			raise ToolError(f"'{fieldname}' is not available to the assistant.")
		expr = f"{aggregate}(`{df.fieldname}`) as value"

	rows = frappe.get_list(
		doctype,
		filters=_sanitize_filters(doctype, tool_input.get("filters")),
		fields=[expr],
	)
	value = rows[0].value if rows else 0
	return {"doctype": doctype, "aggregate": aggregate, "value": value}
