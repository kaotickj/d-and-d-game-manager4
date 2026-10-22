"""Reviewed campaign clock, travel, rest, weather and calendar controls."""
from __future__ import annotations

import json
import sqlite3

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from .campaign_time import CalendarSpec, CampaignTimeRepository


def _label(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def _button(text, callback):
    button = QPushButton(text)
    button.clicked.connect(callback)
    return button


def _spin(maximum=1000000000, value=0):
    spin = QSpinBox()
    spin.setRange(0, maximum)
    spin.setValue(value)
    return spin


class CampaignTimeDialog(QDialog):
    def __init__(self, database_path, campaign_id, parent=None):
        super().__init__(parent)
        self.repository = CampaignTimeRepository(database_path)
        self.campaign_id = campaign_id
        campaign = self.repository.campaigns.get_campaign(campaign_id)
        if campaign is None:
            raise ValueError("Choose a saved campaign before opening its clock.")
        self.state = self.repository.get_clock(campaign_id)
        self._preview = None
        self._weather_preview = None
        self._calendar_preview = None
        self._calendar_dirty = False
        self._loading_calendar = False
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle(f"Campaign Time & Travel · {campaign.name}")
        self.resize(980, 760)
        self.setMinimumSize(700, 500)
        layout = QVBoxLayout(self)
        heading = _label("CAMPAIGN TIME & TRAVEL")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        self.clock = _label("")
        layout.addWidget(self.clock)
        layout.addWidget(_label("This fictional clock is separate from real session dates. Preview a change, then apply it. "
                                "Character health, spells, inventory and encounters require their own reviewed actions."))
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._build_advance()
        self._build_travel()
        self._build_rest()
        self._build_events()
        self._build_weather()
        self._build_calendar()
        self._build_history()
        self.message = _label("")
        self.message.setAccessibleName("Campaign time status")
        layout.addWidget(self.message)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        refresh = buttons.addButton("Refresh", QDialogButtonBox.ButtonRole.ActionRole)
        refresh.clicked.connect(self.refresh)
        layout.addWidget(buttons)
        self.refresh()

    def _page(self, label):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        self.tabs.addTab(scroll, label)
        return layout

    def _preview_widgets(self, layout, key):
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setAccessibleName(f"{key.title()} time change preview")
        preview.setPlaceholderText("Preview the change to inspect events and consequences.")
        layout.addWidget(preview, 1)
        apply = _button("Apply Reviewed Time Change", self.apply_time)
        apply.setEnabled(False)
        layout.addWidget(apply)
        setattr(self, key + "_preview", preview)
        setattr(self, key + "_apply", apply)

    def _build_advance(self):
        layout = self._page("Clock")
        form = QFormLayout()
        self.advance_days = _spin(1000000)
        self.advance_minutes = _spin(1000000000, 60)
        self.advance_reason = QLineEdit("Time passes")
        self.advance_reason.setMaxLength(2000)
        form.addRow("Calendar days", self.advance_days)
        form.addRow("Additional minutes", self.advance_minutes)
        form.addRow("Reason for the journal", self.advance_reason)
        layout.addLayout(form)
        layout.addWidget(_button("Preview Time Change", self.preview_advance))
        self._preview_widgets(layout, "advance")
        self.advance_days.valueChanged.connect(self._invalidate_time)
        self.advance_minutes.valueChanged.connect(self._invalidate_time)
        self.advance_reason.textChanged.connect(self._invalidate_time)

    def _build_travel(self):
        layout = self._page("Travel")
        layout.addWidget(_label("Enter the DM's effective speed after considering roads, terrain, load, weather and breaks. "
                                "This calculator does not adjudicate forced marches or encounter probability."))
        form = QFormLayout()
        self.travel_distance = QLineEdit("24")
        self.travel_speed = QLineEdit("3")
        self.travelers = _spin(10000, 1)
        self.travelers.setMinimum(1)
        self.travel_reason = QLineEdit("Travel")
        self.travel_roll = QCheckBox("Include an original d20 encounter prompt roll (DM interprets)")
        for edit in (self.travel_distance, self.travel_speed):
            edit.setMaxLength(30)
        self.travel_reason.setMaxLength(2000)
        form.addRow("Distance (miles)", self.travel_distance)
        form.addRow("Effective speed (miles/hour)", self.travel_speed)
        form.addRow("Travelers", self.travelers)
        form.addRow("Reason / route", self.travel_reason)
        layout.addLayout(form)
        layout.addWidget(self.travel_roll)
        layout.addWidget(_button("Preview Travel", self.preview_travel))
        self._preview_widgets(layout, "travel")
        for edit in (self.travel_distance, self.travel_speed, self.travel_reason):
            edit.textChanged.connect(self._invalidate_time)
        self.travelers.valueChanged.connect(self._invalidate_time)
        self.travel_roll.toggled.connect(self._invalidate_time)

    def _build_rest(self):
        layout = self._page("Rest")
        layout.addWidget(_label("Advance the campaign clock for rest. The DM reviews interruptions and recovery eligibility; "
                                "this action does not restore health, spell slots or other character resources."))
        form = QFormLayout()
        self.rest_hours = QLineEdit("8")
        self.rest_hours.setMaxLength(30)
        self.rest_reason = QLineEdit("Rest")
        self.rest_reason.setMaxLength(2000)
        form.addRow("Elapsed hours", self.rest_hours)
        form.addRow("Reason / rest conditions", self.rest_reason)
        layout.addLayout(form)
        layout.addWidget(_button("Preview Rest", self.preview_rest))
        self._preview_widgets(layout, "rest")
        self.rest_hours.textChanged.connect(self._invalidate_time)
        self.rest_reason.textChanged.connect(self._invalidate_time)

    def _build_events(self):
        layout = self._page("Timeline")
        layout.addWidget(_label("Campaign day 0 is the calendar's first day. World Desk events also appear here; "
                                "manage their status in the World Desk. Advancing time does not complete events."))
        self.events = QListWidget()
        self.events.setAccessibleName("Campaign event timeline")
        layout.addWidget(self.events, 1)
        form = QFormLayout()
        self.event_day = _spin(1000000000)
        self.event_hour = _spin(47)
        self.event_minute = _spin(59)
        self.event_title = QLineEdit()
        self.event_title.setMaxLength(200)
        self.event_notes = QLineEdit()
        self.event_notes.setMaxLength(20000)
        time_row = QHBoxLayout()
        for label, widget in (("Day", self.event_day), ("Hour", self.event_hour), ("Minute", self.event_minute)):
            time_row.addWidget(_label(label))
            time_row.addWidget(widget)
        form.addRow("At", time_row)
        form.addRow("Event title", self.event_title)
        form.addRow("DM notes", self.event_notes)
        layout.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(_button("Add Timeline Event", self.add_event))
        row.addWidget(_button("Cancel Selected Timeline Event", self.cancel_event))
        layout.addLayout(row)

    def _build_weather(self):
        layout = self._page("Weather")
        layout.addWidget(_label("An original d20 prompt generator, rather than a 3.5 weather rules engine. "
                                "Review local climate and consequences with the DM. Rolls are stored only when you save."))
        form = QFormLayout()
        self.weather_day = _spin(1000000000)
        form.addRow("Campaign day", self.weather_day)
        layout.addLayout(form)
        self.saved_weather = _label("")
        layout.addWidget(self.saved_weather)
        layout.addWidget(_button("Roll Weather Preview", self.preview_weather))
        self.weather_text = QPlainTextEdit()
        self.weather_text.setReadOnly(True)
        self.weather_text.setAccessibleName("Weather preview")
        layout.addWidget(self.weather_text, 1)
        self.weather_apply = _button("Save Reviewed Weather", self.apply_weather)
        self.weather_apply.setEnabled(False)
        layout.addWidget(self.weather_apply)
        self.weather_day.valueChanged.connect(self._weather_day_changed)

    def _build_calendar(self):
        layout = self._page("Calendar")
        layout.addWidget(_label("Define a fictional calendar with named months and unequal month lengths. "
                                "Each hour is 60 minutes. Saving keeps elapsed minutes and timeline offsets unchanged. "
                                "Changing hours per day reinterprets numbered World Desk event days."))
        form = QFormLayout()
        self.calendar_name = QLineEdit()
        self.calendar_name.setMaxLength(120)
        self.calendar_hours = _spin(48, 24)
        self.calendar_hours.setMinimum(1)
        self.calendar_epoch = _spin(1000000, 1)
        form.addRow("Calendar name", self.calendar_name)
        form.addRow("Hours per day", self.calendar_hours)
        form.addRow("Starting year", self.calendar_epoch)
        layout.addLayout(form)
        layout.addWidget(_label("Months · one per line: Month name | number of days"))
        self.calendar_months = QPlainTextEdit()
        self.calendar_months.setAccessibleName("Calendar month names and lengths")
        layout.addWidget(self.calendar_months, 1)
        layout.addWidget(_button("Review Calendar Definition", self.preview_calendar))
        self.calendar_review = _label("")
        layout.addWidget(self.calendar_review)
        self.calendar_apply = _button("Save Reviewed Calendar", self.apply_calendar)
        self.calendar_apply.setEnabled(False)
        layout.addWidget(self.calendar_apply)
        self.calendar_name.textChanged.connect(self._invalidate_calendar)
        self.calendar_hours.valueChanged.connect(self._invalidate_calendar)
        self.calendar_epoch.valueChanged.connect(self._invalidate_calendar)
        self.calendar_months.textChanged.connect(self._invalidate_calendar)

    def _build_history(self):
        layout = self._page("History")
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setAccessibleName("Campaign time history")
        layout.addWidget(self.history)

    def _error(self, error):
        self.message.setText(str(error))
        return False

    def _invalidate_time(self, *_):
        self._preview = None
        for key in ("advance", "travel", "rest"):
            if hasattr(self, key + "_apply"):
                getattr(self, key + "_apply").setEnabled(False)
                getattr(self, key + "_preview").clear()

    def _invalidate_calendar(self, *_):
        self._calendar_preview = None
        if not self._loading_calendar:
            self._calendar_dirty = True
        if hasattr(self, "calendar_apply"):
            self.calendar_apply.setEnabled(False)
            self.calendar_review.clear()

    def _show_preview(self, preview, key):
        self._invalidate_time()
        state = self.repository.get_clock(self.campaign_id)
        if (state.minutes, state.revision) != (preview.before_minutes, preview.revision):
            raise ValueError("The campaign clock changed. Create a fresh preview.")
        self.state = state
        self._preview = preview
        calendar = self.state.calendar
        lines = [f"From: {calendar.format(preview.before_minutes)}", f"To: {calendar.format(preview.after_minutes)}",
                 f"Reason: {preview.reason}", "", *preview.consequences, "", "Crossed events:"]
        lines.extend(f"• {calendar.format(event.at_minutes)} — {event.title}" for event in preview.events)
        if not preview.events:
            lines.append("None scheduled in this interval.")
        details = json.loads(preview.details_json)
        if "encounter_d20" in details:
            lines.extend(("", f"Travel d20: {details['encounter_d20']} · DM interprets; saved only on Apply."))
        getattr(self, key + "_preview").setPlainText("\n".join(lines))
        getattr(self, key + "_apply").setEnabled(True)
        self.message.setText("Preview only. The campaign clock has not changed.")
        return True

    def preview_advance(self):
        try:
            self.state = self.repository.get_clock(self.campaign_id)
            minutes = self.advance_days.value() * self.state.calendar.minutes_per_day + self.advance_minutes.value()
            return self._show_preview(self.repository.preview_advance(self.campaign_id, minutes, self.advance_reason.text()), "advance")
        except (ValueError, sqlite3.Error) as error:
            self._invalidate_time()
            return self._error(error)

    def preview_travel(self):
        try:
            preview = self.repository.preview_travel(self.campaign_id, self.travel_distance.text(), self.travel_speed.text(),
                       travelers=self.travelers.value(), reason=self.travel_reason.text(), encounter_roll=self.travel_roll.isChecked())
            return self._show_preview(preview, "travel")
        except (ValueError, sqlite3.Error) as error:
            self._invalidate_time()
            return self._error(error)

    def preview_rest(self):
        try:
            return self._show_preview(self.repository.preview_rest(self.campaign_id, self.rest_hours.text(), self.rest_reason.text()), "rest")
        except (ValueError, sqlite3.Error) as error:
            self._invalidate_time()
            return self._error(error)

    def apply_time(self):
        if self._preview is None:
            return self._error("Create a time-change preview first.")
        try:
            self.repository.apply_preview(self._preview)
            self.refresh()
            self.message.setText("Time change saved. Review crossed events and resource/recovery actions separately.")
            return True
        except (ValueError, sqlite3.Error) as error:
            self._invalidate_time()
            return self._error(error)

    def add_event(self):
        try:
            fresh = self.repository.get_clock(self.campaign_id)
            if fresh.calendar != self.state.calendar:
                raise ValueError("The calendar changed. Refresh before adding this event.")
            when = self.event_day.value() * self.state.calendar.minutes_per_day + self.event_hour.value() * 60 + self.event_minute.value()
            self.repository.add_event(self.campaign_id, when, self.event_title.text(), self.event_notes.text())
            self.event_title.clear()
            self.event_notes.clear()
            self.refresh()
            self.message.setText("Timeline event saved.")
            return True
        except (ValueError, sqlite3.Error) as error:
            return self._error(error)

    def cancel_event(self):
        item = self.events.currentItem()
        if item is None:
            return self._error("Select a timeline event first.")
        event = item.data(Qt.ItemDataRole.UserRole)
        if event.source == "world":
            return self._error("Manage this World Desk event in the World Desk.")
        try:
            self.repository.cancel_event(self.campaign_id, event.id)
            self.refresh()
            self.message.setText("Timeline event cancelled; its saved record is retained.")
            return True
        except (ValueError, sqlite3.Error) as error:
            return self._error(error)

    def _weather_day_changed(self, *_):
        self._weather_preview = None
        self.weather_apply.setEnabled(False)
        self.weather_text.clear()
        try:
            saved = self.repository.weather(self.campaign_id, self.weather_day.value())
            self.saved_weather.setText(f"Saved: d20 {saved['roll']} · {saved['description']}" if saved else "No weather saved for this day.")
        except (ValueError, sqlite3.Error) as error:
            self._error(error)

    def preview_weather(self):
        try:
            self._weather_preview = self.repository.preview_weather(self.campaign_id, self.weather_day.value())
            preview = self._weather_preview
            self.weather_text.setPlainText(f"Day {preview.day}: d20 {preview.roll}\n{preview.description}\n\nOriginal campaign prompt; review local effects with the DM.")
            self.weather_apply.setEnabled(True)
            self.message.setText("Weather preview only. Save it to retain this roll.")
            return True
        except (ValueError, sqlite3.Error) as error:
            self._weather_preview = None
            self.weather_apply.setEnabled(False)
            return self._error(error)

    def apply_weather(self):
        if self._weather_preview is None:
            return self._error("Roll a weather preview first.")
        try:
            self.repository.apply_weather(self._weather_preview)
            self._weather_day_changed()
            self.message.setText("Weather and its d20 roll saved.")
            return True
        except (ValueError, sqlite3.Error) as error:
            self.weather_apply.setEnabled(False)
            self._weather_preview = None
            return self._error(error)

    def preview_calendar(self):
        try:
            lines = self.calendar_months.toPlainText().splitlines()
            months = []
            for line in lines:
                if not line.strip():
                    continue
                if line.count("|") != 1:
                    raise ValueError("Each month line needs a name, |, and whole number of days.")
                name, days = line.split("|")
                try:
                    days = int(days.strip())
                except ValueError as error:
                    raise ValueError("Month lengths must be whole numbers.") from error
                months.append((name.strip(), days))
            calendar = CalendarSpec(self.calendar_name.text().strip(), tuple(months),
                                    self.calendar_hours.value(), self.calendar_epoch.value())
            self._calendar_preview = (calendar, self.state.revision)
            self.calendar_review.setText(f"{calendar.name}: {len(calendar.months)} months, {calendar.days_per_year} days/year, "
                                         f"{calendar.hours_per_day} hours/day. Current minute {self.state.minutes:,} becomes "
                                         f"{calendar.format(self.state.minutes)}. Saved minute offsets remain unchanged.")
            self.calendar_apply.setEnabled(True)
            self.message.setText("Calendar preview only.")
            return True
        except (ValueError, sqlite3.Error) as error:
            self._invalidate_calendar()
            return self._error(error)

    def apply_calendar(self):
        if self._calendar_preview is None:
            return self._error("Review the calendar definition first.")
        try:
            calendar, revision = self._calendar_preview
            self.repository.configure_calendar(self.campaign_id, calendar, expected_revision=revision)
            self._calendar_dirty = False
            self.refresh()
            self.message.setText("Calendar definition saved; elapsed minutes are unchanged.")
            return True
        except (ValueError, sqlite3.Error) as error:
            self._invalidate_calendar()
            return self._error(error)

    def refresh(self):
        try:
            state = self.repository.get_clock(self.campaign_id)
            events = self.repository.timeline(self.campaign_id)
            history = self.repository.history(self.campaign_id)
            self.state = state
            self._invalidate_time()
            self._loading_calendar = True
            self._invalidate_calendar()
            self.clock.setText(f"{state.calendar.format(state.minutes)} · campaign day {state.minutes // state.calendar.minutes_per_day:,} "
                               f"· elapsed {state.minutes:,} minutes")
            self.event_hour.setMaximum(state.calendar.hours_per_day - 1)
            self.events.clear()
            for event in events:
                suffix = " · World Desk" if event.source == "world" else ""
                item = QListWidgetItem(f"{state.calendar.format(event.at_minutes)} · {event.title}{suffix}")
                item.setData(Qt.ItemDataRole.UserRole, event)
                item.setToolTip(event.notes)
                self.events.addItem(item)
            if not self._calendar_dirty:
                self.calendar_name.setText(state.calendar.name)
                self.calendar_hours.setValue(state.calendar.hours_per_day)
                self.calendar_epoch.setValue(state.calendar.epoch_year)
                self.calendar_months.setPlainText("\n".join(f"{name} | {days}" for name, days in state.calendar.months))
            self._loading_calendar = False
            self.weather_day.setValue(min(state.minutes // state.calendar.minutes_per_day, self.weather_day.maximum()))
            self._weather_day_changed()
            lines = []
            for change in history:
                lines.append(f"{change['created_at']} · {change['before_minutes']:,} → {change['after_minutes']:,} minutes\n{change['reason']}")
                if change["payload_json"]:
                    payload = json.loads(change["payload_json"])
                    details = json.loads(payload["details_json"])
                    if "encounter_d20" in details:
                        lines.append(f"Travel d20: {details['encounter_d20']} · DM interpretation")
                lines.append("")
            self.history.setPlainText("\n".join(lines) or "No time changes recorded.")
            return True
        except (ValueError, sqlite3.Error) as error:
            self._loading_calendar = False
            return self._error(error)

    def reject(self):
        if self._calendar_dirty:
            answer = QMessageBox.question(self, "Unsaved Calendar", "Save your calendar edits before closing?",
                    QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Save and not (self.preview_calendar() and self.apply_calendar()):
                return
        super().reject()

    def closeEvent(self, event):
        if self._calendar_dirty:
            self.reject()
            event.setAccepted(not self.isVisible())
        else:
            super().closeEvent(event)
