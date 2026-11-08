from django import forms
from django.contrib.auth import get_user_model
from .models import Product, StockMovement, Supplier, Warehouse


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"


class ProductForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "sku", "name", "category", "supplier", "warehouse", "unit_price",
            "reorder_level", "target_stock", "is_active",
        ]
        widgets = {
            "unit_price": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "reorder_level": forms.NumberInput(attrs={"min": "0"}),
            "target_stock": forms.NumberInput(attrs={"min": "1"}),
        }


class StockMovementForm(StyledFormMixin, forms.Form):
    movement_type = forms.ChoiceField(choices=StockMovement.MovementType.choices)
    quantity = forms.IntegerField(min_value=1)
    note = forms.CharField(required=False, max_length=255)


class SupplierForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "email", "phone", "address"]


class WarehouseForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ["code", "name", "location"]


class ReorderRuleForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ["reorder_level", "target_stock"]


class ProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ["first_name", "last_name", "email"]
