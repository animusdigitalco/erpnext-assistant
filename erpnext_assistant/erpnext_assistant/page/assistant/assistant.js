frappe.pages["assistant"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Assistant"),
		single_column: true,
	});

	new ERPNextAssistant(page);
};

class ERPNextAssistant {
	constructor(page) {
		this.page = page;
		this.conversation = null;
		this.busy = false;

		this.inject_styles();
		this.render();
		this.bind_events();
		this.load_conversation_list();

		frappe.realtime.on("erpnext_assistant_progress", (data) => {
			if (this.busy && data && data.text && this.$thinking) {
				this.$thinking.find(".ea-thinking-text").text(data.text + "…");
			}
		});
	}

	inject_styles() {
		if (document.getElementById("erpnext-assistant-style")) return;
		const css = `
			.ea-wrap { max-width: 840px; margin: 0 auto; display: flex; flex-direction: column; height: calc(100vh - 140px); }
			.ea-messages { flex: 1; overflow-y: auto; padding: 16px 8px; }
			.ea-msg { margin-bottom: 14px; display: flex; }
			.ea-msg-user { justify-content: flex-end; }
			.ea-bubble { max-width: 85%; padding: 10px 14px; border-radius: 12px; line-height: 1.5; word-wrap: break-word; }
			.ea-msg-user .ea-bubble { background: var(--bg-blue, #e8f0fe); }
			.ea-msg-assistant .ea-bubble { background: var(--bg-light-gray, var(--control-bg, #f4f5f6)); }
			.ea-bubble p:last-child { margin-bottom: 0; }
			.ea-bubble table { font-size: var(--text-sm); }
			.ea-composer { display: flex; gap: 8px; padding: 12px 8px; border-top: 1px solid var(--border-color, #ebeef0); }
			.ea-composer textarea { flex: 1; resize: none; max-height: 140px; }
			.ea-empty { text-align: center; color: var(--text-muted); margin-top: 15vh; }
			.ea-usage { font-size: var(--text-xs); color: var(--text-muted); margin-top: 4px; }
			.ea-msg-notice .ea-bubble { background: var(--bg-orange, #fff4e5); border: 1px solid var(--orange-200, #f5c26b); }
			.ea-notice-label { font-size: var(--text-xs); font-weight: 600; color: var(--orange-600, #b35c00); text-transform: uppercase; letter-spacing: .04em; margin-bottom: 2px; }
			.ea-thinking-text { font-size: var(--text-sm); color: var(--text-muted); margin-left: 8px; }
			.ea-dots { display: inline-flex; gap: 4px; align-items: center; padding: 2px 0; }
			.ea-dots span { width: 7px; height: 7px; border-radius: 50%; background: var(--text-muted, #94a3b8); animation: eaBounce 1.2s infinite ease-in-out; }
			.ea-dots span:nth-child(2) { animation-delay: .15s; }
			.ea-dots span:nth-child(3) { animation-delay: .3s; }
			@keyframes eaBounce { 0%, 60%, 100% { transform: translateY(0); opacity: .45; } 30% { transform: translateY(-5px); opacity: 1; } }
			@media (prefers-reduced-motion: reduce) { .ea-dots span { animation: none; opacity: .7; } }
		`;
		$("<style>", { id: "erpnext-assistant-style", text: css }).appendTo("head");
	}

	render() {
		this.$wrap = $(`
			<div class="ea-wrap">
				<div class="ea-messages"></div>
				<div class="ea-composer">
					<textarea class="form-control" rows="2"
						placeholder="${__("Ask about your data, e.g. 'Which invoices are overdue this month?'")}"></textarea>
					<button class="btn btn-primary btn-send">${__("Send")}</button>
				</div>
			</div>
		`).appendTo(this.page.main);

		this.$messages = this.$wrap.find(".ea-messages");
		this.$input = this.$wrap.find("textarea");
		this.$send = this.$wrap.find(".btn-send");
		this.$thinking = null;

		this.show_empty_state();

		this.page.set_secondary_action(__("New Chat"), () => this.new_chat());
	}

