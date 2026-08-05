"""The `Item` model as a library: the fields phase 1 adds and the index the
matcher will need. `status='active'` means "in the library"."""
import pytest
from django.contrib.postgres.search import TrigramSimilarity

from menu.models import Company, Item


@pytest.mark.django_db
def test_a_library_entry_roundtrips_its_new_fields():
    company = Company.objects.create(name='Chill Zone', slug='chillzone')
    item = Item.objects.create(
        name='Chicken Chowmein', search_name='chicken chowmein', status='active',
        image_prompt='chicken chowmein, wok-tossed noodles', use_count=3,
        origin_company=company, shareable=True)
    item.refresh_from_db()
    assert item.search_name == 'chicken chowmein'
    assert item.image_prompt.startswith('chicken chowmein')
    assert item.use_count == 3
    assert item.origin_company_id == company.pk
    assert item.shareable is True


@pytest.mark.django_db
def test_the_defaults_are_the_safe_ones():
    """A row nobody has counted has been used by nobody, and an entry is
    shareable unless something says otherwise -- venue photographs say so."""
    item = Item.objects.create(name='Black Tea')
    assert item.search_name == ''
    assert item.image_prompt == ''
    assert item.use_count == 0
    assert item.origin_company_id is None
    assert item.shareable is True


@pytest.mark.django_db
def test_deleting_the_origin_company_does_not_delete_the_entry():
    """A venue leaving must not take the library's entries with it."""
    company = Company.objects.create(name='Gone', slug='gone')
    item = Item.objects.create(name='Veg Momo', origin_company=company, status='active')
    company.delete()
    item.refresh_from_db()
    assert item.origin_company_id is None


@pytest.mark.django_db
def test_trigram_similarity_ranks_a_misspelling_above_a_different_dish():
    """Proves pg_trgm is installed, not just that Django can spell the query.
    This is phase 3's matcher layer 2 on its feet a phase early."""
    Item.objects.create(name='Chicken Chowmein', search_name='chicken chowmein',
                        status='active')
    Item.objects.create(name='Chicken Chilly', search_name='chicken chilly',
                        status='active')
    ranked = (Item.objects.filter(status='active')
              .annotate(sim=TrigramSimilarity('search_name', 'chiken chowmein'))
              .order_by('-sim'))
    assert ranked[0].search_name == 'chicken chowmein'
    assert ranked[0].sim > 0.35
    assert ranked[1].sim < ranked[0].sim
