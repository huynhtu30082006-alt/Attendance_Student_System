from django import forms

from .models import Setting


class ThresholdForm(forms.ModelForm):
    """Use case 25: the value must be a number from 0 to 100 (percent)."""

    class Meta:
        model = Setting
        fields = ["absence_threshold"]
        labels = {"absence_threshold": "Absence warning threshold (%)"}
        error_messages = {
            "absence_threshold": {
                "required": "Enter the threshold as a number from 0 to 100.",
                "invalid": "Enter the threshold as a number from 0 to 100.",
                "min_value": "The threshold must be between 0 and 100.",
                "max_value": "The threshold must be between 0 and 100.",
                "max_digits": "Enter at most 2 decimal places.",
                "max_decimal_places": "Enter at most 2 decimal places.",
                "max_whole_digits": "The threshold must be between 0 and 100.",
            }
        }