	show_empty_state() {
		this.$messages.html(`
			<div class="ea-empty">
				<p><b>${__("Ask me about this system.")}</b></p>
				<p>${__("I can look up records, counts and totals you have permission to see. I am read only.")}</p>
			</div>
		`);
	}

	bind_events() {
		this.$send.on("click", () => this.send());
		this.$input.on("keydown", (e) => {
			if (e.key === "Enter" && !e.shiftKey) {
				e.preventDefault();
				this.send();
			}
		});
	}

	load_conversation_list() {
		frappe
			.call("erpnext_assistant.assistant.api.get_conversations")
			.then((r) => {
				const items = r.message || [];
				if (!items.length) return;
				this.page.add_menu_item(__("Recent chats"), () => {}, true);
				items.slice(0, 10).forEach((c) => {
					this.page.add_menu_item(c.title || c.name, () => this.open_conversation(c.name));
				});
			})
			.catch(() => {});
	}

	open_conversation(name) {
		frappe.call("erpnext_assistant.assistant.api.get_conversation", { conversation: name }).then((r) => {
			this.conversation = name;
			this.$messages.empty();
			(r.message.messages || []).forEach((m) => this.append_message(m.role, m.content));
			this.scroll_down();
		});
	}

	new_chat() {
		this.conversation = null;
		this.show_empty_state();
		this.$input.val("").focus();
	}

	append_message(role, content, opts = {}) {
		this.$messages.find(".ea-empty").remove();
		const html = role === "assistant" ? frappe.markdown(content) : frappe.utils.escape_html(content);
		const notice = opts.notice ? " ea-msg-notice" : "";
		const label = opts.notice ? `<div class="ea-notice-label">${__("Out of scope")}</div>` : "";
		const $msg = $(`
			<div class="ea-msg ea-msg-${role}${notice}">
				<div class="ea-bubble">${label}${html}</div>
			</div>
		`);
		this.$messages.append($msg);
		this.scroll_down();
		return $msg;
	}

	show_thinking() {
		this.$thinking = $(`
			<div class="ea-msg ea-msg-assistant">
				<div class="ea-bubble">
					<span class="ea-dots" aria-label="${__("Thinking")}"><span></span><span></span><span></span></span>
					<span class="ea-thinking-text">${__("Thinking")}…</span>
				</div>
			</div>
		`);
		this.$messages.append(this.$thinking);
		this.scroll_down();
	}

	hide_thinking() {
		if (this.$thinking) {
			this.$thinking.remove();
			this.$thinking = null;
		}
	}

	scroll_down() {
		this.$messages.scrollTop(this.$messages[0].scrollHeight);
	}

	send() {
		if (this.busy) return;
		const message = (this.$input.val() || "").trim();
		if (!message) return;

		this.busy = true;
		this.$input.val("");
		this.$send.prop("disabled", true);
		this.append_message("user", message);
		this.show_thinking();

		frappe
			.call({
				method: "erpnext_assistant.assistant.api.ask",
				args: { message: message, conversation: this.conversation },
				timeout: 300,
			})
			.then((r) => {
				this.hide_thinking();
				this.conversation = r.message.conversation || this.conversation;
				const $msg = this.append_message("assistant", r.message.reply, {
					notice: !!r.message.out_of_scope,
				});
				const u = r.message.usage;
				if (u && !r.message.out_of_scope) {
					$msg
						.find(".ea-bubble")
						.append(
							`<div class="ea-usage">${u.input_tokens} ${__("in")} / ${u.output_tokens} ${__("out tokens")}</div>`
						);
				}
			})
			.catch(() => {
				this.hide_thinking();
				this.append_message("assistant", __("That did not work. Check the error message or the Error Log."));
			})
			.always(() => {
				this.busy = false;
				this.$send.prop("disabled", false);
				this.$input.focus();
			});
	}
}
