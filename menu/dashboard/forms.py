from django import forms
from django.utils.text import slugify
from menu.models import MenuItem


class MenuItemForm(forms.ModelForm):
    DIETARY_CHOICES = [
        ('VEG', 'VEG'), ('VEGAN', 'VEGAN'), ('HALAL', 'HALAL'),
        ('GF', 'GF'), ('SPICY', 'SPICY'),
    ]
    dietary_tags = forms.MultipleChoiceField(
        choices=DIETARY_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    image_url = forms.CharField(required=False)

    class Meta:
        model = MenuItem
        fields = [
            'name', 'price', 'description',
            'dietary_tags', 'image_url', 'is_popular', 'is_featured',
        ]

    def clean_dietary_tags(self):
        return self.cleaned_data.get('dietary_tags', [])

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.pk:
            base = slugify(instance.name)
            slug = base
            counter = 1
            while MenuItem.objects.filter(slug=slug).exists():
                slug = f"{base}-{counter}"
                counter += 1
            instance.slug = slug
        if commit:
            instance.save()
        return instance
