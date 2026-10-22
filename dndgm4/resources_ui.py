"""Reviewed campaign treasure, supplies, and XP commands."""
from __future__ import annotations

from decimal import Decimal
import json
import sqlite3
from uuid import uuid4

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from .resources import (
    CARRYING_SOURCE, ResourceRepository, decode_operation, encumbrance, money_label, pounds_to_millilb,
)


def _label(text):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


def _button(text, callback):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    return widget


def _whole(field, label):
    text = field.text().strip()
    if not text or not text.isascii() or not text.isdecimal() or len(text) > 15:
        raise ValueError(f"{label} must be a nonnegative whole number.")
    return int(text)


def _pounds(value):
    return format(Decimal(value) / 1000, "f")


class ResourcesDialog(QDialog):
    """A campaign resource desk; opening or previewing never grants a reward."""

    character_changed = pyqtSignal(str)
    resources_changed = pyqtSignal()

    def __init__(self, database_path, campaign_id, parent=None):
        super().__init__(parent)
        self.repository = ResourceRepository(database_path)
        self.campaign_id = campaign_id
        campaign = self.repository.campaigns.get_campaign(campaign_id)
        if campaign is None:
            raise ValueError("Choose a saved campaign before opening Resources & Rewards.")
        self._wallet_id = None
        self._retry_commands = {}
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle(f"Resources & Rewards · {campaign.name}")
        self.resize(1060, 760)
        self.setMinimumSize(830, 540)
        layout = QVBoxLayout(self)
        heading = _label("RESOURCES & REWARDS")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        layout.addWidget(_label(f"{campaign.name} · Shared treasuries, personal purses, item instances and reviewed XP awards."))
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        navigation = QWidget()
        nav = QVBoxLayout(navigation)
        nav.addWidget(_label("Select a wallet / inventory owner"))
        self.wallets = QListWidget()
        self.wallets.setAccessibleName("Campaign resource wallets")
        self.wallets.currentItemChanged.connect(self._wallet_changed)
        nav.addWidget(self.wallets, 1)
        nav.addWidget(_button("New Wallet / Shared Store…", self.new_wallet))
        nav.addWidget(_button("Refresh Saved Resources", self.refresh))
        splitter.addWidget(navigation)
        self.tabs = QTabWidget()
        splitter.addWidget(self.tabs)
        splitter.setSizes([280, 760])
        self.balance = _label("")
        self.xp_status = _label("")
        self._build_money()
        self._build_inventory()
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setAccessibleName("Audited resource operations")
        self.tabs.addTab(self.history, "Audit History")
        source = QHBoxLayout()
        source.addWidget(_label("Source session"))
        self.session = QComboBox()
        self.session.setAccessibleName("Reward or transfer source session")
        self.session.addItem("Campaign / no session", "")
        for saved in self.repository.campaigns.list_sessions(campaign_id):
            self.session.addItem(saved.title, saved.id)
        self.session.currentIndexChanged.connect(self._fill_encounters)
        source.addWidget(self.session, 1)
        source.addWidget(_label("Encounter"))
        self.encounter = QComboBox()
        self.encounter.setAccessibleName("Reward or transfer source encounter")
        source.addWidget(self.encounter, 1)
        layout.addLayout(source)
        reason_row = QHBoxLayout()
        reason_row.addWidget(_label("Reason / provenance"))
        self.reason = QLineEdit()
        self.reason.setAccessibleName("Resource command reason")
        self.reason.setMaxLength(2000)
        self.reason.setPlaceholderText("For example: bridge rescue, provisions, or potion used")
        reason_row.addWidget(self.reason, 1)
        layout.addLayout(reason_row)
        self.message = _label("")
        self.message.setAccessibleName("Resource operation result")
        layout.addWidget(self.message)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        self._fill_encounters()
        self.refresh()

    def _build_money(self):
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.addWidget(self.balance)
        layout.addWidget(self.xp_status)
        layout.addWidget(_label("Enter monetary value in copper pieces: 100 cp = 1 gp. All commands are reviewed before saving."))
        form = QFormLayout()
        self.copper = QLineEdit("0")
        self.copper.setAccessibleName("Copper pieces to award spend or transfer")
        self.copper.setMaxLength(13)
        form.addRow("Copper pieces", self.copper)
        self.xp = QLineEdit("0")
        self.xp.setAccessibleName("Pending XP to award")
        self.xp.setMaxLength(10)
        form.addRow("XP to award (pending)", self.xp)
        self.money_target = QComboBox()
        self.money_target.setAccessibleName("Money transfer destination")
        form.addRow("Transfer destination", self.money_target)
        layout.addLayout(form)
        self.award_button = _button("Preview Reward / Deposit…", lambda: self.money_command("award"))
        self.expense_button = _button("Preview Expense…", lambda: self.money_command("expense"))
        self.transfer_money_button = _button("Preview Money Transfer…", lambda: self.money_command("transfer"))
        for button in (self.award_button, self.expense_button, self.transfer_money_button):
            layout.addWidget(button)
        self.apply_xp_button = _button("Review && Apply Pending XP…", self.apply_pending_xp)
        layout.addWidget(self.apply_xp_button)
        layout.addWidget(_label("XP awards stay in the ledger until explicitly applied to the shared character sheet. Use guided advancement separately to review a level change."))
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self.tabs.addTab(scroll, "Money && XP")

    def _build_inventory(self):
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.addWidget(_label("These are campaign item instances. Enter all carried/worn gear here to include it in weight; transfers do not rewrite the library equipment list."))
        self.items = QListWidget()
        self.items.setAccessibleName("Selected wallet inventory")
        self.items.currentItemChanged.connect(self._item_changed)
        layout.addWidget(self.items, 1)
        add_row = QHBoxLayout()
        self.add_item_button = _button("Add Item / Treasure…", self.new_item)
        self.add_container_button = _button("New Container…", self.new_container)
        add_row.addWidget(self.add_item_button)
        add_row.addWidget(self.add_container_button)
        layout.addLayout(add_row)
        form = QFormLayout()
        self.item_quantity = QSpinBox()
        self.item_quantity.setRange(1, 1_000_000)
        form.addRow("Quantity to move / use", self.item_quantity)
        self.item_target = QComboBox()
        self.item_target.setAccessibleName("Item transfer destination wallet")
        self.item_target.currentIndexChanged.connect(self._fill_target_containers)
        form.addRow("Destination wallet", self.item_target)
        self.item_container = QComboBox()
        self.item_container.setAccessibleName("Item transfer destination container")
        form.addRow("Destination container", self.item_container)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.transfer_item_button = _button("Preview Item Transfer…", lambda: self.item_command("transfer"))
        self.consume_button = _button("Preview Item Use / Removal…", lambda: self.item_command("consume"))
        row.addWidget(self.transfer_item_button)
        row.addWidget(self.consume_button)
        layout.addLayout(row)
        load = QHBoxLayout()
        self.strength = QSpinBox()
        self.strength.setRange(1, 99)
        self.strength.setValue(10)
        self.strength.valueChanged.connect(self._update_load)
        load.addWidget(_label("Strength"))
        load.addWidget(self.strength)
        self.size = QComboBox()
        self.size.addItems(("Fine", "Diminutive", "Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan", "Colossal"))
        self.size.setCurrentText("Medium")
        self.size.currentIndexChanged.connect(self._update_load)
        load.addWidget(self.size)
        self.quadruped = QCheckBox("Quadruped")
        self.quadruped.toggled.connect(self._update_load)
        load.addWidget(self.quadruped)
        layout.addLayout(load)
        self.load_status = _label("")
        layout.addWidget(self.load_status)
        layout.addWidget(_label("Weight includes these items and empty containers. Wallet value does not imply coin weight; record physical coins as an item. Armor, magic and unusual carrying abilities require DM review. Load penalties are advisory."))
        citation = QLabel(f'<a href="{CARRYING_SOURCE}">D&D 3.5 SRD · Carrying capacity</a>')
        citation.setOpenExternalLinks(True)
        layout.addWidget(citation)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self.tabs.addTab(scroll, "Items && Carrying")

    def _fill_encounters(self):
        self.encounter.clear()
        self.encounter.addItem("No encounter", "")
        if self.session.currentData():
            for saved in self.repository.campaigns.list_encounters(self.session.currentData()):
                self.encounter.addItem(saved.title, saved.id)

    def _source(self):
        return dict(session_id=self.session.currentData() or "", encounter_id=self.encounter.currentData() or "")

    def _fill_target_containers(self):
        if not hasattr(self, "item_container"):
            return
        self.item_container.clear()
        self.item_container.addItem("Loose / no container", None)
        target = self.item_target.currentData()
        if target:
            for saved in self.repository.list_containers(self.campaign_id, target):
                self.item_container.addItem(saved.name, saved.id)

    def refresh(self):
        selected = self._wallet_id
        wallets = self.repository.list_wallets(self.campaign_id)
        self.wallets.blockSignals(True)
        self.wallets.clear()
        self.money_target.blockSignals(True)
        self.item_target.blockSignals(True)
        targets = (self.money_target.currentData(), self.item_target.currentData())
        self.money_target.clear()
        self.item_target.clear()
        for wallet in wallets:
            item = QListWidgetItem(f"{wallet.name}\n{money_label(wallet.copper)}")
            item.setData(Qt.ItemDataRole.UserRole, wallet.id)
            self.wallets.addItem(item)
            for combo in (self.money_target, self.item_target):
                combo.addItem(wallet.name, wallet.id)
            if wallet.id == selected:
                self.wallets.setCurrentItem(item)
        if self.wallets.currentRow() < 0 and self.wallets.count():
            self.wallets.setCurrentRow(0)
        self.wallets.blockSignals(False)
        for combo, target in zip((self.money_target, self.item_target), targets):
            index = combo.findData(target)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
        self._fill_target_containers()
        self._wallet_changed()
        history = []
        for entry in self.repository.operations(self.campaign_id):
            try:
                payload = decode_operation(entry["payload_json"])
                rendered = json.dumps(payload, ensure_ascii=False, indent=2)
            except ValueError as exc:
                rendered = str(exc)
            history.append(f'{entry["created_at"]} · {entry["id"]}\n{rendered}')
        self.history.setPlainText("\n\n".join(history) or "No resource commands recorded.")

    def _wallet_changed(self, *_):
        current = self.wallets.currentItem()
        self._wallet_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.items.clear()
        for widget in (self.award_button, self.expense_button, self.transfer_money_button,
                       self.add_item_button, self.add_container_button):
            widget.setEnabled(bool(self._wallet_id))
        self.apply_xp_button.setEnabled(False)
        if not self._wallet_id:
            self.balance.setText("Create a shared store or personal wallet to begin.")
            self.xp_status.setText("")
            self.load_status.setText("")
            self._item_changed()
            return
        wallet = self.repository.get_wallet(self.campaign_id, self._wallet_id)
        self.balance.setText(f"{wallet.name} · {money_label(wallet.copper)} ({wallet.copper:,} cp)")
        if wallet.creature_id:
            creature = self.repository.library.get(wallet.creature_id)
            if creature:
                self.strength.setValue(max(1, creature.strength))
            try:
                preview = self.repository.preview_xp(self.campaign_id, wallet.id)
                self.xp_status.setText(f"Saved XP: {preview.current:,} · Pending XP: {preview.pending:,}")
                self.apply_xp_button.setEnabled(bool(preview.pending))
            except ValueError as exc:
                self.xp_status.setText(str(exc))
        else:
            self.xp_status.setText("Shared store · XP rewards need a personal PC/NPC wallet.")
        containers = {entry.id: entry.name for entry in self.repository.list_containers(self.campaign_id, wallet.id)}
        for saved in self.repository.list_items(self.campaign_id, wallet.id):
            location = containers.get(saved.container_id, "Loose")
            item = QListWidgetItem(f"{saved.name} ×{saved.quantity:,} · {_pounds(saved.quantity * saved.unit_millilb)} lb · {location}")
            item.setData(Qt.ItemDataRole.UserRole, saved)
            self.items.addItem(item)
        if self.items.count():
            self.items.setCurrentRow(0)
        self._item_changed()
        self._update_load()

    def _item_changed(self, *_):
        item = self.items.currentItem()
        self.transfer_item_button.setEnabled(item is not None)
        self.consume_button.setEnabled(item is not None)
        if item:
            self.item_quantity.setMaximum(item.data(Qt.ItemDataRole.UserRole).quantity)

    def _update_load(self, *_):
        if not self._wallet_id:
            return
        report = encumbrance(self.repository.carried_weight(self.campaign_id, self._wallet_id), self.strength.value(), self.size.currentText(), self.quadruped.isChecked())
        penalty = "" if report["load"] == "light" else f' · Max Dex {report["max_dex"]} · Check penalty {report["check_penalty"]}' if report["load"] != "overloaded" else " · Above maximum normal carried load"
        movement = f'Speed from 30 ft: {report["speed_30_ft"]} ft · Run ×{report["run_multiplier"]}' if report["load"] != "overloaded" else "Overhead maximum exceeded; lift/stagger limits need DM review."
        self.load_status.setText(f'{report["weight_lb"]} lb · {report["load"].capitalize()} load{penalty}\nThresholds: light {report["light_lb"]} / medium {report["medium_lb"]} / heavy {report["heavy_lb"]} lb\n{movement}')

    def _confirm(self, title, text):
        # The explicitly constructed plain-text box never interprets a record
        # name as markup or a link.
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return box.exec() == QMessageBox.StandardButton.Ok

    def _run(self, signature, callback):
        key = json.dumps(signature, sort_keys=True)
        request = self._retry_commands.setdefault(key, str(uuid4()))
        try:
            result = callback(request)
            self.refresh()
        except (ValueError, sqlite3.Error, OSError, TypeError, OverflowError) as exc:
            self.message.setText(f"Could not save resource command: {exc}")
            return False
        self._retry_commands.pop(key, None)
        self.message.setText("Resource command saved. Audit history includes its reason and source.")
        self.resources_changed.emit()
        return result if result is not None else True

    def _input_error(self, exc):
        self.message.setText(str(exc))
        return False

    def money_command(self, kind):
        if not self._wallet_id:
            return False
        try:
            copper = _whole(self.copper, "Copper pieces")
            xp = _whole(self.xp, "XP") if kind == "award" else 0
            reason = self.reason.text().strip()
            if not reason:
                raise ValueError("Enter a reason / provenance before saving a command.")
            wallet = self.repository.get_wallet(self.campaign_id, self._wallet_id)
            source = self._source()
            target_id = self.money_target.currentData()
            if kind == "transfer":
                target = self.repository.get_wallet(self.campaign_id, target_id)
                text = f"Transfer {money_label(copper)} from {wallet.name} to {target.name}?\nSource balance: {money_label(wallet.copper)}\nReason: {reason}"
                callback = lambda request: self.repository.transfer_money(self.campaign_id, wallet.id, target.id, copper, reason, request, **source)
            elif kind == "expense":
                text = f"Spend {money_label(copper)} from {wallet.name}?\nSource balance: {money_label(wallet.copper)}\nReason: {reason}"
                callback = lambda request: self.repository.adjust_money(self.campaign_id, wallet.id, -copper, reason, request, **source)
            else:
                text = f"Award {money_label(copper)} and {xp:,} pending XP to {wallet.name}?\nXP will wait for a separate reviewed application.\nReason: {reason}"
                callback = lambda request: self.repository.award(self.campaign_id, [dict(wallet_id=wallet.id, copper=copper, xp=xp)], reason, request, **source)
            if not self._confirm("Review Resource Command", text):
                return False
            return self._run(dict(kind=kind, wallet=wallet.id, target=target_id, copper=copper, xp=xp, reason=reason, **source), callback)
        except (ValueError, sqlite3.Error) as exc:
            return self._input_error(exc)

    def apply_pending_xp(self):
        if not self._wallet_id:
            return False
        try:
            preview = self.repository.preview_xp(self.campaign_id, self._wallet_id)
            if not preview.pending:
                raise ValueError("There is no pending XP to apply.")
            if not self._confirm("Review Character XP", f"{preview.name}: {preview.current:,} → {preview.target:,} XP (+{preview.pending:,}).\n\nThis updates the shared character sheet used by every campaign that references this character. Levels and other statistics stay at their current values. Review any level change with guided advancement."):
                return False
            result = self._run(dict(kind="apply_xp", wallet=preview.wallet_id, current=preview.current, ledger_ids=preview.ledger_ids), lambda request: self.repository.apply_xp(preview, request))
            if result:
                self.character_changed.emit(preview.creature_id)
            return result
        except (ValueError, sqlite3.Error) as exc:
            return self._input_error(exc)

    def new_wallet(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("New Resource Wallet")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        name = QLineEdit()
        name.setMaxLength(200)
        owner = QComboBox()
        owner.addItem("Shared store / no creature", None)
        for saved in self.repository.library.list():
            owner.addItem(saved.name, saved.id)
        form.addRow("Wallet / store name", name)
        form.addRow("Owner", owner)
        layout.addLayout(form)
        layout.addWidget(_label("The new wallet starts empty. Each creature can have one wallet per campaign."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        error = _label("")
        layout.addWidget(error)
        def save():
            try:
                saved = self.repository.create_wallet(self.campaign_id, name.text(), owner.currentData())
                self._wallet_id = saved.id
                dialog.accept()
            except (ValueError, sqlite3.Error) as exc:
                error.setText(str(exc))
        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self.refresh()
        return True

    def new_container(self):
        if not self._wallet_id:
            return False
        dialog = QDialog(self)
        dialog.setWindowTitle("New Inventory Container")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        name, tare, capacity = QLineEdit(), QLineEdit("0"), QLineEdit("0")
        name.setMaxLength(200)
        form.addRow("Container name", name)
        form.addRow("Empty weight (lb)", tare)
        form.addRow("Contents capacity (lb; 0 = unspecified)", capacity)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        error = _label("")
        layout.addWidget(error)
        def save():
            try:
                self.repository.create_container(self.campaign_id, self._wallet_id, name.text(), tare_millilb=pounds_to_millilb(tare.text()), capacity_millilb=pounds_to_millilb(capacity.text()))
                dialog.accept()
            except (ValueError, sqlite3.Error) as exc:
                error.setText(str(exc))
        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self.refresh()
        return True

    def new_item(self):
        if not self._wallet_id:
            return False
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Item / Treasure")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        name, weight, value = QLineEdit(), QLineEdit("0"), QLineEdit("0")
        name.setMaxLength(200)
        quantity = QSpinBox()
        quantity.setRange(1, 1_000_000)
        container = QComboBox()
        container.addItem("Loose / no container", None)
        for saved in self.repository.list_containers(self.campaign_id, self._wallet_id):
            container.addItem(saved.name, saved.id)
        notes = QPlainTextEdit()
        form.addRow("Item name", name)
        form.addRow("Quantity", quantity)
        form.addRow("Weight of each (lb)", weight)
        form.addRow("Value of each (cp)", value)
        form.addRow("Container", container)
        form.addRow("Item notes", notes)
        layout.addLayout(form)
        layout.addWidget(_label("This records item ownership and value. It does not purchase an item or debit money; record any payment as an expense."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        error = _label("")
        layout.addWidget(error)
        def save():
            try:
                unit_weight = pounds_to_millilb(weight.text())
                unit_cp = _whole(value, "Unit value")
                wallet_id = self._wallet_id
                reason = self.reason.text().strip()
                if not reason:
                    raise ValueError("Enter a reason / provenance in the resource desk before adding an item.")
                if not name.text().strip():
                    raise ValueError("Enter an item name.")
                source = self._source()
                if not self._confirm("Review New Inventory", f"Add {name.text()} ×{quantity.value():,}, total {_pounds(quantity.value() * unit_weight)} lb?\nValue each: {money_label(unit_cp)}\nReason: {reason}"):
                    return
                args = dict(wallet_id=wallet_id, name=name.text(), quantity=quantity.value(), unit_millilb=unit_weight, unit_cp=unit_cp, container_id=container.currentData(), notes=notes.toPlainText(), reason=reason, **source)
                if self._run(dict(kind="add_item", **args), lambda request: self.repository.add_item(self.campaign_id, request_id=request, **args)):
                    dialog.accept()
                else:
                    error.setText(self.message.text())
            except (ValueError, sqlite3.Error) as exc:
                error.setText(str(exc))
        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def item_command(self, kind):
        selected = self.items.currentItem()
        if not selected:
            return False
        try:
            item = selected.data(Qt.ItemDataRole.UserRole)
            quantity = self.item_quantity.value()
            reason = self.reason.text().strip()
            if not reason:
                raise ValueError("Enter a reason / provenance before moving or using an item.")
            source = self._source()
            if kind == "transfer":
                target_id, container_id = self.item_target.currentData(), self.item_container.currentData()
                target = self.repository.get_wallet(self.campaign_id, target_id)
                text = f"Transfer {item.name} ×{quantity:,} to {target.name} / {self.item_container.currentText()}?\nReason: {reason}"
                callback = lambda request: self.repository.transfer_item(self.campaign_id, item.id, target_id, quantity, reason, request, container_id=container_id, **source)
            else:
                target_id = container_id = None
                text = f"Use / remove {item.name} ×{quantity:,}?\nRemaining quantity: {item.quantity - quantity:,}\nReason: {reason}"
                callback = lambda request: self.repository.consume_item(self.campaign_id, item.id, quantity, reason, request, **source)
            if not self._confirm("Review Inventory Command", text):
                return False
            return self._run(dict(kind=kind, item=item.id, quantity=quantity, target_id=target_id, container_id=container_id, reason=reason, **source), callback)
        except (ValueError, sqlite3.Error) as exc:
            return self._input_error(exc)
