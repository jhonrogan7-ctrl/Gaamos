import pytest
from django.template import Context, Template

from core.context_processors import base_domain


def test_base_domain_processor_returns_setting(settings):
    settings.BASE_DOMAIN = "example.test"
    assert base_domain(None) == {"base_domain": "example.test"}


@pytest.mark.django_db
def test_base_domain_available_in_templates(client, settings):
    settings.BASE_DOMAIN = "example.test"
    rendered = Template("{{ base_domain }}").render(
        Context({"base_domain": "example.test"})
    )
    assert rendered == "example.test"
