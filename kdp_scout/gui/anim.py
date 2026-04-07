"""Smooth animation helpers for KDP Scout Desktop.

Provides animated show/hide for widgets (height + opacity transitions).
All animations are parented to the target widget to prevent garbage collection crashes.
"""

from PyQt6.QtCore import (
    QEasingCurve, QPropertyAnimation, QAbstractAnimation,
)
from PyQt6.QtWidgets import QWidget, QGraphicsOpacityEffect


ANIM_DURATION = 250  # ms


def animated_toggle(widget: QWidget, show: bool, duration: int = ANIM_DURATION,
                    finished_cb=None):
    """Smoothly show/hide a widget via max-height animation."""
    # Stop any running animation on this widget
    old_anim = getattr(widget, '_kdp_anim', None)
    if old_anim and isinstance(old_anim, QAbstractAnimation):
        old_anim.stop()
        old_anim.deleteLater()

    if show:
        # Temporarily remove height constraint so sizeHint is accurate
        widget.setMaximumHeight(16777215)
        widget.setVisible(True)
        widget.adjustSize()
        target_h = widget.sizeHint().height()
        if target_h <= 0:
            target_h = 300
        # Now constrain to 0 and animate to the real target
        widget.setMaximumHeight(0)
        anim = QPropertyAnimation(widget, b"maximumHeight", widget)
        anim.setDuration(duration)
        anim.setStartValue(0)
        anim.setEndValue(target_h)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        if finished_cb:
            anim.finished.connect(finished_cb)
        # Remove constraint after animation so layout is free
        anim.finished.connect(lambda: widget.setMaximumHeight(16777215))
    else:
        current_h = widget.height()
        anim = QPropertyAnimation(widget, b"maximumHeight", widget)
        anim.setDuration(duration)
        anim.setStartValue(current_h)
        anim.setEndValue(0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.finished.connect(lambda: widget.setVisible(False))
        anim.finished.connect(lambda: widget.setMaximumHeight(16777215))
        if finished_cb:
            anim.finished.connect(finished_cb)

    widget._kdp_anim = anim
    anim.start()


def fade_in(widget: QWidget, duration: int = ANIM_DURATION):
    """Fade a widget in with opacity animation."""
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    widget.setVisible(True)

    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    widget._kdp_fade_anim = anim
    anim.start()
