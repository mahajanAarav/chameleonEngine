"""The engine as it was before the learned picker (hand-set score only). For A/B tests."""

import engine.picker as picker
import engine.resize as R


def resize_old(source, target_canvas):
    original = picker.Picker.load
    picker.Picker.load = classmethod(lambda cls: None)
    try:
        return R.resize(source, target_canvas)
    finally:
        picker.Picker.load = original
