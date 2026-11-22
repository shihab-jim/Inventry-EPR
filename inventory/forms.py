from django import forms
from django.contrib.auth import get_user_model
from .models import Category, Product, StockMovement, Supplier, Warehouse


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


class CategoryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name"]


class ReorderRuleForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ["reorder_level", "target_stock"]


class ProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ["first_name", "last_name", "email"]


class AdminUserCreateForm(StyledFormMixin, forms.Form):
    ROLE_CHOICES = (
        ("viewer", "Viewer (Catalog & Stock In/Out)"),
        ("staff", "Administrator (Full Staff Access)"),
    )
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={"placeholder": "e.g. john_doe"})
    )
    first_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "e.g. John"})
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Doe"})
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={"placeholder": "e.g. john@company.com"})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Minimum 6 characters"}),
        required=True,
        min_length=6
    )
    role = forms.ChoiceField(choices=ROLE_CHOICES, initial="viewer")

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        User = get_user_model()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("A user with this username already exists.")
        return username
