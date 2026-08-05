"""A build owns its sections and rows, and owns nothing of the tenant's.

The whole design rests on rows being disposable scratch space: an abandoned
build must cost nothing, and re-extracting one document must not endanger a
menu that is already live.
"""
import pytest

from menu.models import (Branch, Company, MenuBuild, MenuBuildRow,
                         MenuBuildSection, MenuScan)


@pytest.fixture
def build(db):
    company = Company.objects.create(name='Kailash Parbat', slug='kailash')
    branch = Branch.all_objects.create(company=company, name='Lakeside', slug='lakeside')
    b = MenuBuild.objects.create(company=company)
    b.branches.add(branch)
    return b


@pytest.mark.django_db
def test_a_build_starts_as_a_draft(build):
    assert build.status == 'draft'


@pytest.mark.django_db
def test_a_build_owns_sections_in_display_order(build):
    MenuBuildSection.objects.create(build=build, name='JUICE', display_order=2)
    MenuBuildSection.objects.create(build=build, name='SNACKS', display_order=1)

    assert [s.name for s in build.sections.all()] == ['SNACKS', 'JUICE']


@pytest.mark.django_db
def test_a_section_starts_unconfirmed(build):
    section = MenuBuildSection.objects.create(build=build, name='JUICE')
    assert section.prices_confirmed is False


@pytest.mark.django_db
def test_deleting_a_build_takes_its_sections_and_rows_with_it(build):
    section = MenuBuildSection.objects.create(build=build, name='JUICE')
    MenuBuildRow.objects.create(build=build, section=section, name='Apple', price=250)

    build.delete()

    assert MenuBuildSection.objects.count() == 0
    assert MenuBuildRow.objects.count() == 0


@pytest.mark.django_db
def test_branch_list_reads_branches_without_a_tenant_context(build):
    """`build.branches.all()` raises: the M2M's related manager inherits
    Branch's fail-closed TenantManager and every wizard screen is apex. That is
    the guard working, not a bug -- so there is exactly one place that does the
    deliberate cross-tenant read, and this pins it."""
    from menu.tenancy import TenantContextRequired

    with pytest.raises(TenantContextRequired):
        list(build.branches.all())

    assert [b.slug for b in build.branch_list()] == ['lakeside']


@pytest.mark.django_db
def test_a_scan_without_a_build_is_still_valid(db):
    """The old /platform/scans/ flow creates scans with no build and must keep
    working — that is the entire reason this FK is nullable."""
    scan = MenuScan.objects.create(file='scans/x.pdf', status='queued')
    assert scan.build_id is None


@pytest.mark.django_db
def test_a_build_can_own_many_scans(build):
    MenuScan.objects.create(file='scans/1.jpg', status='queued', build=build)
    MenuScan.objects.create(file='scans/2.jpg', status='queued', build=build)

    assert build.scans.count() == 2


@pytest.mark.django_db
def test_two_sections_in_one_build_cannot_share_a_name(build):
    from django.db.utils import IntegrityError
    MenuBuildSection.objects.create(build=build, name='JUICE')
    with pytest.raises(IntegrityError):
        MenuBuildSection.objects.create(build=build, name='JUICE')


@pytest.mark.django_db
def test_a_row_records_what_was_printed_alongside_what_we_read(build):
    section = MenuBuildSection.objects.create(build=build, name='JUICE')
    row = MenuBuildRow.objects.create(
        build=build, section=section, name='Apple Juice', raw_name='Apple',
        raw_price_text='250', price=250)

    assert (row.raw_name, row.name) == ('Apple', 'Apple Juice')
    assert row.match_state == 'none'
    assert row.image_state == 'none'
    assert row.published_item_id is None
