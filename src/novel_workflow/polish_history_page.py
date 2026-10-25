"""Full-page history using the shell's navigation and existing theme tokens."""
from datetime import datetime
from pathlib import Path
import re

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer, QEvent
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QFrame, QMenu, QInputDialog, QMessageBox, QApplication, QStyle,
    QComboBox, QToolButton, QCheckBox)


class HistoryWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try: self.succeeded.emit(self.operation())
        except Exception as exc: self.failed.emit(exc)


class PolishHistoryPage(QWidget):
    def __init__(self, owner, profile):
        super().__init__(owner)
        self.owner, self.profile = owner, profile
        self.snapshots = []
        self._refresh_queued = False
        self._sort_mode = self.owner.settings.history_sort_modes.get(profile.id, 'recent')
        if self._sort_mode not in ('recent', 'chapter_desc', 'chapter_asc', 'manual'):
            self._sort_mode = 'recent'
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        subtitle = QLabel('คัดลอกเฉพาะไฟล์ในประวัติที่กด · ไม่เกี่ยวกับการคัดลอกขั้นตอนแปลหรือ Export')
        subtitle.setWordWrap(True); subtitle.setObjectName('mutedLabel'); layout.addWidget(subtitle)
        self.zip_mode = QCheckBox('คัดลอกประวัติเป็น ZIP (เฉพาะรายการที่กด)')
        self.zip_mode.setObjectName('historyCopyAsZip')
        self.zip_mode.setChecked(self.owner.settings.history_copy_as_zip)
        self.zip_mode.setToolTip('รวมไฟล์ของประวัติรายการเดียวเป็น ZIP · ไม่กระทบขั้นตอน Workflow')
        self.zip_mode.toggled.connect(self._change_zip_mode)
        layout.addWidget(self.zip_mode)
        self.progress_summary = QLabel()
        self.progress_summary.setObjectName('historyProgressSummary')
        self.progress_summary.setWordWrap(True)
        layout.addWidget(self.progress_summary)
        navigation = QHBoxLayout()
        self.previous_button = QPushButton('← ชุดก่อนหน้า')
        self.previous_button.setObjectName('previousHistoryBatch')
        self.previous_button.clicked.connect(self.go_to_previous)
        navigation.addWidget(self.previous_button)
        self.resume_button = QPushButton('ไปจุดทำงานต่อ')
        self.resume_button.setObjectName('goToRecommendedHistory')
        self.resume_button.clicked.connect(self.go_to_resume)
        navigation.addWidget(self.resume_button)
        navigation.addStretch(1)
        layout.addLayout(navigation)
        self._navigation_snapshot_id = None
        self._user_navigated = False
        self._render_generation = 0
        self._user_scroll_generation = 0
        tools = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText('ค้นหาเลขบทหรือช่วงบท…')
        self.search.setAccessibleName('ค้นหาประวัติช่วงบท')
        self.search.textChanged.connect(self.render); tools.addWidget(self.search, 1)
        self.refresh_button = QPushButton('Refresh'); self.refresh_button.clicked.connect(self.refresh)
        tools.addWidget(self.refresh_button); layout.addLayout(tools)
        sort_tools = QHBoxLayout()
        sort_label = QLabel('จัดเรียง:')
        sort_label.setObjectName('mutedLabel')
        sort_tools.addWidget(sort_label)
        self.sort_selector = QComboBox()
        self.sort_selector.setObjectName('polishHistorySort')
        self.sort_selector.setAccessibleName('จัดเรียงประวัติตามเลขบทหรือเวลา')
        for label, value in (
            ('ล่าสุดก่อน', 'recent'),
            ('เลขบท: มาก → น้อย', 'chapter_desc'),
            ('เลขบท: น้อย → มาก', 'chapter_asc'),
            ('จัดเรียงด้วยตัวเอง', 'manual'),
        ):
            self.sort_selector.addItem(label, value)
        self.sort_selector.setCurrentIndex(
            max(0, self.sort_selector.findData(self._sort_mode))
        )
        self.sort_selector.currentIndexChanged.connect(self._change_sort)
        sort_tools.addWidget(self.sort_selector)
        sort_tools.addStretch(1)
        layout.addLayout(sort_tools)
        self.status = QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        self.history_scroll = scroll
        scroll.viewport().installEventFilter(self)
        scroll.verticalScrollBar().sliderPressed.connect(self._mark_user_navigation)
        scroll.verticalScrollBar().valueChanged.connect(self._sync_navigation_from_scroll)
        self.cards = QWidget(); self.cards.setObjectName('polishHistoryCards')
        self.card_layout = QVBoxLayout(self.cards)
        self.card_layout.setContentsMargins(0, 2, 0, 2); self.card_layout.setSpacing(4)
        scroll.setWidget(self.cards); layout.addWidget(scroll, 1)

    def _mark_user_navigation(self, *_args):
        self._user_navigated = True
        self._user_scroll_generation += 1
        QTimer.singleShot(0, self._sync_navigation_from_scroll)

    def _sync_navigation_from_scroll(self, *_args):
        if getattr(self, '_programmatic_scroll', False):
            return
        position = self.history_scroll.verticalScrollBar().value()
        for snapshot in self._ordered_snapshots():
            card = self._cards_by_id.get(self._snapshot_id(snapshot))
            if card is not None and card.y() + card.height() > position:
                self._navigation_snapshot_id = self._snapshot_id(snapshot)
                break

    def eventFilter(self, watched, event):
        if watched is self.history_scroll.viewport() and event.type() == QEvent.Wheel:
            self._mark_user_navigation()
        return super().eventFilter(watched, event)

    def _change_zip_mode(self, enabled):
        previous = self.owner.settings.history_copy_as_zip
        self.owner.settings.history_copy_as_zip = enabled
        try:
            self.owner.repo.save_settings(self.owner.settings)
        except (OSError, ValueError) as error:
            self.owner.settings.history_copy_as_zip = previous
            self.zip_mode.blockSignals(True)
            self.zip_mode.setChecked(previous)
            self.zip_mode.blockSignals(False)
            self.failed('บันทึกโหมดคัดลอก ZIP ไม่สำเร็จ: ' + str(error))
            return
        # Update existing controls immediately, without depending on Qt deferred deletion.
        self.owner.update_copy_mode_labels()
        self._update_progress_summary()

    def refresh(self):
        if self.owner._history_pending:
            self.status.setText('กำลังรอการบันทึกประวัติ…')
            if not self._refresh_queued and self.owner._history_workers:
                self._refresh_queued = True
                def after_job():
                    self._refresh_queued = False
                    self.refresh()
                self.owner._history_workers[-1].finished.connect(after_job)
            return
        self.status.setText('กำลังตรวจสอบไฟล์และ Hash…')
        mime = QApplication.clipboard().mimeData()
        urls = [u.toLocalFile() for u in mime.urls()] if mime else []
        step_id = self.profile.polish_history_step_id
        self.owner.run_history_job(
            lambda: self.owner.polish_history.list(self.profile, step_id=step_id, clipboard_paths=urls),
            self.loaded, self.failed,
        )

    def loaded(self, snapshots):
        self.snapshots = snapshots
        count = sum(x.manifest.get('file_count', 0) for x in snapshots if not x.error)
        size = sum(sum(e['size'] for e in x.manifest['files']) for x in snapshots if not x.error)
        self.status.setText(f'{len(snapshots)} ประวัติ · {count} ไฟล์ · {size / (1024 * 1024):,.2f} MB')
        self._update_progress_summary()
        self.render()
        if not self._user_navigated:
            QTimer.singleShot(0, self.go_to_resume)

    def _progress_key(self):
        step_id = self.profile.polish_history_step_id or 'all'
        return f'{self.profile.id}:{step_id}'

    def _update_progress_summary(self):
        events = self._copy_events()
        state = self.owner.settings.history_copy_state.get(self._progress_key(), {})
        last_event = max(events, key=lambda item: str(item.get('timestamp') or ''), default=state)
        last = last_event.get('chapter_range')
        forward = self._forward_progress_end(events)
        legacy_end = self._legacy_resume_end()
        if legacy_end is not None:
            forward = max(forward, legacy_end) if forward is not None else legacy_end
        candidate = self._recommended_snapshot(forward)
        self._recommended = candidate
        copied = self._copied_snapshot_ids(events)
        if not copied and state.get('snapshot_id'):
            copied.add(str(state['snapshot_id']))
        skipped = self._skipped_ranges(copied, forward)
        timestamp = state.get('timestamp')
        timestamp = last_event.get('timestamp')
        if timestamp:
            try: timestamp = datetime.fromisoformat(timestamp).astimezone().strftime('%d/%m/%Y %H:%M')
            except (ValueError, TypeError): pass
        self.progress_summary.setText(
            f"ประวัติทั้งหมด {len(self.snapshots)} ชุด · เคยคัดลอกแล้ว {len(copied)} ชุด\n"
            f"คัดลอกล่าสุด: {'บท ' + str(last).replace('-', '–') if last else 'ไม่มีข้อมูล'}"
            f"{(' · ' + str(timestamp)) if timestamp else ''}    "
            f"ชุดถัดไป: {'บท ' + str(candidate.manifest.get('chapter_range')).replace('-', '–') if candidate else 'ถึงรายการสุดท้ายแล้ว'}"
            f"    รายการที่ข้ามไว้: {skipped} ชุด"
        )
        chapter_snapshots = self._chapter_ordered_snapshots()
        # Resume remains useful at the end of the recorded history: its handler
        # falls back to the latest available chapter when no next batch exists.
        self.resume_button.setEnabled(bool(chapter_snapshots))
        self.previous_button.setEnabled(bool(chapter_snapshots))

    def _copy_events(self):
        events = self.owner.settings.history_copy_events.get(self._progress_key(), [])
        if not isinstance(events, list):
            return []
        return [item for item in events if isinstance(item, dict) and item.get('result') == 'clipboard_set']

    @staticmethod
    def _copied_snapshot_ids(events):
        return {str(item.get('snapshot_id')) for item in events if item.get('snapshot_id')}

    def _forward_progress_end(self, events):
        ends = [bounds[1] for event in events
                if (bounds := self._chapter_range(type('RangeValue', (), {
                    'manifest': {'chapter_range': event.get('chapter_range')}
                })()))]
        return max(ends) if ends else None

    def _legacy_resume_end(self):
        legacy = self.owner.settings.history_resume_positions.get(self._progress_key(), {})
        span = legacy.get('chapter_range') if isinstance(legacy, dict) else legacy
        if not span:
            return None
        bounds = self._chapter_range(type('RangeValue', (), {'manifest': {'chapter_range': span}})())
        return bounds[1] if bounds else None

    def _chapter_ordered_snapshots(self):
        return sorted(
            (item for item in self.snapshots if not item.error and self._chapter_range(item)),
            key=lambda item: (self._chapter_range(item)[0], self._chapter_range(item)[1], self._snapshot_id(item)),
        )

    def _skipped_ranges(self, copied_ids, forward):
        if forward is None:
            return 0
        seen = set()
        for item in self._chapter_ordered_snapshots():
            bounds = self._chapter_range(item)
            if bounds[1] >= forward:
                continue
            marker = (bounds, self._snapshot_id(item))
            if self._snapshot_id(item) not in copied_ids:
                seen.add(marker)
        return len(seen)

    def _recommended_snapshot(self, forward=None):
        if forward is None:
            forward = self._forward_progress_end(self._copy_events())
        legacy_end = self._legacy_resume_end()
        if legacy_end is not None:
            forward = max(forward, legacy_end) if forward is not None else legacy_end
        copied = self._copied_snapshot_ids(self._copy_events())
        state = self.owner.settings.history_copy_state.get(self._progress_key(), {})
        if state.get('snapshot_id'):
            copied.add(str(state['snapshot_id']))
        candidates = [item for item in self._chapter_ordered_snapshots()
                      if self._snapshot_id(item) not in copied
                      and (forward is None or self._chapter_range(item)[0] > forward)]
        return candidates[0] if candidates else None

    def _scroll_to_snapshot(self, snapshot):
        if snapshot is None:
            return
        self._navigation_snapshot_id = self._snapshot_id(snapshot)
        card = getattr(self, '_cards_by_id', {}).get(self._navigation_snapshot_id)
        if card:
            self._programmatic_scroll = True
            # Use the rebuilt card's content coordinates after layout, then set
            # the scrollbar explicitly. ensureWidgetVisible() can be a no-op
            # while the card layout is being rebuilt or the utility page is
            # switching stacks.
            def reveal():
                if not card or not self.cards:
                    self._programmatic_scroll = False
                    return
                self.cards.layout().activate()
                top = card.mapTo(self.cards, self.cards.rect().topLeft()).y()
                bottom = top + card.height()
                bar = self.history_scroll.verticalScrollBar()
                margin = 24
                target = bar.value()
                if top < target + margin:
                    target = max(bar.minimum(), top - margin)
                elif bottom > target + self.history_scroll.viewport().height() - margin:
                    target = bottom - self.history_scroll.viewport().height() + margin
                bar.setValue(max(bar.minimum(), min(bar.maximum(), target)))
                QTimer.singleShot(0, lambda: setattr(self, '_programmatic_scroll', False))
            QTimer.singleShot(0, reveal)

    def go_to_resume(self):
        self._user_navigated = True
        snapshot = self._recommended_snapshot()
        if snapshot is None:
            ordered = self._chapter_ordered_snapshots()
            if not ordered:
                self.status.setText('ยังไม่มีชุดประวัติที่พร้อมใช้งาน')
                return
            snapshot = ordered[-1]
            self.status.setText('ถึงรายการสุดท้ายแล้ว · แสดงชุดล่าสุดที่มีเลขบท')
        self.search.clear()
        self.render()
        QTimer.singleShot(0, lambda s=snapshot: self._scroll_to_snapshot(s))

    def go_to_previous(self):
        self._user_navigated = True
        ordered = self._chapter_ordered_snapshots()
        if not ordered:
            return
        current_id = self._navigation_snapshot_id
        current_index = next((i for i, item in enumerate(ordered) if self._snapshot_id(item) == current_id), None)
        if current_index is None:
            target = ordered[-1]
        else:
            target = ordered[max(0, current_index - 1)]
        self.search.clear()
        self.render()
        QTimer.singleShot(0, lambda s=target: self._scroll_to_snapshot(s))

    def on_copy_success(self, snapshot, *, advanced=False):
        self._update_progress_summary()
        self.render()
        if advanced:
            self._user_navigated = False
            QTimer.singleShot(0, self.go_to_resume)

    def set_resume_position(self, snapshot):
        span = snapshot.manifest.get('chapter_range')
        if not span:
            return
        key = self._progress_key()
        previous = self.owner.settings.history_resume_positions.get(key)
        self.owner.settings.history_resume_positions[key] = {
            'profile_id': self.profile.id,
            'step_id': str(snapshot.manifest.get('step_id') or self.profile.polish_history_step_id or 'all'),
            'snapshot_id': str(snapshot.manifest.get('snapshot_id') or snapshot.path.name),
            'chapter_range': str(span),
        }
        try:
            self.owner.repo.save_settings(self.owner.settings)
        except (OSError, ValueError) as exc:
            if previous is None: self.owner.settings.history_resume_positions.pop(key, None)
            else: self.owner.settings.history_resume_positions[key] = previous
            self.failed('บันทึกจุดทำงานต่อไม่ได้: ' + str(exc))
            return
        self._update_progress_summary()
        self.render()
        self.status.setText('กำหนดจุดทำงานต่อเป็นบท ' + str(span).replace('-', '–'))

    def failed(self, error):
        self.status.setText(str(error))

    @staticmethod
    def _snapshot_id(snapshot):
        return str(snapshot.manifest.get('snapshot_id') or snapshot.path)

    @staticmethod
    def _chapter_range(snapshot):
        span = str(snapshot.manifest.get('chapter_range') or '')
        match = re.fullmatch(r'\s*(\d+)(?:\s*[-–]\s*(\d+))?\s*', span)
        if match is None:
            return None
        return int(match.group(1)), int(match.group(2) or match.group(1))

    def _ordered_snapshots(self, mode=None):
        mode = mode or self._sort_mode
        # Service returns newest first; Python's stable sort retains that
        # ordering for equal chapter keys or unresolved ranges.
        snapshots = list(self.snapshots)
        if mode in ('chapter_asc', 'chapter_desc'):
            def key(snapshot):
                span = self._chapter_range(snapshot)
                if span is None:
                    return (1, 0, 0)
                start, end = span
                if mode == 'chapter_desc':
                    return (0, -start, -end)
                return (0, start, end)
            return sorted(snapshots, key=key)
        if mode == 'manual':
            identifiers = self.owner.settings.history_manual_order.get(self.profile.id, [])
            if not isinstance(identifiers, list):
                identifiers = []
            by_id = {self._snapshot_id(s): s for s in snapshots}
            existing = [by_id[i] for i in identifiers if i in by_id]
            used = {self._snapshot_id(s) for s in existing}
            # New snapshots appear first, without disturbing manually placed
            # existing rows; removed snapshots never get restored.
            return [s for s in snapshots if self._snapshot_id(s) not in used] + existing
        return snapshots

    def _persist_sort(self):
        try:
            self.owner.repo.save_settings(self.owner.settings)
        except (OSError, ValueError) as exc:
            self.failed('บันทึกการจัดเรียงไม่ได้: ' + str(exc))

    def _change_sort(self, _index):
        choice = self.sort_selector.currentData()
        if choice not in ('recent', 'chapter_desc', 'chapter_asc', 'manual'):
            return
        if choice == 'manual' and self._sort_mode != 'manual':
            # Manual mode starts with exactly the order currently visible.
            self.owner.settings.history_manual_order[self.profile.id] = [
                self._snapshot_id(s) for s in self._ordered_snapshots()
            ]
        self._sort_mode = choice
        self.owner.settings.history_sort_modes[self.profile.id] = choice
        self._persist_sort()
        self.render()

    def _move_snapshot(self, snapshot, direction):
        if self._sort_mode != 'manual':
            return
        arranged = self._ordered_snapshots()
        identities = [self._snapshot_id(s) for s in arranged]
        current = self._snapshot_id(snapshot)
        if current not in identities:
            return
        index = identities.index(current)
        new_index = index + direction
        if not 0 <= new_index < len(identities):
            return
        identities[index], identities[new_index] = identities[new_index], identities[index]
        self.owner.settings.history_manual_order[self.profile.id] = identities
        self._persist_sort()
        self.render()

    def render(self, *_):
        # Rebuilding every row after a copy used to collapse the scroll area to
        # its first row. Keep the viewport where it was unless the caller has
        # explicitly requested navigation (for example, to the next batch).
        scroll_bar = self.history_scroll.verticalScrollBar()
        prior_scroll_value = scroll_bar.value()
        render_generation = self._render_generation = self._render_generation + 1
        user_scroll_generation = self._user_scroll_generation
        self._cards_by_id = {}
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        query = self.search.text().strip().replace('–', '-')
        ordered = self._ordered_snapshots()
        found = []
        for snapshot in ordered:
            span = str(snapshot.manifest.get('chapter_range', ''))
            match = not query or query in span
            if query.isdigit() and span:
                try:
                    bounds = [int(x) for x in span.split('-')]
                    match = bounds[0] <= int(query) <= bounds[-1]
                except (ValueError, TypeError): pass
            if match: found.append(snapshot)
        # Sequential UI labels follow the selected (and optionally filtered)
        # presentation order. The immutable manifest ID is never modified.
        for index, snapshot in enumerate(found):
            card = QFrame(); card.setObjectName('polishHistoryRow')
            snapshot_id = self._snapshot_id(snapshot)
            recommended = getattr(self, '_recommended', None)
            is_recommended = bool(recommended and self._snapshot_id(recommended) == snapshot_id)
            if is_recommended:
                card.setProperty('recommendedNext', True)
                card.setStyleSheet('QFrame#polishHistoryRow[recommendedNext="true"] { border: 2px solid #4386d8; border-radius: 7px; }')
            rows = QHBoxLayout(card); rows.setContentsMargins(8, 0, 8, 0); rows.setSpacing(6)
            # Global button styling enforces a 48 px hit target on Windows.
            card.setMinimumHeight(60)
            # Keep number → chapter/details → copy as one left-aligned group.
            # Destructive actions stay isolated on the far right.
            sequence = QLabel(str(index + 1))
            sequence.setObjectName('historySequenceNumber')
            sequence.setAlignment(Qt.AlignCenter)
            sequence.setFixedSize(36, 36)
            sequence.setToolTip('ลำดับรายการที่แสดง')
            sequence.setAccessibleName(f'ลำดับ {index + 1}')
            rows.addWidget(sequence)
            text_column = QVBoxLayout(); text_column.setContentsMargins(0, 0, 0, 0); text_column.setSpacing(0)
            # Keep the chapter details and copy action grouped at the left.
            # Giving this layout a stretch factor pushed the copy button to the
            # horizontal center on wide windows.
            rows.addLayout(text_column)
            span = snapshot.manifest.get('chapter_range')
            title = QLabel(('บท ' + str(span).replace('-', '–')) if span else 'รอระบุช่วงบท')
            title.setObjectName('historyRangeTitle')
            title.setWordWrap(False)
            text_column.addWidget(title)
            copy_state = self.owner.settings.history_copy_state.get(self._progress_key(), {})
            copied_ids = self._copied_snapshot_ids(self._copy_events())
            if copy_state.get('snapshot_id'):
                copied_ids.add(str(copy_state['snapshot_id']))
            row_status = []
            copied = snapshot_id in copied_ids
            badge_text = ('✓  คัดลอกแล้ว' if copied else ('→  ชุดถัดไป' if is_recommended else '○  ยังไม่ได้คัดลอก'))
            badge = QLabel(badge_text)
            badge.setObjectName('historyCopyState')
            badge.setStyleSheet('font-size: 16px; font-weight: 700; color: #24834a;' if copied else
                                ('font-size: 16px; font-weight: 700; color: #2868b2;' if is_recommended else
                                 'font-size: 14px; color: palette(mid);'))
            text_column.addWidget(badge)
            zipped = self.owner.settings.history_copy_as_zip
            copy = QPushButton('คัดลอก ZIP' if zipped else 'คัดลอก')
            copy.setObjectName('polishHistoryCopy')
            copy.setFixedHeight(32)
            copy.setToolTip('รวมไฟล์ทั้งหมดของรายการนี้เป็น ZIP เดียว · วางด้วย Ctrl+V' if zipped
                            else 'คัดลอกไฟล์ทั้งหมดของรายการนี้ · วางด้วย Ctrl+V')
            changed_payload = snapshot.error.startswith('ไฟล์ในประวัติถูกแก้ไขหรือ Hash ไม่ตรง:')
            copy.setEnabled(not snapshot.error or changed_payload)
            if changed_payload:
                copy.setToolTip('ไฟล์ในประวัติถูกแก้ไข · คลิกเพื่อยืนยันไฟล์ที่แก้แล้วและคัดลอก')
            copy.setAccessibleName(f'ลำดับ {index + 1} ' + title.text() + ' คัดลอกไฟล์ทั้งหมด')
            copy.clicked.connect(lambda _=False, s=snapshot: self.copy_snapshot(s))
            rows.addWidget(copy)
            if self._sort_mode == 'manual':
                up = QToolButton()
                up.setObjectName('polishHistoryMoveUp')
                up.setText('↑')
                up.setToolTip('เลื่อนประวัติขึ้น')
                up.setAccessibleName(f'เลื่อนบท {span} ขึ้น')
                up.setFixedWidth(25)
                up.setFixedHeight(28)
                up.setEnabled(index > 0 and not self.search.text().strip())
                up.clicked.connect(lambda _=False, s=snapshot: self._move_snapshot(s, -1))
                rows.addWidget(up)
                down = QToolButton()
                down.setObjectName('polishHistoryMoveDown')
                down.setText('↓')
                down.setToolTip('เลื่อนประวัติลง')
                down.setAccessibleName(f'เลื่อนบท {span} ลง')
                down.setFixedWidth(25)
                down.setFixedHeight(28)
                down.setEnabled(index < len(found) - 1 and not self.search.text().strip())
                down.clicked.connect(lambda _=False, s=snapshot: self._move_snapshot(s, 1))
                rows.addWidget(down)
            rows.addStretch(1)
            delete = QPushButton(); delete.setObjectName('polishHistoryDelete')
            delete.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
            delete.setToolTip('ลบประวัตินี้ไปยังถังรีไซเคิล')
            delete.setAccessibleName(f'ลำดับ {index + 1} ' + title.text() + ' ลบประวัตินี้ไปยังถังรีไซเคิล')
            delete.setFixedWidth(32)
            delete.setFixedHeight(32)
            delete.setStyleSheet('QPushButton:hover { background: #f6caca; color: #782020; }')
            delete.clicked.connect(lambda _=False, s=snapshot, b=delete: self.delete_snapshot(s, b))
            rows.addWidget(delete)
            more = QPushButton('⋯'); more.setAccessibleName(f'ลำดับ {index + 1} ' + title.text() + ' ตัวเลือกเพิ่มเติม')
            more.clicked.connect(lambda _=False, s=snapshot, b=more: self.more_menu(s, b))
            more.setFixedSize(28, 32); rows.addWidget(more)
            try: stamp = datetime.fromisoformat(snapshot.manifest['created_at']).astimezone().strftime('%H:%M')
            except (KeyError, ValueError, TypeError): stamp = snapshot.path.name
            review_status = snapshot.manifest.get('review_status', 'รอตรวจ')
            detail = QLabel(
                f'{stamp} · {snapshot.manifest.get("file_count", 0) if not snapshot.error else "?"} ไฟล์ · ตรวจ: {review_status}'
            )
            detail.setWordWrap(False); detail.setObjectName('historyCopyState')
            detail.setToolTip(f'สถานะคัดลอก: {badge_text}\nสถานะตรวจคำแปล: {review_status}')
            detail.setStyleSheet('font-size: 12px; color: palette(mid);'); text_column.addWidget(detail)
            if snapshot.error:
                error = QLabel('ตรวจพบข้อผิดพลาด: ' + snapshot.error); error.setWordWrap(True)
                text_column.addWidget(error)
            if snapshot.warning:
                warning = QLabel(snapshot.warning); warning.setWordWrap(True)
                text_column.addWidget(warning)
            self.card_layout.addWidget(card)
            self._cards_by_id[self._snapshot_id(snapshot)] = card
        if not found:
            empty = QLabel('ยังไม่มีประวัติ\nเลือกขั้นตอนใน Settings แล้วคลิกขั้นตอนเพื่อบันทึกไฟล์'
                           if not self.snapshots else 'ไม่พบช่วงบทที่ค้นหา')
            empty.setWordWrap(True); empty.setObjectName('emptyStateDescription'); self.card_layout.addWidget(empty)
        self.card_layout.addStretch()

        def restore_viewport():
            if (render_generation != self._render_generation
                    or user_scroll_generation != self._user_scroll_generation):
                return
            self.card_layout.activate()
            bar = self.history_scroll.verticalScrollBar()
            bar.setValue(max(bar.minimum(), min(bar.maximum(), prior_scroll_value)))
        QTimer.singleShot(0, restore_viewport)

    def copy_snapshot(self, snapshot):
        """Only explicitly confirmed historical edits may update stored hashes."""
        if not snapshot.error:
            self.owner.copy_history_snapshot(self.profile, snapshot)
            return
        if not snapshot.error.startswith('ไฟล์ในประวัติถูกแก้ไขหรือ Hash ไม่ตรง:'):
            self.failed('ไฟล์ประวัติเสียหายหรือหายไป ไม่สามารถคัดลอกได้')
            return
        confirmation = QMessageBox.question(
            self, 'ยืนยันไฟล์ที่แก้ไขในประวัติ',
            'ไฟล์สำรองในประวัติชุดนี้ถูกแก้ไขหลังบันทึก\\n\\n'
            'หากคุณแก้ไขไฟล์นี้โดยตั้งใจ ให้กด Yes เพื่อเก็บ Hash เดิม'
            ' ไว้เป็นประวัติ ตรวจไฟล์ที่แก้ใหม่ แล้วคัดลอก\\n\\n'
            'หากไม่ได้แก้เอง ให้กด No และตรวจไฟล์ก่อน',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirmation != QMessageBox.Yes:
            return
        zipped = self.owner.settings.history_copy_as_zip
        def operation():
            modified = self.owner.polish_history.accept_snapshot_edits(
                self.profile, snapshot.path
            )
            paths = self.owner.polish_history.clipboard_paths(
                self.profile, snapshot.path, zipped=zipped
            )
            count = len(paths)
            if zipped:
                import zipfile
                with zipfile.ZipFile(paths[0]) as archive:
                    count = sum(not item.is_dir() for item in archive.infolist())
            return paths, count, modified
        def success(result):
            paths, count, modified = result
            try:
                self.owner._history_clipboard(paths, count, zipped)
            except Exception as exc:
                self.failed('ส่งไฟล์ไปยัง Clipboard ไม่สำเร็จ: ' + str(exc))
                return
            try:
                self.owner._record_history_copy_success(self.profile, snapshot, count, zipped)
            except Exception as exc:
                self.failed('คัดลอกไฟล์แล้ว แต่บันทึกประวัติการคัดลอกไม่สำเร็จ: ' + str(exc))
                return
            self.refresh()
        self.owner.run_history_job(operation, success, self.failed)

    def delete_snapshot(self, snapshot, button=None):
        if self.owner.history_busy():
            self.status.setText('กำลังจัดการประวัติ กรุณารอสักครู่')
            return
        mime = QApplication.clipboard().mimeData()
        urls = [u.toLocalFile() for u in mime.urls()] if mime else []
        if button: button.setEnabled(False)
        def failed(error):
            if button:
                try:
                    button.setEnabled(True)
                except RuntimeError:
                    # A concurrent history refresh may already have rebuilt the row.
                    pass
            self.failed('ลบประวัติไม่สำเร็จ: ' + str(error))
        def deleted(_):
            self.status.setText('ย้ายประวัติไปยังถังรีไซเคิลแล้ว · Clipboard คงเดิม')
            self.refresh()
        self.owner.run_history_job(lambda: self.owner.polish_history.delete(self.profile, snapshot.path, urls),
                                   deleted, failed)

    def more_menu(self, snapshot, button):
        menu = QMenu(button)
        rename = menu.addAction('แก้ไขช่วงบท'); rename.setEnabled(not snapshot.error)
        status = menu.addAction('ทำเครื่องหมายตรวจแล้ว' if snapshot.manifest.get('review_status', 'รอตรวจ') == 'รอตรวจ'
                                else 'ตั้งเป็นรอตรวจ')
        status.setEnabled(not snapshot.error)
        open_folder = menu.addAction('เปิดโฟลเดอร์')
        verify = menu.addAction('ตรวจสอบไฟล์อีกครั้ง')
        delete = menu.addAction('ลบประวัติไปยังถังรีไซเคิล')
        action = menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        if action == open_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(snapshot.path)))
        elif action == verify: self.refresh()
        elif action == status:
            target = 'ตรวจแล้ว' if snapshot.manifest.get('review_status', 'รอตรวจ') == 'รอตรวจ' else 'รอตรวจ'
            self.owner.run_history_job(lambda: self.owner.polish_history.set_review_status(self.profile, snapshot.path, target),
                                       lambda _: self.refresh(), self.failed)
        elif action == rename:
            value, accepted = QInputDialog.getText(self, 'ระบุช่วงบท', 'ช่วงบท เช่น 6-10', text=snapshot.manifest.get('chapter_range') or '')
            if accepted:
                mime = QApplication.clipboard().mimeData()
                urls = [u.toLocalFile() for u in mime.urls()] if mime else []
                self.owner.run_history_job(lambda: self.owner.polish_history.rename(self.profile, snapshot.path, value, clipboard_paths=urls),
                                           lambda _: self.refresh(), self.failed)
        elif action == delete:
            self.delete_snapshot(snapshot)
